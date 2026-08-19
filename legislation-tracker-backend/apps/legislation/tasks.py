"""
Celery tasks: BillContract generation plus topic and similarity updates.
"""
import logging
import re

from celery import shared_task
from django.db import transaction
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
    ProcessingStatus,
    Topic,
)
from apps.legislation.topic_taxonomy import TOPICS

logger = logging.getLogger(__name__)

CONTRACT_SCHEMA_VERSION = "1.1-deterministic"
STUB_SCHEMA_VERSION = CONTRACT_SCHEMA_VERSION
SIMILARITY_METHOD = "deterministic-v1"
SIMILARITY_MIN_SCORE = 0.2

_TAXONOMY_BY_SLUG = {entry["slug"]: entry for entry in TOPICS}
_KEYWORD_INDEX = [
    (entry["slug"], [keyword.lower() for keyword in entry["keywords"]])
    for entry in TOPICS
]
GENERIC_SINGLE_HIT_KEYWORDS = {"infrastructure"}


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


def _source_text(document: BillDocument, bill: Bill):
    text = (document.extracted_text or "").strip()
    if text:
        return text
    return (bill.summary or bill.title or "").strip()


def _sentence_spans(text):
    spans = []
    for match in re.finditer(r"[^.!?]+[.!?]", text):
        raw = match.group()
        leading = len(raw) - len(raw.lstrip())
        sentence = raw.strip()
        if not sentence:
            continue
        start = match.start() + leading
        spans.append({"text": sentence, "start": start, "end": start + len(sentence)})
    trailing_start = spans[-1]["end"] if spans else 0
    trailing = text[trailing_start:].strip()
    if trailing:
        start = text.find(trailing, trailing_start)
        spans.append({"text": trailing, "start": start, "end": start + len(trailing)})
    return spans


def _is_heading(sentence):
    return bool(re.fullmatch(r"(section|sec)\.?\s+[0-9a-zA-Z-]+\.?", sentence.lower()))


def _first_meaningful_sentence(sentences):
    for sentence in sentences:
        if not _is_heading(sentence["text"]):
            return sentence
    return sentences[0] if sentences else None


def _matches_any(sentence, keywords):
    text = sentence["text"].lower()
    return any(re.search(rf"\b{re.escape(keyword)}\b", text) for keyword in keywords)


def _matching_sentences(sentences, keywords, limit=5):
    matches = []
    for sentence in sentences:
        if _matches_any(sentence, keywords):
            matches.append(sentence)
        if len(matches) >= limit:
            break
    return matches


def _contract_item(sentence, category):
    return {"text": sentence["text"], "category": category}


def _add_evidence(evidence, field_path, quote, source_text, start=None):
    if not quote:
        return
    if start is None:
        start = source_text.find(quote)
    if start < 0:
        return
    evidence.append(
        {
            "field_path": field_path,
            "quoted_text": quote,
            "start_char": start,
            "end_char": start + len(quote),
        }
    )


def _build_contract(document: BillDocument, bill: Bill):
    """Build deterministic structured contract JSON and exact source citations."""
    source_text = _source_text(document, bill)
    sentences = _sentence_spans(source_text)
    summary_sentence = _first_meaningful_sentence(sentences)
    key_sentences = [s for s in sentences if not _is_heading(s["text"])][:5]
    if summary_sentence and summary_sentence not in key_sentences:
        key_sentences.insert(0, summary_sentence)
    key_sentences = key_sentences[:5]
    requirement_sentences = _matching_sentences(
        sentences,
        {"shall", "must", "require", "requires", "required", "prohibit", "prohibits"},
    )
    funding_sentences = _matching_sentences(
        sentences,
        {"appropriated", "authorization", "authorized", "fund", "funding", "grant", "$"},
    )
    effective_date_sentences = _matching_sentences(
        sentences,
        {"effective", "takes effect", "enactment"},
    )
    summary_text = (
        summary_sentence["text"]
        if summary_sentence
        else (bill.summary or bill.title or "")
    )
    source_excerpt = source_text[:500]
    contract_json = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "title": bill.title,
        "version_label": document.version_label,
        # Compatibility for the current client.
        "plain_summary": summary_text,
        "source_excerpt": source_excerpt,
        "summary": {"text": summary_text, "basis": "first substantive source sentence"},
        "key_points": [_contract_item(sentence, "key_point") for sentence in key_sentences],
        "requirements": [
            _contract_item(sentence, "requirement") for sentence in requirement_sentences
        ],
        "funding_mentions": [
            _contract_item(sentence, "funding") for sentence in funding_sentences
        ],
        "effective_dates": [
            _contract_item(sentence, "effective_date")
            for sentence in effective_date_sentences
        ],
        "limitations": [
            "This deterministic summary cites exact source sentences and is not legal advice."
        ],
    }
    evidence = []
    summary_start = summary_sentence["start"] if summary_sentence else None
    _add_evidence(evidence, "plain_summary", summary_text, source_text, summary_start)
    _add_evidence(evidence, "summary.text", summary_text, source_text, summary_start)
    _add_evidence(evidence, "source_excerpt", source_excerpt, source_text, 0)
    for index, sentence in enumerate(key_sentences):
        _add_evidence(
            evidence,
            f"key_points[{index}].text",
            sentence["text"],
            source_text,
            sentence["start"],
        )
    for index, sentence in enumerate(requirement_sentences):
        _add_evidence(
            evidence,
            f"requirements[{index}].text",
            sentence["text"],
            source_text,
            sentence["start"],
        )
    for index, sentence in enumerate(funding_sentences):
        _add_evidence(
            evidence,
            f"funding_mentions[{index}].text",
            sentence["text"],
            source_text,
            sentence["start"],
        )
    for index, sentence in enumerate(effective_date_sentences):
        _add_evidence(
            evidence,
            f"effective_dates[{index}].text",
            sentence["text"],
            source_text,
            sentence["start"],
        )
    return contract_json, evidence


def _build_metadata_contract(bill: Bill):
    summary_text = (bill.summary or bill.title or "").strip()
    contract_json = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "title": bill.title,
        "version_label": "metadata",
        "plain_summary": summary_text,
        "source_excerpt": summary_text[:500],
        "summary": {
            "text": summary_text,
            "basis": "bill metadata from source API",
        },
        "key_points": (
            [{"text": summary_text, "category": "key_point"}] if summary_text else []
        ),
        "requirements": [],
        "funding_mentions": [],
        "effective_dates": [],
        "limitations": [
            "This deterministic summary cites available metadata and is not legal advice."
        ],
    }
    return contract_json


@shared_task
def generate_contract_for_bill(bill_id):
    """
    Create a metadata-only contract when document text is not available yet.
    """
    bill = Bill.objects.filter(pk=bill_id).first()
    if not bill:
        return {"bill_id": bill_id, "skipped": True, "reason": "no_bill"}

    contract_json = _build_metadata_contract(bill)
    new_hash = contract_hash_from_dict(contract_json)
    latest = bill.latest_contract
    if latest and latest.contract_hash == new_hash:
        update_topics.apply_async(kwargs={"bill_id": bill.id})
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

    update_topics.apply_async(kwargs={"bill_id": bill.id})
    logger.info(
        "generate_contract_for_bill: bill_id=%s contract_id=%s",
        bill.id,
        contract.id,
    )
    return {"bill_id": bill.id, "contract_id": contract.id, "contract_hash": new_hash}


@shared_task
def generate_contract(document_id):
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

    bill = document.bill
    contract_json, evidence_spans = _build_contract(document, bill)
    new_hash = contract_hash_from_dict(contract_json)

    latest = (
        BillContract.objects.filter(document=document)
        .order_by("-id")
        .first()
    )
    if latest and latest.contract_hash == new_hash:
        update_fields = ["contract_generated_at"]
        document.contract_generated_at = timezone.now()
        document.save(update_fields=update_fields)
        if document.is_active_version:
            bill.latest_contract = latest
            if bill.processing_status != ProcessingStatus.COMPLETE:
                bill.processing_status = ProcessingStatus.COMPLETE
                bill.save(update_fields=["latest_contract", "processing_status"])
            else:
                bill.save(update_fields=["latest_contract"])
        update_topics.apply_async(args=[latest.id])
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
                "schema_version": CONTRACT_SCHEMA_VERSION,
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

        if contract_created:
            ChangeLog.objects.create(
                bill=bill,
                document=document,
                contract=contract,
                change_type="contract_update",
                old_value={"contract_hash": latest.contract_hash} if latest else None,
                new_value={
                    "contract_id": contract.id,
                    "contract_hash": new_hash,
                    "schema_version": CONTRACT_SCHEMA_VERSION,
                },
            )

            for span in evidence_spans:
                EvidenceSpan.objects.create(
                    bill=bill,
                    document=document,
                    contract=contract,
                    field_path=span["field_path"],
                    start_char=span["start_char"],
                    end_char=span["end_char"],
                    quoted_text=span["quoted_text"],
                    page_number=None,
                )

    update_topics.apply_async(args=[contract.id])

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

    old_slugs = list(
        BillTopic.objects.filter(bill=bill)
        .order_by("topic__slug")
        .values_list("topic__slug", flat=True)
    )
    matches = infer_topic_matches(bill=bill, contract=contract)
    new_slugs = [slug for slug, _confidence in matches]
    confidence_by_slug = dict(matches)
    with transaction.atomic():
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
    schedule_similarity_for_bill.apply_async(args=[bill.id])
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
    for bill in bills:
        contract = bill.latest_contract
        if not contract:
            continue
        update_topics.apply_async(args=[contract.id])
        enqueued += 1

    logger.info(
        "backfill_update_topics: enqueued=%s (session=%s)",
        enqueued,
        session,
    )
    return {"enqueued": enqueued, "session": session}


@shared_task
def schedule_similarity_for_bill(bill_id):
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
    for bill_id in bill_ids:
        schedule_similarity_for_bill.apply_async(args=[bill_id])
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
