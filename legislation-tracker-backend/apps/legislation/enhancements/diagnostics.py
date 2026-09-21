"""Allowlisted failure metadata. Never persist exception text or model output."""

from jsonschema import ValidationError

MESSAGES = {
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
