"""Reuse bill-only analysis; payer credentials and attempt history remain private."""
from apps.legislation.models import BillEnhancement


def _source_first_result_valid(saved):
    from .provision_pipeline import _plan_built_graph, run_analysis
    from .source_graph import build_source_graph
    from .xml_sections import stored_xml_sections

    document = saved.bill.documents.filter(pk=saved.source_manifest_json["document_id"]).first()
    if document is None:
        return False
    text = document.extracted_text or document.raw_text or ""
    graph = build_source_graph(str(document.pk), document.version_label, text,
                               xml_sections=stored_xml_sections(document, text))
    if graph.document_fingerprint != saved.source_fingerprint:
        return False
    result = saved.result_json
    plan = _plan_built_graph(graph, reuse_result=result)
    if plan.calls or plan.unresolved_unit_ids:
        return False
    synopsis = result["synopsis"]
    from dataclasses import replace
    projected = run_analysis(replace(plan, maximum_calls=1), lambda call: {k: synopsis[k] for k in ("text", "explanation_ids")},
                             lambda *args: None).output
    # Replanning reused units changes the plan fingerprint. The published result
    # binds to the original confirmed plan, whose fingerprint the worker stored.
    projected["plan_fingerprint"] = result.get("plan_fingerprint")
    return projected == result


def _reader_result_valid(saved):
    import copy
    import hashlib
    from types import SimpleNamespace
    from jsonschema import ValidationError
    from apps.legislation.models import BillProcessingCache
    from .reader_cache import VALIDATOR_VERSION
    from .schema import validate_enhancement_output
    fingerprint = hashlib.sha256(f"bill-validation:projection-7:{saved.output_schema_version}:{VALIDATOR_VERSION}:{saved.validation_digest}".encode()).hexdigest()
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
        if saved.output_schema_version == "2.0-source-first":
            valid = _source_first_result_valid(saved)
        else:
            validate_enhancement_output(result, saved.source_snapshot_json, expected_version=saved.output_schema_version,
                                        aggregate_glossary=True)
    except (ValidationError, KeyError, TypeError, ValueError):
        valid = False
    BillProcessingCache.objects.get_or_create(pk=fingerprint,
        defaults={'kind': 'reader-validation', 'result_json': {'valid': valid}})
    return valid


def _source_identity(bill):
    from apps.legislation.models import BillContract
    documents = bill.documents.only("id", "bill_id", "version_label", "reader_text_hash").order_by("-created_at", "-id")
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
    if enhancement.output_schema_version == "2.0-source-first":
        from .source_graph import NORMALIZATION_VERSION, _hash
        identity = f"{document.pk}\0{document.version_label}\0{NORMALIZATION_VERSION}\0{document.reader_text_hash}"
        if manifest.get("source_kind") != "pinned_passages" or manifest.get("document_version_label") != document.version_label:
            return False
        if "document_content_hash" in manifest:
            return manifest["document_content_hash"] == document.reader_text_hash
        # Older XML graphs incorporate section identities into their fingerprint.
        if enhancement.source_fingerprint == _hash(identity):
            return True
        from .source_graph import build_source_graph
        from .source_packet import PreflightUnavailable
        from .xml_sections import stored_xml_sections
        text = document.extracted_text or document.raw_text or ""
        try:
            sections = stored_xml_sections(document, text)
        except PreflightUnavailable:
            return False
        return bool(sections and enhancement.source_fingerprint == build_source_graph(
            str(document.pk), document.version_label, text, xml_sections=sections).document_fingerprint)
    if manifest.get("document_content_hash") != document.reader_text_hash:
        return False
    if enhancement.output_schema_version == "1.4":
        if manifest.get("source_kind") in {"xml_full_review", "reader_targets"} and manifest.get("contract_id") is None:
            from .reader_targets import reader_contract
            return reader_contract(document) is None
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
                if status == BillEnhancement.Status.SUCCEEDED and not _reader_result_valid(saved):
                    continue
                return saved
    return None
