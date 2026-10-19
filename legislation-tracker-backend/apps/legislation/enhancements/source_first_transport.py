"""Request-local, exact aliases; canonical hashes never depend on model copying."""

import copy
import json
from dataclasses import dataclass

from jsonschema import Draft202012Validator, ValidationError

from .source_first_schema import (
    MAX_DETAILS_PER_CLAIM,
    MONEY,
    PROVISION_SCHEMA,
    SYNOPSIS_SCHEMA,
    TEXT,
    _evidence_ids,
    arr,
    obj,
)


def _refs(value, units, passages, items=None):
    if isinstance(value, list):
        return [_refs(item, units, passages, items) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key == "unit_id":
            result[key] = units[item]
        elif key == "item_id" and items is not None:
            result[key] = items[item]
        elif key == "explanation_ids":
            result[key] = [units[ref] for ref in item]
        elif key == "evidence_ids":
            result[key] = [passages[ref] for ref in item]
        else:
            result[key] = _refs(item, units, passages, items)
    return result


@dataclass(frozen=True)
class Transport:
    payload: dict
    schema: dict
    units: dict
    passages: dict
    items: dict

    def decode(self, output):
        _evidence_ids(output)  # Bound recursion before JSON Schema validation.
        Draft202012Validator(self.schema).validate(output)
        if self.payload.get("repair_mode") == "money_only":
            return _refs(output, {v: k for k, v in self.units.items()}, {})

        def expand(value):
            if isinstance(value, list):
                return [expand(item) for item in value]
            if not isinstance(value, dict):
                return value
            if value.get("operator") == "block":
                item = next(
                    item
                    for unit in self.payload["units"]
                    for item in unit["source_checklist"]
                    if item["id"] == value["item_id"]
                )
                return {
                    "operator": "leaf",
                    "text": item["text"],
                    "evidence_ids": list(item["evidence_ids"]),
                }
            if value.get("operator") == "source":
                return {
                    "operator": "leaf",
                    **copy.deepcopy(
                        self.payload["required_conditions"][value["condition_id"]]
                    ),
                }
            return {key: expand(item) for key, item in value.items()}

        expanded = expand(output)
        if self.items:
            assignments = {
                unit["id"]: {item["id"] for item in unit["source_checklist"]}
                for unit in self.payload["units"]
            }
            for row in expanded["provisions"]:
                row["details"] = []
                coverage = {}
                for index, claim in enumerate(row["claims"]):
                    refs = claim.pop("source_item_ids")
                    sentences = claim.pop("explanations")
                    detail_indexes = list(
                        range(
                            len(row["details"]) + 1,
                            len(row["details"]) + len(sentences) + 1,
                        )
                    )
                    row["details"].extend(sentences)
                    for ref in refs:
                        if ref not in assignments[row["unit_id"]]:
                            raise ValidationError("unrelated_source_item")
                        entry = coverage.setdefault(
                            ref,
                            {
                                "item_id": ref,
                                "status": "explained",
                                "claim_indexes": [],
                                "explanation_indexes": [],
                                "reason": None,
                            },
                        )
                        entry["claim_indexes"].append(index)
                        entry["explanation_indexes"].extend(detail_indexes)
                for item in row.pop("unresolved_items"):
                    ref = item["item_id"]
                    if ref not in assignments[row["unit_id"]] or ref in coverage:
                        raise ValidationError("source_item_assignment")
                    coverage[ref] = {
                        **item,
                        "status": "unresolved",
                        "claim_indexes": [],
                        "explanation_indexes": [],
                    }
                row["coverage_items"] = list(coverage.values())
        return _refs(
            expanded,
            {v: k for k, v in self.units.items()},
            {v: k for k, v in self.passages.items()},
            {v: k for k, v in self.items.items()},
        )


def prepare_transport(stage, payload):
    synopsis = stage == "synopsis"
    unit_ids = (
        [row["unit_id"] for row in payload["explanations"]]
        if synopsis
        else [u["id"] for u in payload["units"]]
    )
    units = {uid: f"u{i}" for i, uid in enumerate(unit_ids, 1)}
    passage_ids = (
        list(dict.fromkeys(_evidence_ids(payload)))
        if synopsis
        else list(payload["passages"])
    )
    passages = {pid: f"p{i}" for i, pid in enumerate(passage_ids, 1)}
    item_ids = (
        []
        if synopsis
        else [
            item["id"]
            for unit in payload["units"]
            for item in unit.get("source_checklist", [])
        ]
    )
    items = {item_id: f"s{i}" for i, item_id in enumerate(item_ids, 1)}
    if synopsis:
        # Synopsis selects summaries only. Claims and source hashes are not needed.
        wire = {
            "explanations": [
                {"unit_id": units[row["unit_id"]], "summary": row["summary"]}
                for row in payload["explanations"]
            ]
        }
    else:
        wire = {"units": [], "passages": {}, "required_conditions": {}}
        condition_ids = {}
        for original in payload["units"]:
            unit = copy.deepcopy(original)
            unit["id"] = units[unit["id"]]
            for field in ("own_passage_ids", "context_passage_ids"):
                unit[field] = [passages[pid] for pid in unit.get(field, [])]
            # Group metadata is server-owned, not evidence the model may cite.
            unit.pop("parent_id", None)
            unit.pop("condition_group_id", None)
            if "source_checklist" in unit:
                unit["source_checklist"] = [
                    {**_refs(item, units, passages), "id": items[item["id"]]}
                    for item in unit["source_checklist"]
                ]
            if "required_conditions" in unit:
                refs = []
                for item in unit.pop("required_conditions"):
                    identity = (item["text"], tuple(item["evidence_ids"]))
                    if identity not in condition_ids:
                        cid = f"c{len(condition_ids) + 1}"
                        condition_ids[identity] = cid
                        wire["required_conditions"][cid] = _refs(item, units, passages)
                    refs.append(condition_ids[identity])
                unit["required_condition_ids"] = refs
            wire["units"].append(unit)
        for pid, original in payload["passages"].items():
            passage = {
                k: copy.deepcopy(v)
                for k, v in original.items()
                if k not in {"id", "text_sha256"}
            }
            passage["id"] = passages[pid]
            # Whole owning text is already supplied in ordered source blocks.
            # Avoid sending it twice, but only after exact reconstruction proves
            # no character is lost. Partial repairs retain the full passage.
            blocks = sorted(
                (
                    item
                    for unit in payload["units"]
                    for item in unit.get("source_checklist", [])
                    if item["evidence_ids"] == [pid]
                ),
                key=lambda item: item["start"],
            )
            if (
                blocks
                and all("text" in item for item in blocks)
                and "".join(item["text"] for item in blocks) == original["text"]
            ):
                passage.pop("text", None)
                passage["source_item_ids_in_order"] = [
                    items[item["id"]] for item in blocks
                ]
            wire["passages"][passages[pid]] = passage
        if "findings" in payload:
            wire["findings"] = {
                units[uid]: _refs(value, units, passages)
                for uid, value in payload["findings"].items()
            }
    schema = copy.deepcopy(SYNOPSIS_SCHEMA if synopsis else PROVISION_SCHEMA)
    if not synopsis:
        schema["properties"]["provisions"].update(
            minItems=len(units), maxItems=len(units)
        )
        row_schema = schema["properties"]["provisions"]["items"]
        if items:
            # Conditions are source references, not model-authored quotations.
            # Canonical historical rows keep leaf support; the wire contract
            # cannot introduce fabricated condition text.
            schema["$defs"]["condition"]["anyOf"] = [
                branch
                for branch in schema["$defs"]["condition"]["anyOf"]
                if branch["properties"]["operator"].get("const") != "leaf"
            ]
            schema["$defs"]["condition"]["anyOf"].insert(
                0,
                obj(
                    {
                        "operator": {"type": "string", "const": "block"},
                        "item_id": {"type": "string", "enum": list(items.values())},
                    }
                ),
            )
            # The model owns claims and prose, not positional bookkeeping.
            row_schema["properties"].pop("coverage_items")
            row_schema["properties"].pop("details")
            row_schema["required"].remove("details")
            row_schema["required"].append("unresolved_items")
            item_ref = {"type": "string", "enum": list(items.values())}
            row_schema["properties"]["unresolved_items"] = arr(
                obj(
                    {
                        "item_id": item_ref,
                        "reason": {"type": "string", "minLength": 1, "maxLength": 400},
                    }
                ),
                512,
            )
            claim_schema = row_schema["properties"]["claims"]["items"]
            claim_schema["properties"].update(
                source_item_ids={
                    **arr(item_ref, 512),
                    "minItems": 1,
                    "uniqueItems": True,
                },
                explanations={**arr(TEXT, MAX_DETAILS_PER_CLAIM), "minItems": 1},
            )
            claim_schema["required"].extend(["source_item_ids", "explanations"])
        else:
            row_schema["properties"].pop("coverage_items", None)
    if not synopsis and wire["required_conditions"]:
        schema["$defs"]["condition"]["anyOf"].insert(
            0,
            obj(
                {
                    "operator": {"type": "string", "const": "source"},
                    "condition_id": {
                        "type": "string",
                        "enum": list(wire["required_conditions"]),
                    },
                }
            ),
        )

    def constrain(node):
        if isinstance(node, dict):
            props = node.get("properties", {})
            if "unit_id" in props:
                props["unit_id"]["enum"] = list(units.values())
            for field, refs in (("evidence_ids", passages), ("explanation_ids", units)):
                if field in props:
                    props[field]["items"]["enum"] = list(refs.values())
            for value in node.values():
                constrain(value)
        elif isinstance(node, list):
            for value in node:
                constrain(value)

    constrain(schema)
    if items and not synopsis:
        variants = []
        for unit in wire["units"]:
            variant = copy.deepcopy(schema["properties"]["provisions"]["items"])
            props = variant["properties"]
            props["claims"]["items"]["properties"]["money"]["items"] = {
                "$ref": "#/$defs/money"
            }
            props["unit_id"]["enum"] = [unit["id"]]
            allowed = [item["id"] for item in unit["source_checklist"]]
            allowed_passages = list(
                dict.fromkeys(unit["own_passage_ids"] + unit["context_passage_ids"])
            )
            props["claims"]["items"]["properties"]["evidence_ids"]["items"]["enum"] = (
                allowed_passages
            )
            condition_key = f"condition_{unit['id']}"
            condition_schema = copy.deepcopy(schema["$defs"]["condition"])
            # Request-local IDs are not globally interchangeable: constrain
            # nested conditions as well as the claim's own source references.
            branches = []
            for branch in condition_schema["anyOf"]:
                fields = branch.get("properties", {})
                if "condition_id" in fields:
                    if not unit.get("required_condition_ids"):
                        continue
                    fields["condition_id"]["enum"] = unit["required_condition_ids"]
                if "item_id" in fields:
                    fields["item_id"]["enum"] = allowed
                if "evidence_ids" in fields:
                    fields["evidence_ids"]["items"]["enum"] = allowed_passages
                branches.append(branch)
            condition_schema["anyOf"] = branches

            def local_conditions(node, condition_key=condition_key):
                if isinstance(node, dict):
                    if node.get("$ref") == "#/$defs/condition":
                        node["$ref"] = f"#/$defs/{condition_key}"
                    for value in node.values():
                        local_conditions(value)
                elif isinstance(node, list):
                    for value in node:
                        local_conditions(value)

            local_conditions(condition_schema)
            local_conditions(variant)
            schema["$defs"][condition_key] = condition_schema
            props["claims"]["items"]["properties"]["source_item_ids"]["items"][
                "enum"
            ] = allowed
            props["unresolved_items"]["items"]["properties"]["item_id"]["enum"] = (
                allowed
            )
            variants.append(variant)
        schema["properties"]["provisions"]["items"] = {"anyOf": variants}
        schema["$defs"]["money"] = copy.deepcopy(MONEY)
        del schema["$defs"]["condition"]
        # Per-unit enums prevent cross-section references. Share identical schema
        # fragments so this stronger contract does not multiply request size.
        shared = {}

        def compact(node):
            if isinstance(node, list):
                return [compact(value) for value in node]
            if not isinstance(node, dict):
                return node
            reduced = {key: compact(value) for key, value in node.items()}
            identity = json.dumps(reduced, sort_keys=True)
            if ("type" in reduced or "anyOf" in reduced) and len(identity) > 120:
                if identity not in shared:
                    key = f"shared{len(shared)}"
                    shared[identity] = key
                    schema["$defs"][key] = reduced
                return {"$ref": f"#/$defs/{shared[identity]}"}
            return reduced

        schema["properties"]["provisions"]["items"] = compact(
            schema["properties"]["provisions"]["items"]
        )
        for key in [key for key in schema["$defs"] if key.startswith("condition_")]:
            schema["$defs"][key] = compact(schema["$defs"][key])
    if payload.get("repair_mode") == "money_only":
        wire["repair_mode"] = "money_only"
        schema = obj(
            {
                "financial_patches": arr(
                    obj(
                        {
                            "unit_id": {"type": "string", "enum": list(units.values())},
                            "claim_index": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": 63,
                            },
                            "money": arr(MONEY),
                        }
                    ),
                    512,
                )
            }
        )
    return Transport(wire, schema, units, passages, items)
