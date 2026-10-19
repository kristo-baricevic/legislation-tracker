"""Required source-candidate acknowledgements, not a semantic truth oracle."""

import copy

from .schema import PROVIDER_OUTPUT_SCHEMA


def response_schema(checklist):
    entry = {
        "type": "object",
        "additionalProperties": False,
        "required": ["status", "output_paths", "reason"],
        "properties": {
            "status": {"type": "string", "enum": ["explained", "unresolved"]},
            "output_paths": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string"},
        },
    }
    schema = copy.deepcopy(PROVIDER_OUTPUT_SCHEMA)
    schema.setdefault("$defs", {})["coverage_entry"] = entry
    schema["required"].append("coverage_response")
    schema["properties"]["coverage_response"] = {
        "type": "object",
        "additionalProperties": False,
        "required": [row["id"] for row in checklist],
        "properties": {
            row["id"]: {"$ref": "#/$defs/coverage_entry"} for row in checklist
        },
    }
    return schema


def provision_schema(checklist):
    quote_schema = copy.deepcopy(
        PROVIDER_OUTPUT_SCHEMA["properties"]["overview"]["items"]["properties"][
            "source_quotes"
        ]
    )
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["provisions"],
        "$defs": {
            "provision": {
                "type": "object",
                "additionalProperties": False,
                "required": ["status", "text", "reason", "source_quotes"],
                "properties": {
                    "status": {"type": "string", "enum": ["explained", "unresolved"]},
                    "text": {"type": "string"},
                    "reason": {"type": "string"},
                    "source_quotes": quote_schema,
                },
            }
        },
        "properties": {
            "provisions": {
                "type": "object",
                "additionalProperties": False,
                "required": [r["id"] for r in checklist],
                "properties": {
                    r["id"]: {"$ref": "#/$defs/provision"} for r in checklist
                },
            }
        },
    }
