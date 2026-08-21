from __future__ import annotations

import copy
import hashlib
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

OUTPUT_SCHEMA_VERSION = "1.1"

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
        "schema_version": {"const": OUTPUT_SCHEMA_VERSION},
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
                    "kind": {"enum": ["funding", "timing"]},
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
) -> dict[str, Any]:
    errors = sorted(
        Draft202012Validator(OUTPUT_SCHEMA).iter_errors(value),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    if errors:
        raise errors[0]

    source_ids = _validate_snapshot(source_snapshot)
    for category in (
        "overview",
        "key_impacts",
        "obligations",
        "funding_and_timing",
        "uncertain_language",
    ):
        for item in value[category]:
            for source_ref in item["source_refs"]:
                if source_ref not in source_ids:
                    raise ValidationError(f"Unknown source reference: {source_ref}")
    return copy.deepcopy(value)
