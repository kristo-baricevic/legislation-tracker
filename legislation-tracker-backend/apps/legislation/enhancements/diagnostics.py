"""Allowlisted failure metadata. Never persist exception text or model output."""

from jsonschema import ValidationError

MESSAGES = {
    "reader_target_invalid": "An explanation does not match its assigned bill provision.",
    "reader_coverage_incomplete": "The AI did not return an outcome for every requested provision.",
    "glossary_coverage_incomplete": "The AI did not explain every requested definition. No partial glossary was published.",
    "glossary_batch_unexpected_content": "The glossary response contained unrelated bill analysis.",
    "glossary_definition_duplicate": "The AI explained the same definition more than once.",
    "glossary_definition_unsupported": "A glossary explanation does not cite its assigned definition.",
    "schema_version_mismatch": "The AI returned a different output schema version than requested.",
    "citation_quote_not_found": "A cited quote does not exactly match its source text.",
    "citation_quote_ambiguous": "A cited quotation occurs more than once in its source; a more specific passage is needed.",
    "citation_reference_unknown": "The AI cited a source that was not supplied.",
    "citation_reference_mismatch": "The quoted passages do not cover exactly the cited sources.",
    "source_snapshot_invalid": "The saved source snapshot failed its integrity check.",
    "provider_output_limit": "The AI response was cut off by the output token limit.",
    "provider_incomplete": "The provider did not complete the response.",
    "provider_invalid_json": "The provider response was not valid JSON.",
    "provider_output_not_object": "The provider returned JSON with the wrong top-level type.",
    "schema_type": "An output field has the wrong type.",
    "schema_required": "A required output field is missing.",
    "schema_additionalProperties": "The output contains an unsupported field.",
    "schema_maxLength": "An output field exceeds its allowed length.",
    "schema_minLength": "An output field is empty or too short.",
    "schema_maxItems": "An output list contains too many items.",
    "schema_minItems": "An output list is missing required items.",
    "schema_uniqueItems": "An output list contains duplicate items.",
    "schema_enum": "An output field has an unsupported value.",
    "schema_const": "An output field does not match its required value.",
    "schema_pattern": "An output field has an invalid format.",
    "output_validation_failed": "The AI output failed validation; no more specific safe diagnostic is available.",
}
PATH_FIELDS = frozenset(
    {
        "schema_version",
        "summary",
        "explanations",
        "target_id",
        "glossary",
        "definition_id",
        "overview",
        "key_impacts",
        "obligations",
        "funding_and_timing",
        "uncertain_language",
        "text",
        "actor",
        "modality",
        "action",
        "conditions",
        "kind",
        "why_it_matters",
        "source_refs",
        "source_quotes",
        "source_ref",
        "quote",
    }
)
JSON_REASONS = {
    "Expecting ',' delimiter": "missing_comma",
    "Expecting ':' delimiter": "missing_colon",
    "Expecting property name enclosed in double quotes": "invalid_property_name",
    "Expecting value": "missing_value",
    "Extra data": "extra_data",
    "Unterminated string starting at": "unterminated_string",
    "Invalid \\escape": "invalid_escape",
    "Invalid control character at": "invalid_control_character",
    "Invalid \\uXXXX escape": "invalid_unicode_escape",
}


def json_parse_diagnostic(error, text):
    """Keep parser coordinates and a fixed reason, never error.doc or raw text."""
    import json
    detail = {"text_length": len(text) if isinstance(text, str) else 0}
    if not isinstance(text, str):
        detail["reason"] = "wrong_text_type"
    elif not text.strip():
        detail["reason"] = "empty_text"
    else:
        detail["reason"] = JSON_REASONS.get(getattr(error, "msg", ""), "invalid_syntax")
    if isinstance(error, json.JSONDecodeError):
        detail.update(position=error.pos, line=error.lineno, column=error.colno)
    return detail


def diagnostic(code, path=()):
    code = code if code in MESSAGES else "output_validation_failed"
    safe_path = []
    for part in path:
        if isinstance(part, int) and 0 <= part <= 10000:
            safe_path.append(str(part))
        elif isinstance(part, str) and part in PATH_FIELDS:
            safe_path.append(part)
        else:
            break
    return {"code": code, "message": MESSAGES[code], "path": "/" + "/".join(safe_path)}


def output_error(code, path=()):
    return ValidationError(MESSAGES[code], validator=code, path=path)


def validation_diagnostic(error):
    code = error.validator
    if code not in MESSAGES:
        code = "schema_" + str(code)
    return diagnostic(code, error.absolute_path)


def provider_validation_diagnostic(error):
    """Persist only allowlisted location metadata, never arbitrary provider text."""
    detail = error.validation_detail
    if not isinstance(detail, dict):
        return diagnostic(error.validation_code)
    path = detail.get("path", "")
    parts = path.strip("/").split("/") if isinstance(path, str) else []
    result = diagnostic(error.validation_code, [int(p) if p.isdecimal() and len(p) <= 5 else p for p in parts])
    if detail.get("stage") in {"main_analysis", "glossary_batch", "reader_batch"}:
        result["stage"] = detail["stage"]
    index = detail.get("batch_index")
    if type(index) is int and 0 <= index <= 10000:
        result["batch_index"] = index
    parser = detail.get("parser")
    if isinstance(parser, dict):
        safe = {}
        if parser.get("reason") in {*JSON_REASONS.values(), "wrong_text_type", "empty_text", "invalid_syntax"}:
            safe["reason"] = parser["reason"]
        for field in ("text_length", "position", "line", "column", "output_text_parts", "output_text_part_length"):
            value = parser.get(field)
            if type(value) is int and 0 <= value <= 100_000_000:
                safe[field] = value
        if safe:
            result["parser"] = safe
    return result
