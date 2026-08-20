"""
Celery tasks: BillContract generation plus topic and similarity updates.
"""
import logging
import re
import time

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.changelog.models import ChangeLog
from apps.ingestion.document_download import reextract_stored_document_text
from apps.ingestion.work_queue import enqueue_ingestion_work
from apps.legislation.contract_json import contract_hash_from_dict
from apps.legislation.extraction.legacy import (
    LEGACY_SCHEMA_VERSION,
    build_legacy_metadata_contract,
)
from apps.legislation.extraction.service import extract_contract
from apps.legislation.extraction.types import EXTRACTOR_VERSION
from apps.legislation.models import (
    Bill,
    BillContract,
    BillDocument,
    BillSimilarity,
    BillTopic,
    EvidenceSpan,
    ProcessingStatus,
    Topic,
)
from apps.legislation.topic_taxonomy import TOPICS

logger = logging.getLogger(__name__)

CONTRACT_SCHEMA_VERSION = LEGACY_SCHEMA_VERSION
STUB_SCHEMA_VERSION = CONTRACT_SCHEMA_VERSION
SIMILARITY_METHOD = "deterministic-v1"
SIMILARITY_MIN_SCORE = 0.2

WORK_KIND_DOCUMENT_CONTRACT = "document_contract"
WORK_KIND_METADATA_CONTRACT = "metadata_contract"
WORK_KIND_TOPIC_UPDATE = "topic_update"
WORK_KIND_SIMILARITY = "similarity"
SOURCE_REEXTRACTION_VERSION = "structured-source-1.0.0"

_TAXONOMY_BY_SLUG = {entry["slug"]: entry for entry in TOPICS}
_KEYWORD_INDEX = [
    (entry["slug"], [keyword.lower() for keyword in entry["keywords"]])
    for entry in TOPICS
]
GENERIC_SINGLE_HIT_KEYWORDS = {"infrastructure"}


def enqueue_document_contract(document, *, reextract_source=False):
    reextraction_suffix = (
        f":{SOURCE_REEXTRACTION_VERSION}" if reextract_source else ""
    )
    return enqueue_ingestion_work(
        kind=WORK_KIND_DOCUMENT_CONTRACT,
        dedupe_key=(
            f"{document.id}:{document.content_hash or 'pending'}:{EXTRACTOR_VERSION}"
            f"{reextraction_suffix}"
        ),
        source_updated_at=document.created_at or timezone.now(),
        payload_json={
            "document_id": document.id,
            **({"reextract_source": True} if reextract_source else {}),
        },
        jurisdiction=document.bill.jurisdiction,
        congress=document.bill.session,
    )


def enqueue_metadata_contract(bill):
    return enqueue_ingestion_work(
        kind=WORK_KIND_METADATA_CONTRACT,
        dedupe_key=f"{bill.id}:{bill.metadata_hash or 'metadata'}",
        source_updated_at=bill.updated_at or timezone.now(),
        payload_json={"bill_id": bill.id},
        jurisdiction=bill.jurisdiction,
        congress=bill.session,
    )


def enqueue_topic_update(*, contract=None, bill=None, source_updated_at=None):
    if contract:
        bill = contract.bill
        dedupe_key = f"contract:{contract.id}:{contract.contract_hash}"
        source_updated_at = source_updated_at or contract.computed_at or timezone.now()
        payload_json = {"contract_id": contract.id}
    elif bill:
        dedupe_key = f"bill:{bill.id}:{bill.metadata_hash or 'metadata'}"
        source_updated_at = source_updated_at or bill.updated_at or timezone.now()
        payload_json = {"bill_id": bill.id}
    else:
        raise ValueError("A contract or bill is required for topic work")
    return enqueue_ingestion_work(
        kind=WORK_KIND_TOPIC_UPDATE,
        dedupe_key=dedupe_key,
        source_updated_at=source_updated_at,
        payload_json=payload_json,
        jurisdiction=bill.jurisdiction,
        congress=bill.session,
    )


def enqueue_similarity(bill, *, source_updated_at=None):
    contract = bill.latest_contract
    fingerprint = contract.contract_hash if contract else bill.metadata_hash or "metadata"
    source_updated_at = source_updated_at or (
        contract.computed_at if contract and contract.computed_at else bill.updated_at
    ) or timezone.now()
    return enqueue_ingestion_work(
        kind=WORK_KIND_SIMILARITY,
        dedupe_key=f"{bill.id}:{fingerprint}",
        source_updated_at=source_updated_at,
        payload_json={"bill_id": bill.id},
        jurisdiction=bill.jurisdiction,
        congress=bill.session,
    )


def _topic_name(slug):
    entry = _TAXONOMY_BY_SLUG.get(slug)
    return entry["name"] if entry else slug.replace("-", " ").title()


def _topic_description(slug):
    entry = _TAXONOMY_BY_SLUG.get(slug)
    return entry.get("description") if entry else None


def _flatten_contract_value(value):
    if isinstance(value, dict):
        return " ".join(_flatten_contract_value(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_contract_value(v) for v in value)
    if value is None:
        return ""
    return str(value)


def _tokenize_text(text):
    stop_words = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "be",
        "bill",
        "by",
        "for",
        "in",
        "is",
        "of",
        "on",
        "or",
        "the",
        "this",
        "to",
        "with",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(token) > 2 and token not in stop_words
    }


def _bill_similarity_features(bill):
    latest_contract_json = {}
    if bill.latest_contract_id:
        latest_contract_json = bill.latest_contract.contract_json or {}
    topic_slugs = set(
        bill.bill_topics.values_list("topic__slug", flat=True)
    )
    text = " ".join(
        [
            bill.title or "",
            bill.summary or "",
            _flatten_contract_value(latest_contract_json),
        ]
    )
    return {"tokens": _tokenize_text(text), "topics": topic_slugs}


def _jaccard(left, right):
    if not left and not right:
        return 0.0
    return len(left & right) / len(left | right)


def compute_bill_similarity_score(left_bill, right_bill):
    left = _bill_similarity_features(left_bill)
    right = _bill_similarity_features(right_bill)
    topic_score = _jaccard(left["topics"], right["topics"])
    token_score = _jaccard(left["tokens"], right["tokens"])
    return round((topic_score * 0.6) + (token_score * 0.4), 6)


def _ordered_bill_pair(left_id, right_id):
    return (left_id, right_id) if left_id < right_id else (right_id, left_id)


def _topic_source_text(*, bill, contract=None):
    return " ".join(
        [
            bill.title or "",
            bill.summary or "",
            _flatten_contract_value(contract.contract_json if contract else {}),
        ]
    )


def _keyword_matches(text, keyword):
    keyword = keyword.lower()
    if " " in keyword:
        return keyword in text
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


def infer_topic_matches(*, bill, contract=None, max_topics=5):
    """Infer canonical taxonomy topic slugs and confidence from bill/contract text."""
    text = re.sub(
        r"\s+",
        " ",
        _topic_source_text(bill=bill, contract=contract).lower(),
    )
    is_long = len(text) > 500
    matches = []
    for slug, keywords in _KEYWORD_INDEX:
        matched_keywords = [
            keyword for keyword in keywords if _keyword_matches(text, keyword)
        ]
        hit_count = len(matched_keywords)
        min_hits = max(2, len(keywords) // 8) if is_long else 1
        if (
            hit_count == 1
            and matched_keywords[0] in GENERIC_SINGLE_HIT_KEYWORDS
        ):
            continue
        if hit_count >= min_hits:
            confidence = min(hit_count / len(keywords), 1.0)
            matches.append((slug, round(confidence, 4)))
    matches.sort(key=lambda item: (-item[1], item[0]))
    return matches[:max_topics]


def infer_topic_slugs(contract):
    """Infer stable policy topic slugs from a bill contract and bill metadata."""
    return [slug for slug, _confidence in infer_topic_matches(bill=contract.bill, contract=contract)]


@shared_task
def generate_contract_for_bill(bill_id):
    return _generate_contract_for_bill_impl(bill_id)


def _generate_contract_for_bill_impl(bill_id):
    """
    Create a metadata-only contract when document text is not available yet.
    """
    bill = Bill.objects.filter(pk=bill_id).first()
    if not bill:
        return {"bill_id": bill_id, "skipped": True, "reason": "no_bill"}

    contract_json = build_legacy_metadata_contract(bill)
    new_hash = contract_hash_from_dict(contract_json)
    latest = bill.latest_contract
    if latest and latest.contract_hash == new_hash:
        enqueue_topic_update(bill=bill)
        return {
            "bill_id": bill.id,
            "contract_id": latest.id,
            "unchanged": True,
        }

    with transaction.atomic():
        contract, contract_created = BillContract.objects.get_or_create(
            bill=bill,
            document__isnull=True,
            contract_hash=new_hash,
            defaults={
                "document": None,
                "schema_version": CONTRACT_SCHEMA_VERSION,
                "contract_json": contract_json,
            },
        )
        bill.latest_contract = contract
        if bill.processing_status != ProcessingStatus.COMPLETE:
            bill.processing_status = ProcessingStatus.COMPLETE
            bill.save(update_fields=["latest_contract", "processing_status"])
        else:
            bill.save(update_fields=["latest_contract"])

        if contract_created:
            ChangeLog.objects.create(
                bill=bill,
                contract=contract,
                change_type="contract_update",
                old_value={"contract_hash": latest.contract_hash} if latest else None,
                new_value={
                    "contract_id": contract.id,
                    "contract_hash": new_hash,
                    "schema_version": CONTRACT_SCHEMA_VERSION,
                },
            )

    enqueue_topic_update(bill=bill)
    logger.info(
        "generate_contract_for_bill: bill_id=%s contract_id=%s",
        bill.id,
        contract.id,
    )
    return {"bill_id": bill.id, "contract_id": contract.id, "contract_hash": new_hash}


@shared_task
def generate_contract(document_id, reextract_source=False):
    return _generate_contract_impl(
        document_id,
        reextract_source=reextract_source,
    )


def _replace_evidence_spans(*, bill, document, contract, evidence_spans):
    """Replace one document contract's source offsets with the current extraction."""
    EvidenceSpan.objects.filter(contract=contract, document=document).delete()
    EvidenceSpan.objects.bulk_create(
        [
            EvidenceSpan(
                bill=bill,
                document=document,
                contract=contract,
                field_path=span.field_path,
                start_char=span.start_char,
                end_char=span.end_char,
                quoted_text=span.quoted_text,
                page_number=span.page_number,
            )
            for span in evidence_spans
        ]
    )


def _generate_contract_impl(document_id, *, reextract_source=False):
    """
    Build or skip BillContract from BillDocument.extracted_text.
    Sets Bill.latest_contract, ChangeLog(contract_update), EvidenceSpan rows;
    enqueues topic and similarity recomputation.
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

    if reextract_source:
        refreshed_text = reextract_stored_document_text(document)
        if refreshed_text != (document.extracted_text or ""):
            document.extracted_text = refreshed_text or None
            document.parsed_at = timezone.now() if refreshed_text else None
            document.save(update_fields=["extracted_text", "parsed_at"])

    bill = document.bill
    extraction_started = time.monotonic()
    extraction_result = extract_contract(document=document, bill=bill)
    duration_ms = int((time.monotonic() - extraction_started) * 1_000)
    contract_json = extraction_result.contract_json
    evidence_spans = extraction_result.evidence
    extraction_metadata = contract_json.get("extraction", {})
    logger.info(
        "contract_extraction_completed",
        extra={
            "extraction_document_id": document.id,
            "extraction_bill_id": bill.id,
            "extraction_schema": extraction_result.schema_version,
            "extraction_method": extraction_result.method,
            "extraction_parser_version": extraction_metadata.get("parser_version"),
            "extraction_category_counts": {
                category: len(contract_json.get(category, []))
                for category in (
                    "requirements",
                    "funding_items",
                    "timeline_items",
                    "definitions",
                    "applicability",
                    "amendment_operations",
                )
            },
            "extraction_sections_seen": extraction_metadata.get("sections_seen"),
            "extraction_sections_with_claims": extraction_metadata.get(
                "sections_with_claims"
            ),
            "extraction_warnings": extraction_metadata.get("warnings", []),
            "extraction_fallback_reason": extraction_result.fallback_reason,
            "extraction_duration_ms": duration_ms,
        },
    )
    new_hash = contract_hash_from_dict(contract_json)

    latest = (
        BillContract.objects.filter(document=document)
        .order_by("-id")
        .first()
    )
    if latest and latest.contract_hash == new_hash:
        with transaction.atomic():
            _replace_evidence_spans(
                bill=bill,
                document=document,
                contract=latest,
                evidence_spans=evidence_spans,
            )
            document.contract_generated_at = timezone.now()
            document.save(update_fields=["contract_generated_at"])
            if document.is_active_version:
                bill.latest_contract = latest
                if bill.processing_status != ProcessingStatus.COMPLETE:
                    bill.processing_status = ProcessingStatus.COMPLETE
                    bill.save(update_fields=["latest_contract", "processing_status"])
                else:
                    bill.save(update_fields=["latest_contract"])
        if document.is_active_version:
            enqueue_topic_update(contract=latest)
        logger.info(
            "generate_contract: unchanged hash for document_id=%s, skipping",
            document_id,
        )
        return {"document_id": document_id, "contract_id": latest.id, "unchanged": True}

    with transaction.atomic():
        contract, contract_created = BillContract.objects.get_or_create(
            bill=bill,
            document=document,
            contract_hash=new_hash,
            defaults={
                "schema_version": extraction_result.schema_version,
                "contract_json": contract_json,
            },
        )
        if document.is_active_version:
            bill.latest_contract = contract
            bill.processing_status = ProcessingStatus.COMPLETE
            bill.save(update_fields=["latest_contract", "processing_status"])
        now = timezone.now()
        document.contract_generated_at = now
        document.save(update_fields=["contract_generated_at"])

        if contract_created and document.is_active_version:
            ChangeLog.objects.create(
                bill=bill,
                document=document,
                contract=contract,
                change_type="contract_update",
                old_value={"contract_hash": latest.contract_hash} if latest else None,
                new_value={
                    "contract_id": contract.id,
                    "contract_hash": new_hash,
                    "schema_version": extraction_result.schema_version,
                },
            )
        _replace_evidence_spans(
            bill=bill,
            document=document,
            contract=contract,
            evidence_spans=evidence_spans,
        )

    if document.is_active_version:
        enqueue_topic_update(contract=contract)

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


@shared_task
def update_topics(contract_id=None, bill_id=None):
    return _update_topics_impl(contract_id=contract_id, bill_id=bill_id)


def _update_topics_impl(contract_id=None, bill_id=None):
    """
    Infer Topic tags from a BillContract or Bill and update BillTopic.
    """
    logger.info(
        "update_topics: starting contract_id=%s bill_id=%s",
        contract_id,
        bill_id,
    )
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
            if (
                bill.latest_contract_id is not None
                and bill.latest_contract_id != contract.id
            ):
                contract = bill.latest_contract
    if bill is None and bill_id:
        bill = Bill.objects.filter(pk=bill_id).first()
        if bill and bill.latest_contract_id:
            contract = bill.latest_contract
    if not bill:
        logger.warning(
            "update_topics: no bill found contract_id=%s bill_id=%s",
            contract_id,
            bill_id,
        )
        return {
            "contract_id": contract_id,
            "bill_id": bill_id,
            "skipped": True,
            "reason": "not_found",
        }

    with transaction.atomic():
        bill = (
            Bill.objects.select_for_update()
            .select_related("latest_contract")
            .filter(pk=bill.pk)
            .first()
        )
        if bill is None:
            return {
                "contract_id": contract_id,
                "bill_id": bill_id,
                "skipped": True,
                "reason": "not_found",
            }
        if bill.latest_contract_id:
            contract = bill.latest_contract
        old_slugs = list(
            BillTopic.objects.filter(bill=bill)
            .order_by("topic__slug")
            .values_list("topic__slug", flat=True)
        )
        matches = infer_topic_matches(bill=bill, contract=contract)
        new_slugs = [slug for slug, _confidence in matches]
        confidence_by_slug = dict(matches)
        contract_id_before_match = contract.id if contract else None
        bill.refresh_from_db(fields=["latest_contract"])
        if (
            bill.latest_contract_id is not None
            and bill.latest_contract_id != contract_id_before_match
        ):
            logger.info(
                "update_topics: contract superseded during matching bill_id=%s "
                "contract_id=%s latest_contract_id=%s",
                bill.id,
                contract_id_before_match,
                bill.latest_contract_id,
            )
            return {
                "contract_id": contract_id_before_match,
                "bill_id": bill.id,
                "skipped": True,
                "reason": "superseded",
            }
        topics = []
        for slug in new_slugs:
            topic, _ = Topic.objects.get_or_create(
                slug=slug,
                defaults={
                    "name": _topic_name(slug),
                    "description": _topic_description(slug),
                },
            )
            topics.append(topic)

        BillTopic.objects.filter(bill=bill).exclude(topic__slug__in=new_slugs).delete()
        for topic in topics:
            bill_topic, created = BillTopic.objects.get_or_create(
                bill=bill,
                topic=topic,
                defaults={"confidence_score": confidence_by_slug.get(topic.slug)},
            )
            if not created and bill_topic.confidence_score != confidence_by_slug.get(topic.slug):
                bill_topic.confidence_score = confidence_by_slug.get(topic.slug)
                bill_topic.save(update_fields=["confidence_score"])

        if set(old_slugs) != set(new_slugs):
            ChangeLog.objects.create(
                bill=bill,
                contract=contract,
                change_type="topic_update",
                old_value={"topics": old_slugs},
                new_value={
                    "topics": new_slugs,
                    "contract_id": contract.id if contract else None,
                },
            )

    logger.info(
        "update_topics: success bill_id=%s contract_id=%s topics=%s",
        bill.id,
        contract.id if contract else None,
        new_slugs,
    )
    enqueue_similarity(bill)
    return {
        "contract_id": contract.id if contract else None,
        "bill_id": bill.id,
        "topics": new_slugs,
    }


@shared_task
def backfill_update_topics(session=None):
    """Enqueue topic inference for the latest contract on every matching bill."""
    bills = (
        Bill.objects.filter(latest_contract__isnull=False)
        .select_related("latest_contract")
        .order_by("id")
    )
    if session is not None:
        bills = bills.filter(session=int(session))

    enqueued = 0
    backfill_requested_at = timezone.now()
    for bill in bills:
        contract = bill.latest_contract
        if not contract:
            continue
        enqueue_topic_update(
            contract=contract,
            source_updated_at=backfill_requested_at,
        )
        enqueued += 1

    logger.info(
        "backfill_update_topics: enqueued=%s (session=%s)",
        enqueued,
        session,
    )
    return {"enqueued": enqueued, "session": session}


@shared_task
def schedule_similarity_for_bill(bill_id):
    return _schedule_similarity_for_bill_impl(bill_id)


def _schedule_similarity_for_bill_impl(bill_id):
    """
    Phase 6: recompute deterministic BillSimilarity rows for one bill.
    """
    bill = (
        Bill.objects.select_related("latest_contract")
        .prefetch_related("bill_topics__topic")
        .filter(pk=bill_id)
        .first()
    )
    if not bill:
        logger.warning("schedule_similarity_for_bill: bill_id=%s not found", bill_id)
        return {"bill_id": bill_id, "skipped": True, "reason": "not_found"}

    candidates = (
        Bill.objects.exclude(pk=bill.id)
        .select_related("latest_contract")
        .prefetch_related("bill_topics__topic")
        .order_by("id")
    )
    computed = 0
    removed = 0
    for candidate in candidates:
        score = compute_bill_similarity_score(bill, candidate)
        bill_a_id, bill_b_id = _ordered_bill_pair(bill.id, candidate.id)
        if score < SIMILARITY_MIN_SCORE:
            deleted, _ = BillSimilarity.objects.filter(
                bill_a_id=bill_a_id,
                bill_b_id=bill_b_id,
                method=SIMILARITY_METHOD,
            ).delete()
            removed += deleted
            continue
        BillSimilarity.objects.update_or_create(
            bill_a_id=bill_a_id,
            bill_b_id=bill_b_id,
            method=SIMILARITY_METHOD,
            defaults={"similarity_score": score},
        )
        computed += 1

    logger.info(
        "schedule_similarity_for_bill: bill_id=%s computed=%s removed=%s",
        bill.id,
        computed,
        removed,
    )
    return {"bill_id": bill.id, "computed": computed, "removed": removed}


@shared_task
def recompute_similarity_batch(session=None, batch_size=None):
    """Enqueue deterministic similarity recomputation for matching bills."""
    bills = Bill.objects.all().order_by("id")
    if session is not None:
        bills = bills.filter(session=int(session))
    bill_ids = bills.values_list("id", flat=True)
    if batch_size is not None:
        bill_ids = bill_ids[: int(batch_size)]
    enqueued = 0
    recompute_requested_at = timezone.now()
    for bill_id in bill_ids:
        bill = Bill.objects.get(pk=bill_id)
        enqueue_similarity(bill, source_updated_at=recompute_requested_at)
        enqueued += 1
    logger.info(
        "recompute_similarity_batch: enqueued=%s (session=%s batch_size=%s)",
        enqueued,
        session,
        batch_size,
    )
    result = {"enqueued": enqueued, "session": session}
    if batch_size is not None:
        result["batch_size"] = batch_size
    return result
