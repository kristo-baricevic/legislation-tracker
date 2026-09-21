from __future__ import annotations

import copy
import hashlib
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

from .diagnostics import output_error

OUTPUT_SCHEMA_VERSION = "1.2"

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
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise output_error("provider_output_not_object")
    if expected_version and value.get("schema_version") != expected_version:
        raise output_error("schema_version_mismatch", ["schema_version"])
    schema = (
        LEGACY_OUTPUT_SCHEMA if value.get("schema_version") == "1.1" else OUTPUT_SCHEMA
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
    ):
        for item_index, item in enumerate(value[category]):
            for source_ref in item["source_refs"]:
                if source_ref not in source_ids:
                    raise ValidationError(
                        "Unknown source reference",
                        validator="citation_reference_unknown",
                        path=[category, item_index, "source_refs"],
                    )
            if value["schema_version"] == "1.2":
                quotes = item["source_quotes"]
                if {q["source_ref"] for q in quotes} != set(item["source_refs"]):
                    raise output_error(
                        "citation_reference_mismatch",
                        [category, item_index, "source_quotes"],
                    )
                sources = {s["source_ref"]: s["quoted_text"] for s in source_snapshot}
                for quote_index, quote in enumerate(quotes):
                    if (
                        not quote["quote"].strip()
                        or sources[quote["source_ref"]].count(quote["quote"]) != 1
                    ):
                        code = (
                            "citation_quote_ambiguous"
                            if quote["quote"].strip()
                            and sources[quote["source_ref"]].count(quote["quote"]) > 1
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
    return copy.deepcopy(value)
