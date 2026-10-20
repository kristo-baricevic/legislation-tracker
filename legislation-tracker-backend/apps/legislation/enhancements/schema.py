from __future__ import annotations

import copy
import hashlib
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

from .diagnostics import output_error
from .citations import citation_spans

OUTPUT_SCHEMA_VERSION = "1.3"

SOURCE_REFS_SCHEMA = {
    "type": "array",
    "items": {"type": "string", "pattern": r"^src_[0-9]{4}$"},
    "minItems": 1,
    "maxItems": 8,
    "uniqueItems": True,
}

ATOMIC_CLAIM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["text", "source_refs"],
    "properties": {
        "text": {"type": "string", "minLength": 1, "maxLength": 600},
        "source_refs": SOURCE_REFS_SCHEMA,
    },
}

OUTPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "overview",
        "key_impacts",
        "obligations",
        "funding_and_timing",
        "uncertain_language",
    ],
    "properties": {
        "schema_version": {"type": "string", "const": OUTPUT_SCHEMA_VERSION},
        "overview": {
            "type": "array",
            "items": ATOMIC_CLAIM_SCHEMA,
            "maxItems": 6,
        },
        "key_impacts": {
            "type": "array",
            "items": ATOMIC_CLAIM_SCHEMA,
            "maxItems": 12,
        },
        "obligations": {
            "type": "array",
            "maxItems": 20,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "actor",
                    "modality",
                    "action",
                    "conditions",
                    "source_refs",
                ],
                "properties": {
                    "actor": {"type": "string", "minLength": 1, "maxLength": 200},
                    "modality": {
                        "type": "string",
                        "enum": ["required", "prohibited", "permitted"],
                    },
                    "action": {"type": "string", "minLength": 1, "maxLength": 600},
                    "conditions": {
                        "type": ["string", "null"],
                        "maxLength": 400,
                    },
                    "source_refs": SOURCE_REFS_SCHEMA,
                },
            },
        },
        "funding_and_timing": {
            "type": "array",
            "maxItems": 16,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "text", "source_refs"],
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["funding", "timing"],
                    },
                    "text": {"type": "string", "minLength": 1, "maxLength": 600},
                    "source_refs": SOURCE_REFS_SCHEMA,
                },
            },
        },
        "uncertain_language": {
            "type": "array",
            "maxItems": 10,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "why_it_matters", "source_refs"],
                "properties": {
                    "text": {"type": "string", "minLength": 1, "maxLength": 600},
                    "why_it_matters": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 600,
                    },
                    "source_refs": SOURCE_REFS_SCHEMA,
                },
            },
        },
    },
}


# Keep historical immutable 1.1 results readable and old in-flight jobs valid.
LEGACY_OUTPUT_SCHEMA = copy.deepcopy(OUTPUT_SCHEMA)
LEGACY_OUTPUT_SCHEMA["properties"]["schema_version"]["const"] = "1.1"
SOURCE_QUOTES_SCHEMA = {
    "type": "array",
    "minItems": 1,
    "maxItems": 12,
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["source_ref", "quote"],
        "properties": {
            "source_ref": {"type": "string", "pattern": r"^src_[0-9]{4}$"},
            "quote": {"type": "string", "minLength": 1, "maxLength": 800},
        },
    },
}
for _category in (
    "overview",
    "key_impacts",
    "obligations",
    "funding_and_timing",
    "uncertain_language",
):
    # overview/key_impacts share an object; detach before adding requirements.
    _item = copy.deepcopy(OUTPUT_SCHEMA["properties"][_category]["items"])
    _item["required"].append("source_quotes")
    _item["properties"]["source_quotes"] = SOURCE_QUOTES_SCHEMA
    OUTPUT_SCHEMA["properties"][_category]["items"] = _item

V12_OUTPUT_SCHEMA = copy.deepcopy(OUTPUT_SCHEMA)
V12_OUTPUT_SCHEMA["properties"]["schema_version"]["const"] = "1.2"
OUTPUT_SCHEMA["required"].append("glossary")
OUTPUT_SCHEMA["properties"]["glossary"] = {
    "type": "array", "maxItems": 64,
    "items": {
        "type": "object", "additionalProperties": False,
        "required": ["definition_id", "text", "source_refs", "source_quotes"],
        "properties": {
            "definition_id": {"type": "string", "minLength": 1, "maxLength": 200},
            "text": {"type": "string", "minLength": 1, "maxLength": 600},
            "source_refs": SOURCE_REFS_SCHEMA, "source_quotes": SOURCE_QUOTES_SCHEMA,
        },
    },
}


def _provider_schema(value: Any) -> Any:
    """Return the strict-schema subset supported by the provider API."""
    if isinstance(value, dict):
        return {
            key: _provider_schema(item)
            for key, item in value.items()
            if key != "uniqueItems"
        }
    if isinstance(value, list):
        return [_provider_schema(item) for item in value]
    return copy.deepcopy(value)


# OpenAI Structured Outputs supports only a subset of JSON Schema. Keep the
# stronger local schema above for post-response validation, including citation
# uniqueness, while sending only supported keywords to the provider.
PROVIDER_OUTPUT_SCHEMA: dict[str, Any] = _provider_schema(OUTPUT_SCHEMA)
# The wire format has one authoritative citation field. source_refs remains
# in the stored/API schema, but is derived by the adapter, not generated twice.
for _property in PROVIDER_OUTPUT_SCHEMA["properties"].values():
    _item = _property.get("items", {})
    if "source_quotes" in _item.get("properties", {}):
        _item["properties"].pop("source_refs")
        _item["required"].remove("source_refs")


def add_derived_source_refs(output):
    """Add API compatibility IDs without rewriting quotes or accepting bad IDs."""
    result = copy.deepcopy(output)
    if not isinstance(result, dict) or result.get("schema_version") != "1.3":
        return result
    for category in OUTPUT_SCHEMA["properties"]:
        items = result.get(category)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or "source_refs" in item:
                continue
            quotes = item.get("source_quotes")
            if isinstance(quotes, list) and all(
                isinstance(q, dict) and isinstance(q.get("source_ref"), str) for q in quotes
            ):
                item["source_refs"] = list(dict.fromkeys(q["source_ref"] for q in quotes))
    return result


def _validate_snapshot(source_snapshot: list[dict[str, Any]]) -> set[str]:
    source_ids: set[str] = set()
    for source in source_snapshot:
        source_ref = source.get("source_ref")
        quoted_text = source.get("quoted_text")
        expected_hash = source.get("text_sha256")
        if not isinstance(source_ref, str) or source_ref in source_ids:
            raise ValidationError("Invalid or duplicate server source reference")
        if not isinstance(quoted_text, str) or not quoted_text:
            raise ValidationError("Invalid server source text")
        actual_hash = hashlib.sha256(quoted_text.encode("utf-8")).hexdigest()
        if actual_hash != expected_hash:
            raise ValidationError("Server source text hash does not match")
        source_ids.add(source_ref)
    return source_ids


def validate_enhancement_output(
    value: dict[str, Any],
    source_snapshot: list[dict[str, Any]],
    *,
    expected_version: str | None = None,
    aggregate_glossary: bool = False,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise output_error("provider_output_not_object")
    if expected_version and value.get("schema_version") != expected_version:
        raise output_error("schema_version_mismatch", ["schema_version"])
    if value.get("schema_version") == "1.4":
        from .reader_targets import validate_reader_explanations, snapshot_targets
        return validate_reader_explanations(value, snapshot_targets(source_snapshot), source_snapshot)
    schema = (
        LEGACY_OUTPUT_SCHEMA if value.get("schema_version") == "1.1"
        else V12_OUTPUT_SCHEMA if value.get("schema_version") == "1.2"
        else OUTPUT_SCHEMA
    )
    if aggregate_glossary and value.get("schema_version") == "1.3":
        schema = copy.deepcopy(schema)
        schema["properties"]["glossary"]["maxItems"] = sum(
            len(source.get("glossary_targets", [])) for source in source_snapshot
        )
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    if errors:
        raise errors[0]

    try:
        source_ids = _validate_snapshot(source_snapshot)
    except ValidationError as error:
        # Keep legacy exception wording for callers, but classify safely.
        error.validator = "source_snapshot_invalid"
        raise
    for category in (
        "overview",
        "key_impacts",
        "obligations",
        "funding_and_timing",
        "uncertain_language",
        "glossary",
    ):
        seen_definitions = set()
        for item_index, item in enumerate(value.get(category, [])):
            for source_ref in item["source_refs"]:
                if source_ref not in source_ids:
                    raise ValidationError(
                        "Unknown source reference",
                        validator="citation_reference_unknown",
                        path=[category, item_index, "source_refs"],
                    )
            if value["schema_version"] in {"1.2", "1.3"}:
                quotes = item["source_quotes"]
                if {q["source_ref"] for q in quotes} != set(item["source_refs"]):
                    raise output_error(
                        "citation_reference_mismatch",
                        [category, item_index, "source_quotes"],
                    )
                sources = {s["source_ref"]: s["quoted_text"] for s in source_snapshot}
                for quote_index, quote in enumerate(quotes):
                    matches = citation_spans(sources[quote["source_ref"]], quote["quote"])
                    if len(matches) != 1:
                        code = (
                            "citation_quote_ambiguous"
                            if len(matches) > 1
                            else "citation_quote_not_found"
                        )
                        raise output_error(
                            code,
                            [
                                category,
                                item_index,
                                "source_quotes",
                                quote_index,
                                "quote",
                            ],
                        )
                if category == "glossary":
                    definition_id = item["definition_id"]
                    if definition_id in seen_definitions:
                        raise output_error("glossary_definition_duplicate", [category, item_index, "definition_id"])
                    seen_definitions.add(definition_id)
                    supported = False
                    for source in source_snapshot:
                        for target in source.get("glossary_targets", []):
                            if target["definition_id"] != definition_id:
                                continue
                            for quote in quotes:
                                if quote["source_ref"] != source["source_ref"]:
                                    continue
                                start, end = citation_spans(source["quoted_text"], quote["quote"])[0]
                                start += source["start_char"]
                                end += source["start_char"]
                                if target["start_char"] <= start < end <= target["end_char"]:
                                    supported = True
                    if not supported:
                        raise output_error("glossary_definition_unsupported", [category, item_index, "source_quotes"])
    return copy.deepcopy(value)
