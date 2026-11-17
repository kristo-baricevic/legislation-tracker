"""Reuse bill-only analysis; payer credentials and attempt history remain private."""
from apps.legislation.models import BillEnhancement


def _reader_result_valid(saved):
    import hashlib
    from jsonschema import ValidationError
    from apps.legislation.models import BillProcessingCache
    from .source_packet import canonical_json_bytes
    from .reader_cache import VALIDATOR_VERSION
    from .schema import validate_enhancement_output
    fingerprint = hashlib.sha256(canonical_json_bytes({'kind': 'reader-validation',
        'version': VALIDATOR_VERSION, 'result': saved.result_json,
        'sources': saved.source_snapshot_json})).hexdigest()
    cached = BillProcessingCache.objects.filter(pk=fingerprint).first()
    if cached:
        return cached.result_json['valid']
    valid = True
    try:
        validate_enhancement_output(saved.result_json, saved.source_snapshot_json, expected_version='1.4')
    except (ValidationError, KeyError, TypeError, ValueError):
        valid = False
    BillProcessingCache.objects.get_or_create(pk=fingerprint,
        defaults={'kind': 'reader-validation', 'result_json': {'valid': valid}})
    return valid


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
                if status == BillEnhancement.Status.SUCCEEDED and saved.output_schema_version == '1.4' and not _reader_result_valid(saved):
                    continue
                return saved
    return None
