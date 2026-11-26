"""Reuse bill-only analysis; payer credentials and attempt history remain private."""

from apps.legislation.models import BillEnhancement


def _source_first_inputs(saved, document):
    from .source_graph import document_fingerprint
    from .source_packet import PreflightUnavailable
    from .xml_sections import stored_xml_sections

    manifest = saved.source_manifest_json
    if (
        document is None
        or manifest.get("document_id") != document.pk
        or manifest.get("source_kind") != "pinned_passages"
        or manifest.get("document_version_label") != document.version_label
        or manifest.get("document_content_hash", document.reader_text_hash)
        != document.reader_text_hash
    ):
        return None
    from hashlib import sha256

    from django.core.cache import cache

    from .source_graph import NORMALIZATION_VERSION
    from .xml_sections import XML_SECTION_VERSION

    cache_key = None
    aligned = None
    if document.content_hash and document.object_storage_key:
        identity = (
            document.pk,
            document.version_label,
            document.content_hash,
            document.reader_text_hash,
            document.object_storage_key,
            document.content_type,
            NORMALIZATION_VERSION,
            XML_SECTION_VERSION,
        )
        cache_key = (
            "reader-section-identity:" + sha256(repr(identity).encode()).hexdigest()
        )
        aligned = cache.get(cache_key)
    if aligned is None:
        try:
            sections = stored_xml_sections(document, None)
        except PreflightUnavailable:
            return None
        aligned = (
            document_fingerprint(
                str(document.pk),
                document.version_label,
                document.reader_text_hash,
                sections,
            ),
            sections,
        )
        if cache_key:
            cache.set(cache_key, aligned, timeout=21600)
    fingerprint, sections = aligned
    if saved.source_fingerprint != fingerprint:
        return None
    return document, sections


def _source_first_result_valid(saved, inputs):
    from .provision_pipeline import _plan_built_graph, run_analysis
    from .source_graph import build_source_graph

    document, sections = inputs
    text = document.extracted_text or document.raw_text or ""
    graph = build_source_graph(
        str(document.pk), document.version_label, text, xml_sections=sections
    )
    result = saved.result_json
    plan = _plan_built_graph(graph, reuse_result=result)
    if plan.calls or plan.unresolved_unit_ids:
        return False
    synopsis = result["synopsis"]
    from dataclasses import replace

    projected = run_analysis(
        replace(plan, maximum_calls=1),
        lambda call: {k: synopsis[k] for k in ("text", "explanation_ids")},
        lambda *args: None,
    ).output
    # Replanning reused units changes the plan fingerprint. The published result
    # binds to the original confirmed plan, whose fingerprint the worker stored.
    projected["plan_fingerprint"] = result.get("plan_fingerprint")
    return projected == result


def validation_key(saved):
    import hashlib

    from .reader_cache import VALIDATOR_VERSION

    return hashlib.sha256(
        f"bill-validation:projection-13:{saved.source_fingerprint}:{saved.output_schema_version}:{VALIDATOR_VERSION}:{saved.validation_digest}".encode()
    ).hexdigest()


def _reader_result_valid(saved, *, source_first_inputs=None):
    import copy
    from types import SimpleNamespace

    from jsonschema import ValidationError

    from apps.legislation.models import BillProcessingCache

    from .schema import validate_enhancement_output

    if saved.output_schema_version == "2.0-source-first":
        if source_first_inputs is None:
            document = saved.bill.documents.filter(
                pk=saved.source_manifest_json.get("document_id")
            ).first()
            source_first_inputs = _source_first_inputs(saved, document)
            if source_first_inputs is None:
                return False
    fingerprint = validation_key(saved)
    cached = BillProcessingCache.objects.filter(pk=fingerprint).first()
    if cached:
        return cached.result_json["valid"]
    valid = True
    try:
        result = copy.deepcopy(saved.result_json)
        review = result.get("source_review") if isinstance(result, dict) else None
        if isinstance(review, dict) and review.get("policy_drafts") is not None:
            from .policy_compilation import group_policy_drafts

            # Validate the same lossless draft projection that readers receive,
            # not obsolete compiler prose. All other validation still applies.
            review["policy_changes"] = group_policy_drafts(
                SimpleNamespace(source_snapshot=saved.source_snapshot_json),
                review["policy_drafts"],
            )
        if saved.output_schema_version == "2.0-source-first":
            valid = _source_first_result_valid(saved, source_first_inputs)
        else:
            validate_enhancement_output(
                result,
                saved.source_snapshot_json,
                expected_version=saved.output_schema_version,
                aggregate_glossary=True,
            )
    except (ValidationError, KeyError, TypeError, ValueError):
        valid = False
    BillProcessingCache.objects.get_or_create(
        pk=fingerprint,
        defaults={"kind": "reader-validation", "result_json": {"valid": valid}},
    )
    return valid


def _source_identity(bill):
    from apps.legislation.models import BillContract

    documents = bill.documents.only(
        "id",
        "bill_id",
        "version_label",
        "reader_text_hash",
        "object_storage_key",
        "content_type",
        "content_hash",
    ).order_by("-created_at", "-id")
    document = (
        documents.filter(is_active_version=True).first()
        or documents.exclude(extracted_text__isnull=True)
        .exclude(extracted_text="")
        .first()
        or documents.exclude(raw_text__isnull=True).exclude(raw_text="").first()
    )
    contract = bill._state.fields_cache.get("latest_contract")
    if contract is None and bill.latest_contract_id:
        contract = (
            BillContract.objects.only("id", "document_id", "contract_hash")
            .filter(pk=bill.latest_contract_id)
            .first()
        )
    return document, contract


def source_compatible(enhancement, bill, *, identity=None):
    document, contract = identity if identity is not None else _source_identity(bill)
    manifest = enhancement.source_manifest_json
    if not document or manifest.get("document_id") != document.pk:
        return False
    if enhancement.output_schema_version == "2.0-source-first":
        return _source_first_inputs(enhancement, document) is not None
    if manifest.get("document_content_hash") != document.reader_text_hash:
        return False
    if enhancement.output_schema_version == "1.4":
        if (
            manifest.get("source_kind") in {"xml_full_review", "reader_targets"}
            and manifest.get("contract_id") is None
        ):
            if contract is None or contract.document_id != document.pk:
                return True
            if hasattr(contract, "json_version"):
                return (contract.schema_version, contract.json_version) != (
                    "2.1-legal-nlp",
                    "2.1-legal-nlp",
                )
            from .reader_targets import reader_contract

            return reader_contract(document) is None
        return bool(
            contract
            and contract.document_id == document.pk
            and manifest.get("contract_id") == contract.pk
            and manifest.get("contract_hash") == contract.contract_hash
        )
    return enhancement.output_schema_version in {"1.1", "1.2", "1.3"}


def shared_enhancement(bill, *, include_active=True):
    # Prefer an already validated result over another user's newer attempt.
    statuses = [BillEnhancement.Status.SUCCEEDED]
    if include_active:
        statuses += [BillEnhancement.Status.RUNNING, BillEnhancement.Status.PENDING]
    identity = _source_identity(bill)
    for status in statuses:
        rows = (
            BillEnhancement.objects.filter(bill=bill, status=status)
            .defer("result_json", "source_snapshot_json")
            .order_by("-created_at", "-id")
        )
        if status == BillEnhancement.Status.SUCCEEDED:
            rows = rows.exclude(result_json=None).exclude(result_completeness="partial")
        for saved in rows:
            inputs = None
            if saved.output_schema_version == "2.0-source-first":
                inputs = _source_first_inputs(saved, identity[0])
                if inputs is None:
                    continue
            elif not source_compatible(saved, bill, identity=identity):
                continue
            if status == BillEnhancement.Status.SUCCEEDED and not _reader_result_valid(
                saved, source_first_inputs=inputs
            ):
                continue
            return saved
    return None
