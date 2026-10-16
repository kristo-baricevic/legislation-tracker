"""Strict provider contract; identity, evidence text and review status are server-owned."""

import copy
from urllib.parse import quote

from jsonschema import Draft202012Validator, ValidationError

VERSION = "2.0-source-first"
MAX_CLAIMS = 64
MAX_DETAILS_PER_CLAIM = 4
MAX_DETAILS = MAX_CLAIMS * MAX_DETAILS_PER_CLAIM


def obj(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def arr(items, maximum=32):
    return {"type": "array", "items": items, "maxItems": maximum}


TEXT = {"type": "string", "maxLength": 400}
NULL_TEXT = {"type": ["string", "null"], "maxLength": 400}
IDS = {**arr({"type": "string"}, 32), "minItems": 1, "uniqueItems": True}
LEAF = obj(
    {
        "operator": {"const": "leaf", "type": "string"},
        "text": {"type": "string", "maxLength": 6000},
        "evidence_ids": IDS,
    }
)
CONDITION = {
    "anyOf": [
        LEAF,
        obj(
            {
                "operator": {"enum": ["all", "any"], "type": "string"},
                "children": {**arr({"$ref": "#/$defs/condition"}, 32), "minItems": 1},
            }
        ),
    ]
}
MONEY = obj(
    {
        k: NULL_TEXT
        for k in (
            "amount",
            "currency",
            "measure",
            "comparator",
            "purpose",
            "period",
            "base",
        )
    }
)
MONEY["properties"]["amount"] = {
    "type": ["string", "null"],
    "maxLength": 100,
    "pattern": r"^[+-]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?$",
}
CLAIM = obj(
    {
        "actor": NULL_TEXT,
        "action": TEXT,
        "modality": {
            "type": "string",
            "enum": ["required", "permitted", "prohibited", "unspecified"],
        },
        "money": arr(MONEY),
        "conditions": {"anyOf": [{"type": "null"}, {"$ref": "#/$defs/condition"}]},
        "exceptions": arr({"$ref": "#/$defs/condition"}),
        "evidence_ids": IDS,
    }
)
EXPLANATION = obj(
    {
        "unit_id": {"type": "string"},
        "status": {"type": "string", "enum": ["explained", "unresolved"]},
        "summary": TEXT,
        "details": arr(TEXT, MAX_DETAILS),
        "unresolved_reason": NULL_TEXT,
        "claims": arr(CLAIM, MAX_CLAIMS),
    }
)
# Legacy records remain readable; new generation requires this field in its
# request-specific wire schema and the production orchestration validator.
EXPLANATION["properties"]["coverage_items"] = arr(
    obj(
        {
            "item_id": {"type": "string"},
            "status": {"type": "string", "enum": ["explained", "unresolved"]},
            "claim_indexes": {
                **arr({"type": "integer", "minimum": 0}, MAX_CLAIMS),
                "uniqueItems": True,
            },
            "explanation_indexes": {
                **arr({"type": "integer", "minimum": 0}, MAX_DETAILS + 1),
                "uniqueItems": True,
            },
            "reason": NULL_TEXT,
        }
    ),
    512,
)
PROVISION_SCHEMA = {
    **obj({"provisions": arr(EXPLANATION, 32)}),
    "$defs": {"condition": CONDITION},
}
SYNOPSIS_SCHEMA = obj(
    {
        "text": {"type": "string", "maxLength": 1200},
        "explanation_ids": arr({"type": "string"}, 128),
    }
)


def _evidence_ids(explanation):
    def walk(node, depth=0, nesting=0):
        if depth > 8 or nesting > 32:
            raise ValidationError("condition_depth")
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "evidence_ids":
                    if not isinstance(value, list) or any(
                        not isinstance(pid, str) for pid in value
                    ):
                        raise ValidationError("invalid_evidence_ids")
                    yield from value
                else:
                    yield from walk(value, depth + (key == "children"), nesting + 1)
        elif isinstance(node, list):
            for value in node:
                yield from walk(value, depth, nesting + 1)

    return list(dict.fromkeys(walk(explanation)))


def validate_source_first_schema(output, graph, unit_ids=None):
    # Bound nesting before invoking recursive JSON Schema validation.
    _evidence_ids(output)
    Draft202012Validator(PROVISION_SCHEMA).validate(output)
    expected = set(unit_ids if unit_ids is not None else (u.id for u in graph.units))
    actual = [p["unit_id"] for p in output["provisions"]]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValidationError("unit_assignment")
    units = {u.id: u for u in graph.units}
    for row in output["provisions"]:
        unit = units.get(row["unit_id"])
        if unit is None:
            raise ValidationError("unknown_unit")
        allowed = set(unit.own_passage_ids + unit.context_passage_ids)
        if any(pid not in allowed for pid in _evidence_ids(row)):
            raise ValidationError("unrelated_evidence")
        if row["status"] == "explained":
            if (
                not row["summary"].strip()
                or not row["claims"]
                or row["unresolved_reason"] is not None
            ):
                raise ValidationError("empty_explanation")
            for claim in row["claims"]:
                if not set(claim["evidence_ids"]) & set(unit.own_passage_ids):
                    raise ValidationError("context_only_claim")
        elif (
            row["claims"]
            or row["summary"]
            or row["details"]
            or not row["unresolved_reason"]
        ):
            raise ValidationError("unresolved_contains_prose")
    return output


def hydrate_evidence(explanation, graph):
    validate_source_first_schema(
        {"provisions": [explanation]}, graph, [explanation["unit_id"]]
    )
    result = copy.deepcopy(explanation)
    unit = next(u for u in graph.units if u.id == result["unit_id"])
    result["id"] = unit.id
    result["source_limitations"] = list(unit.unresolved_dependencies)
    result["evidence"] = [
        dict(
            id=p.id,
            text=p.text,
            start=p.start,
            end=p.end,
            text_sha256=p.text_sha256,
            section_label=" · ".join(filter(None, p.structural_path)),
            url=f"/documents/{quote(graph.document_id, safe='')}",
        )
        for pid in (
            _evidence_ids(result)
            or list(unit.own_passage_ids + unit.context_passage_ids)
        )
        for p in [graph.passages[pid]]
    ]
    return result
