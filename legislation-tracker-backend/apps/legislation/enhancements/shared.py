"""Reuse bill-only analysis; payer credentials and attempt history remain private."""
from apps.legislation.models import BillEnhancement


def source_compatible(enhancement, bill):
    from .source_packet import _marked_active_document, _stored_document, _text_hash
    document = _marked_active_document(bill) or _stored_document(bill)
    manifest = enhancement.source_manifest_json
    if not document or manifest.get("document_id") != document.pk:
        return False
    if manifest.get("document_content_hash") != _text_hash(document.extracted_text or document.raw_text or ""):
        return False
    if enhancement.output_schema_version == "1.4":
        contract = bill.latest_contract
        return bool(contract and contract.document_id == document.pk
                    and manifest.get("contract_id") == contract.pk
                    and manifest.get("contract_hash") == contract.contract_hash)
    return enhancement.output_schema_version in {"1.1", "1.2", "1.3"}


def shared_enhancement(bill, *, include_active=True):
    # Prefer an already validated result over another user's newer attempt.
    statuses = [BillEnhancement.Status.SUCCEEDED]
    if include_active:
        statuses += [BillEnhancement.Status.RUNNING, BillEnhancement.Status.PENDING]
    for status in statuses:
        rows = BillEnhancement.objects.filter(bill=bill, status=status).order_by("-created_at", "-id")
        if status == BillEnhancement.Status.SUCCEEDED:
            rows = rows.exclude(result_json=None).exclude(result_completeness="partial")
        for saved in rows:
            if source_compatible(saved, bill):
                return saved
    return None
