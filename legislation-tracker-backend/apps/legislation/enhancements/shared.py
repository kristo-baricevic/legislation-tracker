"""Reuse bill-only analysis; payer credentials and attempt history remain private."""
from apps.legislation.models import BillEnhancement


def _reader_result_valid(saved):
    import copy
    import hashlib
    from types import SimpleNamespace
    from jsonschema import ValidationError
    from apps.legislation.models import BillProcessingCache
    from .reader_cache import VALIDATOR_VERSION
    from .schema import validate_enhancement_output
    fingerprint = hashlib.sha256(f"reader-validation:projection-1:{VALIDATOR_VERSION}:{saved.validation_digest}".encode()).hexdigest()
    cached = BillProcessingCache.objects.filter(pk=fingerprint).first()
    if cached:
        return cached.result_json['valid']
    valid = True
    try:
        result = copy.deepcopy(saved.result_json)
        review = result.get('source_review') if isinstance(result, dict) else None
        if isinstance(review, dict) and review.get('policy_drafts') is not None:
            from .policy_compilation import group_policy_drafts
            # Validate the same lossless draft projection that readers receive,
            # not obsolete compiler prose. All other validation still applies.
            review['policy_changes'] = group_policy_drafts(
                SimpleNamespace(source_snapshot=saved.source_snapshot_json), review['policy_drafts'])
        validate_enhancement_output(result, saved.source_snapshot_json, expected_version='1.4')
    except (ValidationError, KeyError, TypeError, ValueError):
        valid = False
    BillProcessingCache.objects.get_or_create(pk=fingerprint,
        defaults={'kind': 'reader-validation', 'result_json': {'valid': valid}})
    return valid


def _source_identity(bill):
    from apps.legislation.models import BillContract
    documents = bill.documents.only("id", "bill_id", "reader_text_hash").order_by("-created_at", "-id")
    document = (documents.filter(is_active_version=True).first()
        or documents.exclude(extracted_text__isnull=True).exclude(extracted_text="").first()
        or documents.exclude(raw_text__isnull=True).exclude(raw_text="").first())
    contract = bill._state.fields_cache.get("latest_contract")
    if contract is None and bill.latest_contract_id:
        contract = BillContract.objects.only("id", "document_id", "contract_hash").filter(pk=bill.latest_contract_id).first()
    return document, contract


def source_compatible(enhancement, bill, *, identity=None):
    document, contract = identity if identity is not None else _source_identity(bill)
    manifest = enhancement.source_manifest_json
    if not document or manifest.get("document_id") != document.pk:
        return False
    if manifest.get("document_content_hash") != document.reader_text_hash:
        return False
    if enhancement.output_schema_version == "1.4":
        if manifest.get("source_kind") == "xml_full_review" and manifest.get("contract_id") is None:
            return not contract or contract.document_id != document.pk
        return bool(contract and contract.document_id == document.pk
                    and manifest.get("contract_id") == contract.pk
                    and manifest.get("contract_hash") == contract.contract_hash)
    return enhancement.output_schema_version in {"1.1", "1.2", "1.3"}


def shared_enhancement(bill, *, include_active=True):
    # Prefer an already validated result over another user's newer attempt.
    statuses = [BillEnhancement.Status.SUCCEEDED]
    if include_active:
        statuses += [BillEnhancement.Status.RUNNING, BillEnhancement.Status.PENDING]
    identity = _source_identity(bill)
    for status in statuses:
        rows = BillEnhancement.objects.filter(bill=bill, status=status).defer("result_json", "source_snapshot_json").order_by("-created_at", "-id")
        if status == BillEnhancement.Status.SUCCEEDED:
            rows = rows.exclude(result_json=None).exclude(result_completeness="partial")
        for saved in rows:
            if source_compatible(saved, bill, identity=identity):
                if status == BillEnhancement.Status.SUCCEEDED and saved.output_schema_version == '1.4' and not _reader_result_valid(saved):
                    continue
                return saved
    return None
