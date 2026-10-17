"""Narrow repair assignments without letting a provider rewrite accepted claims."""

import copy
import re

from jsonschema import ValidationError

from .citations import citation_spans
from .source_checklist import source_checklist
from .source_first_schema import validate_source_first_schema


def repair_items(row, checks, unit, graph):
    """Return a closed set of failed source IDs, or None for whole-unit repair.

    Only localizable findings permit reuse. Shared claims and prose connect source
    items; repair the entire connected component, never sever a compound rule.
    """
    try:
        validate_source_first_schema({"provisions": [row]}, graph, [unit.id])
    except (ValidationError, KeyError, TypeError):
        return None
    items = row.get("coverage_items", [])
    targets = set()
    for check in checks:
        if check.code == "source_checklist_missing":
            expected = {item["id"] for item in source_checklist(unit, graph)}
            present = [item["item_id"] for item in items]
            if len(present) != len(set(present)) or not set(present) <= expected:
                return None
            missing = expected - set(present)
            if not missing:
                return None
            targets.update(missing)
            continue
        if check.code == "condition_scope_unverified":
            from .provision_validation import required_conditions

            pending = [
                node
                for claim in row["claims"]
                for node in [claim["conditions"], *claim["exceptions"]]
                if node
            ]
            leaves = []
            while pending:
                node = pending.pop()
                if node["operator"] == "leaf":
                    leaves.append(node["text"])
                else:
                    pending.extend(node["children"])
            for condition in required_conditions(unit, graph):
                if any(citation_spans(leaf, condition["text"]) for leaf in leaves):
                    continue
                matching = set()
                for pid in condition["evidence_ids"]:
                    if pid not in unit.own_passage_ids:
                        # A context-only condition needs a semantic assignment;
                        # never guess which own-source claim it qualifies.
                        return None
                    passage = graph.passages[pid]
                    for start, end in citation_spans(
                        passage.text, condition["text"], limit=None
                    ):
                        matching.update(
                            item["id"]
                            for item in source_checklist(unit, graph)
                            if pid in item["evidence_ids"]
                            and item["start"] < passage.start + end
                            and passage.start + start < item["end"]
                        )
                if not matching:
                    return None
                targets.update(matching)
            continue
        # The per-source money findings already identify the same omission.
        # Do not let the aggregate alert force a rewrite of unrelated claims.
        if check.code == "financial_coverage_unverified" and any(
            f.code in {"source_item_money_missing", "source_item_amount_missing"}
            for f in checks
        ):
            continue
        match = re.fullmatch(
            r"(coverage_items|claims|explanations)/(\d+)(?:/.*)?", check.path
        )
        if not match:
            return None
        kind, index = match[1], int(match[2])
        if kind == "coverage_items":
            if index >= len(items):
                return None
            targets.add(items[index]["item_id"])
        else:
            field = "claim_indexes" if kind == "claims" else "explanation_indexes"
            if kind == "explanations" and index == 0:
                return None
            matches = {item["item_id"] for item in items if index in item[field]}
            if not matches:
                return None
            targets.update(matches)
    while targets:
        previous_targets = set(targets)
        selected = [item for item in items if item["item_id"] in targets]
        claims = {i for item in selected for i in item["claim_indexes"]}
        prose = {i for item in selected for i in item["explanation_indexes"]}
        # A condition/exception can legitimately come from a different block.
        # Include that block and its connected claims in the repair assignment;
        # otherwise the repair cannot cite it without violating its own scope.
        for index in claims:
            if index >= len(row["claims"]):
                return None
            claim = row["claims"][index]
            pending = [
                node for node in [claim["conditions"], *claim["exceptions"]] if node
            ]
            while pending:
                node = pending.pop()
                if node["operator"] != "leaf":
                    pending.extend(node["children"])
                    continue
                for pid in node["evidence_ids"]:
                    if pid not in unit.own_passage_ids:
                        continue
                    passage = graph.passages[pid]
                    for start, end in citation_spans(
                        passage.text, node["text"], limit=None
                    ):
                        targets.update(
                            item["id"]
                            for item in source_checklist(unit, graph)
                            if pid in item["evidence_ids"]
                            and item["start"] < passage.start + end
                            and passage.start + start < item["end"]
                        )
        if 0 in prose:
            return None  # A failed summary cannot be frozen.
        connected = {
            item["item_id"]
            for item in items
            if claims.intersection(item["claim_indexes"])
            or prose.intersection(item["explanation_indexes"])
        }
        expanded = targets | connected
        if expanded == previous_targets:
            return targets
        targets = expanded
    return None


def narrow_assignment(payload_unit, targets, graph):
    payload_unit["source_checklist"] = [
        item for item in payload_unit["source_checklist"] if item["id"] in targets
    ]
    payload_unit["repair_scope"] = "source_items_only"
    selected = payload_unit["source_checklist"]

    def relevant(condition):
        for pid in condition["evidence_ids"]:
            if pid in payload_unit["context_passage_ids"]:
                return True
            passage = graph.passages[pid]
            for start, end in citation_spans(
                passage.text, condition["text"], limit=None
            ):
                if any(
                    pid in item["evidence_ids"]
                    and item["start"] < passage.start + end
                    and passage.start + start < item["end"]
                    for item in selected
                ):
                    return True
        return False

    payload_unit["required_conditions"] = [
        condition
        for condition in payload_unit["required_conditions"]
        if relevant(condition)
    ]


def merge_repair(original, replacement, targets, graph):
    """Keep untargeted facts and prose byte-for-byte; validate the merged row later."""
    validate_source_first_schema(
        {"provisions": [replacement]}, graph, [original["unit_id"]]
    )
    supplied = replacement.get("coverage_items", [])
    if (
        replacement["status"] != "explained"
        or len(supplied) != len(targets)
        or {item["item_id"] for item in supplied} != targets
    ):
        raise ValidationError("repair_assignment")
    # Check all indices before remapping. Do not allow floats, negatives or
    # dangling references to turn a malformed patch into a valid merged result.
    for item in supplied:
        for field, maximum in (
            ("claim_indexes", len(replacement["claims"]) - 1),
            ("explanation_indexes", len(replacement["details"])),
        ):
            if any(
                type(index) is not int or index < 0 or index > maximum
                for index in item[field]
            ):
                raise ValidationError("repair_index")
        if 0 in item["explanation_indexes"]:
            raise ValidationError("repair_summary_reference")
    kept = [
        item for item in original["coverage_items"] if item["item_id"] not in targets
    ]
    claims = sorted({i for item in kept for i in item["claim_indexes"]})
    details = sorted({i for item in kept for i in item["explanation_indexes"] if i})
    claim_map = {old: new for new, old in enumerate(claims)}
    detail_map = {old: new for new, old in enumerate(details, 1)}
    detail_map[0] = 0
    result = copy.deepcopy(original)
    result["claims"] = [
        copy.deepcopy(original["claims"][i]) for i in claims
    ] + copy.deepcopy(replacement["claims"])
    result["details"] = [original["details"][i - 1] for i in details] + copy.deepcopy(
        replacement["details"]
    )
    remapped = [
        {
            **item,
            "claim_indexes": [claim_map[i] for i in item["claim_indexes"]],
            "explanation_indexes": [detail_map[i] for i in item["explanation_indexes"]],
        }
        for item in kept
    ]
    remapped += [
        {
            **item,
            "claim_indexes": [i + len(claims) for i in item["claim_indexes"]],
            "explanation_indexes": [
                i + len(details) for i in item["explanation_indexes"]
            ],
        }
        for item in supplied
    ]
    by_id = {item["item_id"]: item for item in remapped}
    unit = next(u for u in graph.units if u.id == original["unit_id"])
    result["coverage_items"] = [
        by_id[item["id"]]
        for item in source_checklist(unit, graph)
        if item["id"] in by_id
    ]
    return result
