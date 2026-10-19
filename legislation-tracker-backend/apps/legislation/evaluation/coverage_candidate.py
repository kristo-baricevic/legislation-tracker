"""Evaluation-only candidate. No answer keys or database access."""

import copy
import hashlib
from dataclasses import asdict, replace

from django.conf import settings
from jsonschema import Draft202012Validator, ValidationError

from apps.legislation.enhancements.citations import resolve_citations
from apps.legislation.enhancements.coverage_contract import response_schema
from apps.legislation.enhancements.diagnostics import diagnostic, validation_diagnostic
from apps.legislation.enhancements.providers.base import ProviderError
from apps.legislation.enhancements.schema import (
    OUTPUT_SCHEMA,
    validate_enhancement_output,
)
from apps.legislation.enhancements.source_packet import (
    PreflightUnavailable,
    canonical_json_bytes,
    select_document_sources,
)
from apps.legislation.enhancements.types import EnhancementPreflight

from .coverage_inventory import assess_inventory, build_inventory

INSTRUCTIONS = """
The coverage_checklist is a source-derived list of candidate provisions, not an
answer key or a guarantee of exhaustive detection. Review each listed range in
the supplied sources. Explain every distinct fee, fine, surcharge, exemption,
fee substitution, authorization and restricted account, with amount and purpose.
Preserve cost-based ceilings, mandatory/optional language and exceptions.
For conditions, read the WHOLE governing rule and its children. Explain all
required conjuncts and alternatives, including nonfinancial prerequisites.
Do not rely on a quote to communicate a condition missing from explanatory prose.
If something cannot be explained safely, identify that specific provision and
limitation in uncertain_language; never silently omit it. Use the normal output
schema plus coverage_response. Respond to EVERY checklist ID exactly once.
For explained entries, output_paths must point to the actual explanations, e.g.
funding_and_timing/0, and reason must be empty. Those explanations must cite the
specific provision, not merely another sentence in the same source chunk.
For unresolved entries, output_paths must be empty and reason must explain the
specific limitation. Never label an incomplete explanation as explained.
Do not claim completeness or semantic verification from this checklist.
"""


def _bytes(envelope):
    data = canonical_json_bytes(envelope)
    if len(data) > min(
        settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES,
        settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS,
    ):
        raise PreflightUnavailable(
            "Coverage request exceeds budget", reason="request_too_large"
        )
    return data


def prepare(bill, text, version):
    sources, envelope, _ = select_document_sources(bill, text, version)
    if envelope["source_packet"]["truncated"]:
        raise PreflightUnavailable("Coverage evaluation requires the full document")
    inventory = build_inventory(sources, document_text=text)
    envelope["instructions"] += INSTRUCTIONS
    envelope["coverage_candidate_version"] = "2"
    envelope["source_packet"]["coverage_checklist"] = [
        {
            **{k: row[k] for k in ("id", "source_refs", "kinds", "amounts")},
            "starts_with": " ".join(row["source_text"].split())[:120],
            "ends_with": " ".join(row["source_text"].split())[-60:],
        }
        for row in inventory
    ]
    envelope["output_schema"] = response_schema(inventory)
    data = _bytes(envelope)
    request = EnhancementPreflight(
        provider=envelope["provider"],
        requested_model=envelope["requested_model"],
        reasoning_effort=envelope["reasoning_effort"],
        prompt_version=envelope["prompt_version"],
        output_schema_version=envelope["output_schema_version"],
        source_packet_version=envelope["source_packet_version"],
        source_fingerprint=hashlib.sha256(canonical_json_bytes(sources)).hexdigest(),
        request_fingerprint=hashlib.sha256(data).hexdigest(),
        source_manifest={
            "document_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "coverage": envelope["source_packet"]["coverage"],
        },
        source_snapshot=sources,
        request_envelope=envelope,
        request_bytes=data,
        estimated_input_tokens=len(data),
        truncated=False,
    )
    return request, inventory


def _correction(request, coverage, citation_error, output, coverage_error=None):
    envelope = copy.deepcopy(request.request_envelope)
    envelope["instructions"] += (
        "\nThis is the single correction pass. Return a complete revised analysis, preserving already covered provisions. Focus on the supplied coverage findings and recheck all conditions. Do not just return missing items."
    )
    envelope["source_packet"]["coverage_findings"] = {
        "rows": [
            {k: v for k, v in row.items() if k in {"id", "status", "missing_amounts"}}
            for row in coverage
        ],
        "citation_error": citation_error,
        "coverage_error": coverage_error,
    }
    # Retain prior prose to avoid fixing omissions by losing earlier coverage.
    # Quotes are already in the source packet; do not duplicate their token cost.
    envelope["source_packet"]["previous_explanations"] = (
        {
            category: [
                {k: v for k, v in item.items() if k != "source_quotes"}
                for item in items
                if isinstance(item, dict)
            ]
            for category, items in output.items()
            if isinstance(items, list)
        }
        if isinstance(output, dict)
        else {}
    )
    try:
        data = _bytes(envelope)
    except PreflightUnavailable:
        # The previous draft is optional context, never a reason to omit source.
        del envelope["source_packet"]["previous_explanations"]
        envelope["source_packet"]["previous_explanations_omitted"] = True
        data = _bytes(envelope)
    return replace(
        request,
        request_envelope=envelope,
        request_bytes=data,
        request_fingerprint=hashlib.sha256(data).hexdigest(),
        estimated_input_tokens=len(data),
    )


def run(request, inventory, generate):
    """At most two calls; no paid citation repair, no automatic retries.

    The correction regenerates the complete result, not a blind append/merge.
    Reassess everything afterward because a correction can introduce regressions.
    """
    report = {
        "provider_calls": 0,
        "release_gate": "blocked",
        "attempts": [],
        "inventory": inventory,
        "coverage": [],
        "initial_coverage": [],
    }
    original = request
    for index in range(2):
        attempt = {
            "request_fingerprint": request.request_fingerprint,
            "request_bytes": len(request.request_bytes),
        }
        report["attempts"].append(attempt)
        report["provider_calls"] += 1
        try:
            result = generate(request)
            attempt.update(
                raw_output=result.output,
                usage=asdict(result.usage),
                response_id=result.response_id,
                resolved_model=result.resolved_model,
            )
        except ProviderError as exc:
            attempt.update(
                failure_category=exc.category,
                validation_code=exc.validation_code,
                usage=asdict(exc.usage),
            )
            report["release_gate"] = "fail"
            break
        citation_error = None
        raw = result.output
        schema = response_schema(inventory)
        ledger_schema = dict(
            schema["properties"]["coverage_response"], **{"$defs": schema["$defs"]}
        )
        ledger = raw.get("coverage_response") if isinstance(raw, dict) else None
        coverage_error = None
        if not Draft202012Validator(ledger_schema).is_valid(ledger):
            coverage_error = "coverage_response_invalid"
            ledger = {}
        else:
            for entry in ledger.values():
                if (
                    (
                        entry["status"] == "explained"
                        and (not entry["output_paths"] or entry["reason"])
                    )
                    or (
                        entry["status"] == "unresolved"
                        and (entry["output_paths"] or not entry["reason"].strip())
                    )
                    or len(entry["output_paths"]) != len(set(entry["output_paths"]))
                ):
                    coverage_error = "coverage_response_invalid"
        output = (
            {k: v for k, v in raw.items() if k != "coverage_response"}
            if isinstance(raw, dict)
            else raw
        )
        result = replace(result, output=output)
        try:
            result = resolve_citations(result, original.source_snapshot, repair=None)
            output = validate_enhancement_output(
                result.output,
                original.source_snapshot,
                expected_version=original.output_schema_version,
            )
        except (ProviderError, ValidationError) as exc:
            detail = (
                validation_diagnostic(exc)
                if isinstance(exc, ValidationError)
                else diagnostic(exc.validation_code)
            )
            attempt["validation_detail"] = detail
            citation_error = detail["code"]
        if citation_error:
            attempt["validation_error"] = citation_error
        if not Draft202012Validator(OUTPUT_SCHEMA).is_valid(output):
            # Malformed output must not enter the coverage assessor.
            coverage = []
            attempt["validation_error"] = citation_error or "invalid_output"
        else:
            coverage = assess_inventory(
                inventory,
                output,
                original.source_snapshot,
                mapping={key: entry["output_paths"] for key, entry in ledger.items()}
                if not coverage_error
                else None,
            )
            ledger_valid = not coverage_error
            for row in coverage:
                entry = ledger.get(row["id"])
                if entry and entry["status"] == "unresolved" and ledger_valid:
                    row.update(status="unresolved", reason=entry["reason"])
                elif (
                    ledger_valid
                    and entry
                    and set(entry["output_paths"]) != set(row["output_paths"])
                ):
                    coverage_error = "coverage_mapping_unsupported"
        if coverage_error:
            attempt["coverage_error"] = coverage_error
        attempt["coverage_response"] = ledger
        attempt["coverage"] = coverage
        attempt["output"] = output
        report["coverage"] = coverage
        report["output"] = output
        if index == 0:
            report["initial_coverage"] = coverage
        missing = [
            r
            for r in coverage
            if r["status"].startswith("missing_") or r["meaning_errors"]
        ]
        if citation_error or missing or coverage_error:
            report["release_gate"] = "fail"
        else:
            report["release_gate"] = "blocked"  # No automated semantic approval.
        condition_review = any("conditions" in row["kinds"] for row in inventory)
        unresolved = any(row["status"] == "unresolved" for row in coverage)
        if index == 0 and (
            citation_error
            or missing
            or coverage_error
            or condition_review
            or unresolved
        ):
            try:
                request = _correction(
                    original, coverage, citation_error, output, coverage_error
                )
            except PreflightUnavailable:
                report["correction_not_run"] = "request_too_large"
                break
        else:
            break
    report["usage"] = {}
    for field in ("input_tokens", "output_tokens", "total_tokens"):
        values = [a["usage"].get(field) for a in report["attempts"]]
        report["usage"][field] = None if any(v is None for v in values) else sum(values)
    return report
