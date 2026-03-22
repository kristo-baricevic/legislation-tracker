"""
Celery tasks: BillContract generation (Phase 5), topic/similarity hooks (Phase 6 stubs).
"""
import json
import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.changelog.models import ChangeLog
from apps.legislation.contract_json import contract_hash_from_dict
from apps.legislation.models import Bill, BillContract, BillDocument, EvidenceSpan

logger = logging.getLogger(__name__)

STUB_SCHEMA_VERSION = "1.0-stub"


def _build_stub_contract_json(document: BillDocument, bill: Bill) -> dict:
    """Minimal structured interpretation until NLP (Phase 5.3)."""
    text = (document.extracted_text or "").strip()
    if not text:
        text = (bill.summary or bill.title or "").strip()
    excerpt = text[:2000] if text else ""
    return {
        "schema_version": STUB_SCHEMA_VERSION,
        "title": bill.title,
        "plain_summary": excerpt[:1200] if excerpt else bill.title,
        "source_excerpt": excerpt[:500],
        "version_label": document.version_label,
    }


@shared_task
def generate_contract(document_id):
    """
    Build or skip BillContract from BillDocument.extracted_text (stub rules).
    Sets Bill.latest_contract, ChangeLog(contract_update), EvidenceSpan rows;
    enqueues Phase 6 stubs: update_topics, schedule_similarity_for_bill.
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
    contract_json = _build_stub_contract_json(document, bill)
    new_hash = contract_hash_from_dict(contract_json)

    latest = (
        BillContract.objects.filter(document=document)
        .order_by("-id")
        .first()
    )
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

    update_topics.apply_async(args=[contract.id])
    schedule_similarity_for_bill.apply_async(args=[bill.id])

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
def update_topics(contract_id):
    """
    Phase 6: infer Topic tags from BillContract and update BillTopic.
    Stub: log only.
    """
    logger.info("update_topics: stub contract_id=%s (Phase 6)", contract_id)
    return {"contract_id": contract_id, "stub": True}


@shared_task
def schedule_similarity_for_bill(bill_id):
    """
    Phase 6: queue bill for BillSimilarity recomputation.
    Stub: log only.
    """
    logger.info(
        "schedule_similarity_for_bill: stub bill_id=%s (Phase 6)",
        bill_id,
    )
    return {"bill_id": bill_id, "stub": True}
