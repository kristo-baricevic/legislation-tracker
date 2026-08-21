"""
Celery tasks: BillContract generation plus topic and similarity updates.
"""

import logging
import re
import time
import uuid
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from jsonschema import ValidationError

from apps.accounts.llm_credentials import (
    CredentialDecryptionError,
    decrypt_credential,
    llm_feature_available,
)
from apps.accounts.models import LLMCredential
from apps.changelog.models import ChangeLog
from apps.ingestion.document_download import reextract_stored_document_text
from apps.ingestion.work_queue import enqueue_ingestion_work
from apps.legislation.contract_json import contract_hash_from_dict
from apps.legislation.enhancements.provider_registry import get_provider
from apps.legislation.enhancements.providers.base import ProviderError, ProviderUsage
from apps.legislation.enhancements.schema import validate_enhancement_output
from apps.legislation.enhancements.source_packet import (
    PreflightUnavailable,
    build_enhancement_preflight,
)
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
    BillEnhancement,
    BillEnhancementAttempt,
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
    reextraction_suffix = f":{SOURCE_REEXTRACTION_VERSION}" if reextract_source else ""
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
    fingerprint = (
        contract.contract_hash if contract else bill.metadata_hash or "metadata"
    )
    source_updated_at = (
        source_updated_at
        or (
            contract.computed_at
            if contract and contract.computed_at
            else bill.updated_at
        )
        or timezone.now()
    )
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
    topic_slugs = set(bill.bill_topics.values_list("topic__slug", flat=True))
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
        if hit_count == 1 and matched_keywords[0] in GENERIC_SINGLE_HIT_KEYWORDS:
            continue
        if hit_count >= min_hits:
            confidence = min(hit_count / len(keywords), 1.0)
            matches.append((slug, round(confidence, 4)))
    matches.sort(key=lambda item: (-item[1], item[0]))
    return matches[:max_topics]


def infer_topic_slugs(contract):
    """Infer stable policy topic slugs from a bill contract and bill metadata."""
    return [
        slug
        for slug, _confidence in infer_topic_matches(
            bill=contract.bill, contract=contract
        )
    ]


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
        BillDocument.objects.select_related("bill").filter(pk=document_id).first()
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

    latest = BillContract.objects.filter(document=document).order_by("-id").first()
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
            BillContract.objects.select_related("bill").filter(pk=contract_id).first()
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
            Bill.objects.select_for_update(of=("self",))
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
            if not created and bill_topic.confidence_score != confidence_by_slug.get(
                topic.slug
            ):
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


ENHANCEMENT_DISPATCH_LEASE_SECONDS = 60


def _known_usage_totals(enhancement_id):
    return BillEnhancementAttempt.objects.filter(
        enhancement_id=enhancement_id,
    ).aggregate(
        input_tokens=Sum("input_tokens"),
        output_tokens=Sum("output_tokens"),
        total_tokens=Sum("total_tokens"),
    )


def _refresh_enhancement_usage(enhancement):
    totals = _known_usage_totals(enhancement.pk)
    enhancement.input_tokens = totals["input_tokens"]
    enhancement.output_tokens = totals["output_tokens"]
    enhancement.total_tokens = totals["total_tokens"]


@shared_task(autoretry_for=())
def dispatch_bill_enhancement_attempts(attempt_ids=None):
    """Lease and publish pending durable attempts; the database is authoritative."""
    now = timezone.now()
    query = BillEnhancementAttempt.objects.filter(
        status=BillEnhancementAttempt.Status.PENDING,
        available_at__lte=now,
    ).filter(
        Q(dispatch_lease_expires_at__isnull=True)
        | Q(dispatch_lease_expires_at__lte=now)
    )
    if attempt_ids is not None:
        query = query.filter(pk__in=list(attempt_ids))
    ids = list(query.order_by("available_at", "id").values_list("id", flat=True)[:100])
    published = 0
    failed = 0
    for attempt_id in ids:
        dispatch_token = uuid.uuid4().hex
        with transaction.atomic():
            attempt = (
                BillEnhancementAttempt.objects.select_for_update()
                .filter(
                    pk=attempt_id,
                    status=BillEnhancementAttempt.Status.PENDING,
                    available_at__lte=now,
                )
                .filter(
                    Q(dispatch_lease_expires_at__isnull=True)
                    | Q(dispatch_lease_expires_at__lte=now)
                )
                .first()
            )
            if attempt is None:
                continue
            attempt.dispatch_token = dispatch_token
            attempt.dispatch_lease_expires_at = now + timedelta(
                seconds=ENHANCEMENT_DISPATCH_LEASE_SECONDS
            )
            attempt.save(
                update_fields=[
                    "dispatch_token",
                    "dispatch_lease_expires_at",
                    "updated_at",
                ]
            )
        try:
            run_bill_enhancement_attempt.apply_async(args=[attempt_id, dispatch_token])
            published += 1
        # Celery transport exceptions are intentionally normalized here. The
        # durable database row is released for the next dispatcher pass.
        except Exception:  # noqa: BLE001
            failed += 1
            BillEnhancementAttempt.objects.filter(
                pk=attempt_id,
                status=BillEnhancementAttempt.Status.PENDING,
                dispatch_token=dispatch_token,
            ).update(dispatch_token="", dispatch_lease_expires_at=None)
            logger.warning(
                "Bill enhancement publish failed",
                extra={"attempt_id": attempt_id, "category": "dispatch_publish_failed"},
            )
    return {"published": published, "failed": failed}


def _claim_enhancement_attempt(attempt_id, dispatch_token):
    now = timezone.now()
    run_token = uuid.uuid4().hex
    with transaction.atomic():
        attempt = (
            BillEnhancementAttempt.objects.select_for_update()
            .select_related("enhancement")
            .filter(
                pk=attempt_id,
                status=BillEnhancementAttempt.Status.PENDING,
                dispatch_token=dispatch_token,
            )
            .first()
        )
        if attempt is None:
            return None
        attempt.status = BillEnhancementAttempt.Status.RUNNING
        attempt.run_token = run_token
        attempt.lease_expires_at = now + timedelta(
            seconds=settings.LLM_ENHANCEMENT_RUN_LEASE_SECONDS
        )
        attempt.started_at = now
        attempt.save(
            update_fields=[
                "status",
                "run_token",
                "lease_expires_at",
                "started_at",
                "updated_at",
            ]
        )
        BillEnhancement.objects.filter(pk=attempt.enhancement_id).update(
            status=BillEnhancement.Status.RUNNING,
            completed_at=None,
        )
    return run_token


def _finish_enhancement_attempt(
    *,
    attempt_id,
    run_token,
    attempt_status,
    failure_category="",
    usage=None,
    result_json=None,
    provider_response_id="",
    resolved_model="",
):
    usage = usage or ProviderUsage()
    now = timezone.now()
    with transaction.atomic():
        attempt = (
            BillEnhancementAttempt.objects.select_for_update()
            .filter(
                pk=attempt_id,
                status=BillEnhancementAttempt.Status.RUNNING,
                run_token=run_token,
            )
            .first()
        )
        if attempt is None:
            return False
        enhancement = BillEnhancement.objects.select_for_update().get(
            pk=attempt.enhancement_id
        )
        attempt.status = attempt_status
        attempt.failure_category = failure_category
        attempt.input_tokens = usage.input_tokens
        attempt.output_tokens = usage.output_tokens
        attempt.total_tokens = usage.total_tokens
        attempt.provider_response_id = provider_response_id
        attempt.resolved_model = resolved_model
        attempt.result_json = result_json
        attempt.completed_at = now
        attempt.lease_expires_at = None
        attempt.save(
            update_fields=[
                "status",
                "failure_category",
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "provider_response_id",
                "resolved_model",
                "result_json",
                "completed_at",
                "lease_expires_at",
                "updated_at",
            ]
        )
        enhancement.status = attempt_status
        enhancement.completed_at = now
        if (
            attempt_status == BillEnhancementAttempt.Status.SUCCEEDED
            and enhancement.successful_attempt_id is None
        ):
            enhancement.successful_attempt = attempt
            enhancement.result_json = result_json
        _refresh_enhancement_usage(enhancement)
        enhancement.save(
            update_fields=[
                "status",
                "completed_at",
                "successful_attempt",
                "result_json",
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "updated_at",
            ]
        )
    return True


def _terminal_task_result(*, persisted, status, category=None):
    if not persisted:
        return {"status": "outcome_unknown", "category": "outcome_unknown"}
    result = {"status": status}
    if category:
        result["category"] = category
    return result


def _invalidate_rejected_credential(attempt):
    """Persist definitive auth/model rejection only for the exact revision used."""
    LLMCredential.objects.filter(
        pk=attempt.credential_id,
        revision=attempt.credential_revision,
        provider=attempt.enhancement.provider,
    ).update(
        validation_status=LLMCredential.ValidationStatus.INVALID,
        validated_revision=attempt.credential_revision,
        validated_provider=attempt.enhancement.provider,
        validated_model=attempt.enhancement.requested_model,
        validated_at=timezone.now(),
    )


def _require_quota_revalidation(attempt):
    """Require an explicit post-remediation validation for the used revision."""
    LLMCredential.objects.filter(
        pk=attempt.credential_id,
        revision=attempt.credential_revision,
        provider=attempt.enhancement.provider,
    ).update(
        validation_status=LLMCredential.ValidationStatus.UNVERIFIED,
        validated_revision=None,
        validated_provider="",
        validated_model="",
        validated_at=None,
    )


def _worker_preflight(attempt):
    if not llm_feature_available():
        return None, None, "feature_disabled"
    credential = attempt.credential
    enhancement = attempt.enhancement
    if (
        credential is None
        or credential.user_id != enhancement.user_id
        or credential.revision != attempt.credential_revision
        or credential.provider != enhancement.provider
    ):
        return None, None, "credential_changed"
    if not credential.enabled:
        return None, None, "credential_disabled"
    if not (
        credential.validation_status == LLMCredential.ValidationStatus.VALID
        and credential.validated_revision == credential.revision
        and credential.validated_provider == credential.provider
        and credential.validated_model == enhancement.requested_model
    ):
        return None, None, "credential_changed"
    try:
        preflight = build_enhancement_preflight(enhancement.bill)
    except PreflightUnavailable as exc:
        return None, None, exc.reason
    identity = (
        preflight.request_fingerprint == enhancement.request_fingerprint
        and preflight.source_fingerprint == enhancement.source_fingerprint
        and preflight.provider == enhancement.provider
        and preflight.requested_model == enhancement.requested_model
        and preflight.reasoning_effort == enhancement.reasoning_effort
        and preflight.prompt_version == enhancement.prompt_version
        and preflight.output_schema_version == enhancement.output_schema_version
        and preflight.source_packet_version == enhancement.source_packet_version
        and preflight.estimated_input_tokens == attempt.estimated_input_tokens
    )
    if not identity:
        return None, None, "source_unavailable"
    try:
        api_key = decrypt_credential(credential)
    except CredentialDecryptionError:
        return None, None, "encryption_error"
    return preflight, api_key, None


@shared_task(autoretry_for=())
def run_bill_enhancement_attempt(attempt_id, dispatch_token):
    """Claim one durable attempt and make no more than one provider call."""
    run_token = _claim_enhancement_attempt(attempt_id, dispatch_token)
    if run_token is None:
        return {"status": "not_claimed"}
    attempt = BillEnhancementAttempt.objects.select_related(
        "enhancement__bill",
        "credential",
    ).get(pk=attempt_id)
    preflight, api_key, failure = _worker_preflight(attempt)
    if failure:
        persisted = _finish_enhancement_attempt(
            attempt_id=attempt_id,
            run_token=run_token,
            attempt_status=BillEnhancementAttempt.Status.FAILED,
            failure_category=failure,
        )
        return _terminal_task_result(
            persisted=persisted,
            status="failed",
            category=failure,
        )

    try:
        provider_result = get_provider(attempt.enhancement.provider).enhance_bill(
            api_key=api_key,
            request=preflight,
            timeout_seconds=settings.LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS,
        )
    except ProviderError as exc:
        if exc.category in {"invalid_credentials", "model_access_denied"}:
            _invalidate_rejected_credential(attempt)
        elif exc.category == "quota_exhausted":
            _require_quota_revalidation(attempt)
        if exc.outcome_unknown:
            terminal_status = BillEnhancementAttempt.Status.OUTCOME_UNKNOWN
        elif exc.category == "content_refusal":
            terminal_status = BillEnhancementAttempt.Status.REFUSED
        else:
            terminal_status = BillEnhancementAttempt.Status.FAILED
        persisted = _finish_enhancement_attempt(
            attempt_id=attempt_id,
            run_token=run_token,
            attempt_status=terminal_status,
            failure_category=exc.category,
            usage=exc.usage,
        )
        return _terminal_task_result(
            persisted=persisted,
            status=terminal_status,
            category=exc.category,
        )

    try:
        validated = validate_enhancement_output(
            provider_result.output,
            attempt.enhancement.source_snapshot_json,
        )
    except ValidationError:
        persisted = _finish_enhancement_attempt(
            attempt_id=attempt_id,
            run_token=run_token,
            attempt_status=BillEnhancementAttempt.Status.FAILED,
            failure_category="invalid_output",
            usage=provider_result.usage,
            provider_response_id=provider_result.response_id,
            resolved_model=provider_result.resolved_model,
        )
        return _terminal_task_result(
            persisted=persisted,
            status="failed",
            category="invalid_output",
        )

    persisted = _finish_enhancement_attempt(
        attempt_id=attempt_id,
        run_token=run_token,
        attempt_status=BillEnhancementAttempt.Status.SUCCEEDED,
        usage=provider_result.usage,
        result_json=validated,
        provider_response_id=provider_result.response_id,
        resolved_model=provider_result.resolved_model,
    )
    return _terminal_task_result(persisted=persisted, status="succeeded")


@shared_task(autoretry_for=())
def recover_stale_bill_enhancement_attempts():
    """Expired provider calls are ambiguous and are never returned to pending."""
    now = timezone.now()
    ids = list(
        BillEnhancementAttempt.objects.filter(
            status=BillEnhancementAttempt.Status.RUNNING,
            lease_expires_at__lte=now,
        ).values_list("id", flat=True)[:100]
    )
    recovered = 0
    for attempt_id in ids:
        with transaction.atomic():
            attempt = (
                BillEnhancementAttempt.objects.select_for_update()
                .filter(
                    pk=attempt_id,
                    status=BillEnhancementAttempt.Status.RUNNING,
                    lease_expires_at__lte=now,
                )
                .first()
            )
            if attempt is None:
                continue
            attempt.status = BillEnhancementAttempt.Status.OUTCOME_UNKNOWN
            attempt.failure_category = "outcome_unknown"
            attempt.completed_at = now
            attempt.lease_expires_at = None
            attempt.save(
                update_fields=[
                    "status",
                    "failure_category",
                    "completed_at",
                    "lease_expires_at",
                    "updated_at",
                ]
            )
            enhancement = BillEnhancement.objects.select_for_update().get(
                pk=attempt.enhancement_id
            )
            enhancement.status = BillEnhancement.Status.OUTCOME_UNKNOWN
            enhancement.completed_at = now
            _refresh_enhancement_usage(enhancement)
            enhancement.save(
                update_fields=[
                    "status",
                    "completed_at",
                    "input_tokens",
                    "output_tokens",
                    "total_tokens",
                    "updated_at",
                ]
            )
            recovered += 1
    return {"recovered": recovered}
