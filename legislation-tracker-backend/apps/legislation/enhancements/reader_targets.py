"""Immutable, source-bound explanations for the existing reader inventory."""
import copy
import hashlib
import re

from jsonschema import Draft202012Validator

from .citations import citation_spans
from .diagnostics import output_error

READER_VERSION = "1.4"
QUOTES = {
    "type": "array", "maxItems": 12,
    "items": {"type": "object", "additionalProperties": False,
              "required": ["source_ref", "quote"], "properties": {
                  "source_ref": {"type": "string", "pattern": r"^src_[0-9]{4}$"},
                  "quote": {"type": "string", "minLength": 1, "maxLength": 800}}},
}
READER_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["schema_version", "summary", "explanations"],
    "properties": {
        "schema_version": {"type": "string", "const": READER_VERSION},
        "summary": {"type": "array", "maxItems": 4, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["text", "source_quotes"], "properties": {
                "text": {"type": "string", "minLength": 1, "maxLength": 600},
                "source_quotes": QUOTES}}},
        "explanations": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["target_id", "status", "text", "unresolved_reason", "source_quotes"],
            "properties": {
                "target_id": {"type": "string", "minLength": 1, "maxLength": 220},
                "status": {"type": "string", "enum": ["explained", "unresolved"]},
                "text": {"type": ["string", "null"], "minLength": 1, "maxLength": 900},
                "unresolved_reason": {"type": ["string", "null"], "minLength": 1, "maxLength": 400},
                "source_quotes": QUOTES}}},
    },
}


def reader_contract(document):
    contract = document.bill.latest_contract
    return contract if (
        contract and contract.document_id == document.pk
        and contract.schema_version == "2.1-legal-nlp"
        and contract.contract_json.get("schema_version") == "2.1-legal-nlp"
    ) else None


def build_reader_targets(document):
    from ..extraction.federal_structure import parse_federal_structure
    from ..extraction.types import ExpectedExtractionRejection

    contract = reader_contract(document)
    if not contract:
        return []
    text = document.extracted_text or document.raw_text or ""
    payload = contract.contract_json
    spans = {}
    for span in contract.evidence_spans.all():
        spans.setdefault(span.field_path, []).append(span)
    try:
        sections = [s for s in parse_federal_structure(text) if s.level == "section"]
    except ExpectedExtractionRejection:
        sections = []
    targets = []
    for category, kind in (("line_items", "line_item"), ("financial_items", "financial_item"), ("definitions", "definition")):
        for item in payload.get(category, []):
            evidence = [span for path in item.get("evidence_paths", [])
                        for span in spans.get(path, [])]
            valid = evidence and all(
                0 <= s.start_char < s.end_char <= len(text)
                and text[s.start_char:s.end_char] == s.quoted_text for s in evidence
            )
            ranges = sorted({(s.start_char, s.end_char) for s in evidence}) if valid else []
            context = next((s.span for s in sections if ranges
                            and s.span.start_char <= ranges[0][0]
                            and max(end for _, end in ranges) <= s.span.end_char), None)
            reason = None if context else "source_context_unavailable"
            if kind == "definition" and re.search(r"\bmeaning\s+(given|assigned|provided)\b", item.get("definition", ""), re.I):
                reason = "external_definition"
            targets.append({
                "target_id": f"{kind}:{item['id']}", "kind": kind, "item_id": item["id"],
                "contract_id": contract.pk, "contract_hash": contract.contract_hash,
                "document_id": document.pk, "document_content_hash": hashlib.sha256(text.encode()).hexdigest(),
                "original_text": item.get("display_text") or item.get("definition") or "",
                "evidence_ranges": [list(r) for r in ranges],
                "facts": {
                    "item": copy.deepcopy(item),
                    "timeline_items": [copy.deepcopy(t) for t in payload.get("timeline_items", []) if t["id"] in item.get("timeline_refs", [])],
                    "financial_items": [copy.deepcopy(f) for f in payload.get("financial_items", []) if f["id"] in item.get("exact_financial_refs", [])],
                },
                "context_text": text[context.start_char:context.end_char] if context else "",
                "start_char": context.start_char if context else None,
                "end_char": context.end_char if context else None,
                "unavailable_reason": reason,
            })
    return targets


def snapshot_targets(sources):
    return [target for source in sources for target in source.get("reader_targets", [])]


def validate_reader_explanations(output, targets, sources):
    from .schema import _validate_snapshot
    Draft202012Validator(READER_SCHEMA).validate(output)
    _validate_snapshot(sources)
    by_id = {t["target_id"]: t for t in targets}
    if len(by_id) != len(targets):
        raise output_error("reader_target_invalid", ["explanations"])
    seen = set()
    source_map = {s["source_ref"]: s for s in sources}
    for index, item in enumerate(output["explanations"]):
        tid = item["target_id"]
        if tid not in by_id or tid in seen:
            raise output_error("reader_target_invalid", ["explanations", index, "target_id"])
        seen.add(tid)
        if item["status"] == "unresolved":
            if item["text"] is not None or not item["unresolved_reason"] or item["source_quotes"]:
                raise output_error("reader_target_invalid", ["explanations", index])
            continue
        if not item["text"] or item["unresolved_reason"] is not None:
            raise output_error("reader_target_invalid", ["explanations", index])
        _validate_quotes(item, source_map, ["explanations", index], by_id[tid])
    if seen != set(by_id):
        raise output_error("reader_coverage_incomplete", ["explanations"])
    for index, item in enumerate(output["summary"]):
        _validate_quotes(item, source_map, ["summary", index])
    return copy.deepcopy(output)


def _validate_quotes(item, sources, path, target=None):
    if not item["source_quotes"]:
        raise output_error("citation_quote_not_found", path + ["source_quotes"])
    own_evidence = target is None
    for index, quote in enumerate(item["source_quotes"]):
        source = sources.get(quote["source_ref"])
        if source is None or (target and not any(
            t == target for t in source.get("reader_targets", [])
        )):
            raise output_error("reader_target_invalid", path + ["source_quotes", index])
        matches = citation_spans(source["quoted_text"], quote["quote"])
        if len(matches) != 1:
            raise output_error("citation_quote_ambiguous" if matches else "citation_quote_not_found",
                               path + ["source_quotes", index, "quote"])
        if target:
            start, end = matches[0]
            start += source["start_char"]
            end += source["start_char"]
            own_evidence |= any(start < right and end > left for left, right in target["evidence_ranges"])
    if not own_evidence:
        raise output_error("reader_target_invalid", path + ["source_quotes"])
