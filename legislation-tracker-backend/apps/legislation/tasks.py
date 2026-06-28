"""
Celery tasks: BillContract generation (Phase 5), topic inference + similarity (Phase 6).
"""
import hashlib
import json
import logging

from celery import shared_task
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.changelog.models import ChangeLog
from apps.legislation.contract_json import contract_hash_from_dict
from apps.legislation.models import (
    Bill,
    BillContract,
    BillDocument,
    BillSimilarity,
    BillTopic,
    EvidenceSpan,
    Topic,
)
from apps.legislation.topic_taxonomy import TOPICS

logger = logging.getLogger(__name__)

STUB_SCHEMA_VERSION = "1.0-stub"


# ---------------------------------------------------------------------------
# Phase 5: generate_contract (unchanged)
# ---------------------------------------------------------------------------


def _build_stub_contract_json(bill: Bill, document: BillDocument | None = None) -> dict:
    """Minimal structured interpretation from bill metadata (and document text if available)."""
    text = ""
    if document:
        text = (document.extracted_text or "").strip()
    if not text:
        text = (bill.summary or bill.title or "").strip()
    excerpt = text[:2000] if text else ""
    return {
        "schema_version": STUB_SCHEMA_VERSION,
        "title": bill.title,
        "plain_summary": excerpt[:1200] if excerpt else bill.title,
        "source_excerpt": excerpt[:500],
        "version_label": document.version_label if document else "ingestion",
    }


def generate_contract_for_bill(bill_id):
    """
    Create or update stub BillContract from bill title/summary alone.
    Called synchronously during ingestion — no document required.
    """
    bill = Bill.objects.filter(pk=bill_id).first()
    if not bill:
        return {"bill_id": bill_id, "skipped": True, "reason": "no_bill"}

    contract_json = _build_stub_contract_json(bill)
    new_hash = contract_hash_from_dict(contract_json)

    latest = bill.latest_contract
    if latest and latest.contract_hash == new_hash:
        return {"bill_id": bill_id, "unchanged": True}

    with transaction.atomic():
        contract = BillContract.objects.create(
            bill=bill,
            document=None,
            schema_version=STUB_SCHEMA_VERSION,
            contract_json=contract_json,
            contract_hash=new_hash,
        )
        bill.latest_contract = contract
        bill.save(update_fields=["latest_contract"])

        ChangeLog.objects.create(
            bill=bill,
            contract=contract,
            change_type="contract_update",
            old_value={"contract_hash": latest.contract_hash} if latest else None,
            new_value={
                "contract_id": contract.id,
                "contract_hash": new_hash,
                "schema_version": STUB_SCHEMA_VERSION,
            },
        )

    logger.info("generate_contract_for_bill: bill_id=%s contract_id=%s", bill_id, contract.id)
    return {"bill_id": bill_id, "contract_id": contract.id, "contract_hash": new_hash}


@shared_task
def generate_contract(document_id):
    """
    Upgrade BillContract with document text after download.
    Replaces the stub contract with a richer one when extracted_text is available.
    """
    logger.info("generate_contract: starting document_id=%s", document_id)
    document = (
        BillDocument.objects.select_related("bill")
        .filter(pk=document_id)
        .first()
    )
    if not document:
        logger.warning("generate_contract: BillDocument %s not found", document_id)
        return {"document_id": document_id, "skipped": True, "reason": "no_document"}

    bill = document.bill
    contract_json = _build_stub_contract_json(bill, document)
    new_hash = contract_hash_from_dict(contract_json)

    latest = bill.latest_contract
    if latest and latest.contract_hash == new_hash:
        logger.info(
            "generate_contract: unchanged hash for document_id=%s, skipping",
            document_id,
        )
        return {"document_id": document_id, "unchanged": True}

    with transaction.atomic():
        contract = BillContract.objects.create(
            bill=bill,
            document=document,
            schema_version=STUB_SCHEMA_VERSION,
            contract_json=contract_json,
            contract_hash=new_hash,
        )
        bill.latest_contract = contract
        bill.save(update_fields=["latest_contract"])
        now = timezone.now()
        document.contract_generated_at = now
        document.save(update_fields=["contract_generated_at"])

        ChangeLog.objects.create(
            bill=bill,
            document=document,
            contract=contract,
            change_type="contract_update",
            old_value={"contract_hash": latest.contract_hash} if latest else None,
            new_value={
                "contract_id": contract.id,
                "contract_hash": new_hash,
                "schema_version": STUB_SCHEMA_VERSION,
            },
        )

        for key, value in contract_json.items():
            if isinstance(value, (dict, list)):
                quoted = json.dumps(value, ensure_ascii=False)[:2000]
            else:
                quoted = str(value)[:2000]
            end_char = max(len(quoted), 1)
            EvidenceSpan.objects.create(
                bill=bill,
                document=document,
                contract=contract,
                field_path=key,
                start_char=0,
                end_char=end_char,
                quoted_text=quoted,
                page_number=None,
            )

    update_topics(bill_id=bill.id)

    logger.info(
        "generate_contract: created contract_id=%s document_id=%s",
        contract.id,
        document_id,
    )
    return {
        "document_id": document_id,
        "contract_id": contract.id,
        "contract_hash": new_hash,
    }


# ---------------------------------------------------------------------------
# Phase 6.1: update_topics — keyword-based topic inference
# ---------------------------------------------------------------------------

# Pre-build a lowercased keyword → topic-slug lookup at import time.
_KEYWORD_INDEX: list[tuple[str, list[str]]] = []
for _entry in TOPICS:
    _KEYWORD_INDEX.append(
        (_entry["slug"], [kw.lower() for kw in _entry["keywords"]])
    )


def _extract_searchable_text(bill: Bill, contract: BillContract | None) -> str:
    """Combine bill metadata + contract fields into one blob for keyword matching."""
    parts = [
        bill.title or "",
        bill.summary or "",
    ]
    if contract:
        cj = contract.contract_json or {}
        for key in ("plain_summary", "source_excerpt", "title"):
            val = cj.get(key)
            if isinstance(val, str):
                parts.append(val)
    return " ".join(parts).lower()


def _compute_topic_set_hash(topic_slugs: list[str]) -> str:
    """Stable hash of the sorted topic slug list for change detection."""
    canonical = "|".join(sorted(topic_slugs))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _match_topics(text: str, max_topics: int = 3) -> list[tuple[str, float]]:
    """Return top (slug, confidence) pairs, capped to max_topics.

    For long text (documents), require >=2 hits to avoid noise.
    For short text (titles), allow 1 hit since there's less chance of false positives.
    """
    is_long = len(text) > 500
    min_hits = 2 if is_long else 1
    matches = []
    for slug, keywords in _KEYWORD_INDEX:
        hit_count = sum(1 for kw in keywords if kw in text)
        if hit_count >= min_hits:
            confidence = min(hit_count / len(keywords), 1.0)
            matches.append((slug, round(confidence, 4)))
    matches.sort(key=lambda x: x[1], reverse=True)
    return matches[:max_topics]


@shared_task
def update_topics(contract_id=None, bill_id=None):
    """
    Infer topics from bill title/summary (and contract if available) via keyword matching.
    Accepts either contract_id or bill_id. Updates BillTopic rows, logs ChangeLog(topic_update)
    when the set changes.
    """
    logger.info("update_topics: starting contract_id=%s bill_id=%s", contract_id, bill_id)

    contract = None
    bill = None

    if contract_id:
        contract = (
            BillContract.objects.select_related("bill")
            .filter(pk=contract_id)
            .first()
        )
        if contract:
            bill = contract.bill

    if bill is None and bill_id:
        bill = Bill.objects.filter(pk=bill_id).first()
        if bill and bill.latest_contract_id:
            contract = BillContract.objects.filter(pk=bill.latest_contract_id).first()

    if not bill:
        logger.warning("update_topics: no bill found (contract_id=%s, bill_id=%s)", contract_id, bill_id)
        return {"contract_id": contract_id, "bill_id": bill_id, "skipped": True, "reason": "no_bill"}

    text = _extract_searchable_text(bill, contract)
    matched = _match_topics(text)

    new_slugs = sorted(s for s, _ in matched)
    new_hash = _compute_topic_set_hash(new_slugs)

    old_topic_ids = set(
        BillTopic.objects.filter(bill=bill).values_list("topic_id", flat=True)
    )
    old_slugs = sorted(
        Topic.objects.filter(id__in=old_topic_ids).values_list("slug", flat=True)
    )
    old_hash = _compute_topic_set_hash(old_slugs)

    if new_hash == old_hash:
        logger.info(
            "update_topics: unchanged topic set for bill_id=%s (%d topics)",
            bill.id,
            len(new_slugs),
        )
        return {"contract_id": contract_id, "bill_id": bill.id, "unchanged": True}

    slug_to_confidence = dict(matched)
    topic_map = {t.slug: t for t in Topic.objects.filter(slug__in=new_slugs)}

    with transaction.atomic():
        BillTopic.objects.filter(bill=bill).delete()
        created_topics = []
        for slug in new_slugs:
            topic = topic_map.get(slug)
            if not topic:
                continue
            BillTopic.objects.create(
                bill=bill,
                topic=topic,
                confidence_score=slug_to_confidence.get(slug),
            )
            created_topics.append(
                {"slug": slug, "name": topic.name, "confidence": slug_to_confidence.get(slug)}
            )

        ChangeLog.objects.create(
            bill=bill,
            contract=contract,
            change_type="topic_update",
            old_value={"topic_slugs": old_slugs},
            new_value={"topic_slugs": new_slugs, "topic_set_hash": new_hash},
        )

    logger.info(
        "update_topics: bill_id=%s topics=%s (was %s)",
        bill.id,
        new_slugs,
        old_slugs,
    )
    return {
        "contract_id": contract_id,
        "bill_id": bill.id,
        "topics": [t["slug"] for t in created_topics],
    }


# ---------------------------------------------------------------------------
# Phase 6.2: similarity — title-based (simple first pass)
# ---------------------------------------------------------------------------

def _normalize_title(title: str) -> set[str]:
    """Tokenize and lowercase a title for Jaccard similarity."""
    import re
    words = set(re.findall(r"[a-z0-9]+", (title or "").lower()))
    _stopwords = {
        "a", "an", "the", "of", "to", "and", "in", "for", "on", "at",
        "by", "or", "is", "it", "be", "as", "no", "not", "act", "bill",
    }
    return words - _stopwords


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@shared_task
def schedule_similarity_for_bill(bill_id):
    """
    Compute title-based similarity between this bill and recent bills.
    Stores pairs where score >= threshold, enforcing bill_a_id < bill_b_id.
    """
    logger.info("schedule_similarity_for_bill: starting bill_id=%s", bill_id)
    bill = Bill.objects.filter(pk=bill_id).first()
    if not bill:
        logger.warning("schedule_similarity_for_bill: bill_id=%s not found", bill_id)
        return {"bill_id": bill_id, "skipped": True}

    tokens_a = _normalize_title(bill.title)
    if not tokens_a:
        return {"bill_id": bill_id, "pairs": 0, "reason": "empty_title"}

    candidates = (
        Bill.objects.filter(session=bill.session)
        .exclude(pk=bill.id)
        .values_list("id", "title")
    )

    threshold = 0.15
    method = "title_jaccard"
    now = timezone.now()
    pairs_upserted = 0

    for other_id, other_title in candidates:
        tokens_b = _normalize_title(other_title)
        score = _jaccard(tokens_a, tokens_b)
        if score < threshold:
            continue

        a_id, b_id = (min(bill.id, other_id), max(bill.id, other_id))
        BillSimilarity.objects.update_or_create(
            bill_a_id=a_id,
            bill_b_id=b_id,
            method=method,
            defaults={"similarity_score": round(score, 4), "computed_at": now},
        )
        pairs_upserted += 1

    logger.info(
        "schedule_similarity_for_bill: bill_id=%s pairs=%s", bill_id, pairs_upserted
    )
    return {"bill_id": bill_id, "pairs": pairs_upserted}


@shared_task
def recompute_similarity_batch(session=119, batch_size=500):
    """
    Periodic batch: recompute title similarity for bills that changed recently
    or never had similarity computed. Runs from Beat schedule.
    """
    logger.info(
        "recompute_similarity_batch: session=%s batch_size=%s", session, batch_size
    )
    computed_bill_ids = set(
        BillSimilarity.objects.filter(method="title_jaccard")
        .values_list("bill_a_id", flat=True)
        .distinct()
    ) | set(
        BillSimilarity.objects.filter(method="title_jaccard")
        .values_list("bill_b_id", flat=True)
        .distinct()
    )

    bill_ids = list(
        Bill.objects.filter(session=session)
        .exclude(id__in=computed_bill_ids)
        .order_by("id")
        .values_list("id", flat=True)[:batch_size]
    )

    if not bill_ids:
        logger.info("recompute_similarity_batch: no bills need similarity")
        return {"enqueued": 0}

    for bid in bill_ids:
        schedule_similarity_for_bill.apply_async(args=[bid])

    logger.info("recompute_similarity_batch: enqueued=%s", len(bill_ids))
    return {"enqueued": len(bill_ids)}
