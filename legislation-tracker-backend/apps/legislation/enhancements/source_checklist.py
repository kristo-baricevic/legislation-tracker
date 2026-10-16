"""Lossless source-block accounting, not a claim of semantic completeness.

Blocks keep their full owning passage and its context. A list item is never
presented to generation without its chapeau or surrounding AND/OR conditions.
"""

import hashlib
import re
from decimal import Decimal, InvalidOperation

from .citations import citation_spans

MARKER = re.compile(r"(?m)^[ \t]*(?:``|[‘“])?\([A-Za-z0-9]+\)[ \t]+")
SIGNALS = {
    "amendment": r"\b(?:strik\w*|insert\w*|repeal\w*|redesignat\w*)\b",
    "financial": r"\$\s*\d|\b(?:shall|may|must)\s+(?:\w+\s+){0,8}(?:award grants|make grants|use (?:the )?grant funds|be fined|charge\s+(?:a\s+)?fee|require\s+(?:payment\s+of\s+)?(?:an?\s+)?(?:reasonable\s+)?fee|require\s+an?\s+applicant\b[^.;]{0,800}\bto\s+pay\s+an?\s+fee\b)|\bauthoriz\w*\s+to\s+be\s+appropriated\b",
    "condition": r"\b(?:if|unless|except|provided that|eligible|eligibility)\b",
    "duty_or_permission": r"\b(?:shall|must|may)\b",
}


def source_checklist(unit, graph):
    items = []
    for pid in unit.own_passage_ids:
        passage = graph.passages[pid]
        cuts = sorted(
            {0, len(passage.text), *(m.start() for m in MARKER.finditer(passage.text))}
        )
        for left, right in zip(cuts, cuts[1:], strict=False):
            raw = passage.text[left:right]
            kinds = sorted(
                kind
                for kind, pattern in SIGNALS.items()
                if re.search(pattern, raw, re.I)
            )
            structural = (
                bool(
                    re.fullmatch(
                        r"(?:SEC\.|SECTION)[ \t]+\d+[A-Za-z]?\.[ \t]+[A-Z0-9 \t,;:'\"()–—-]+\.",
                        raw.strip(),
                    )
                    or re.fullmatch(r"\s*\([A-Za-z0-9]+\)\s+[^.\n]+\.--\s*", raw)
                )
                and not kinds
            )
            start, end = passage.start + left, passage.start + right
            items.append(
                {
                    "id": hashlib.sha256(f"{pid}:{start}:{end}".encode()).hexdigest(),
                    "start": start,
                    "end": end,
                    "evidence_ids": [pid],
                    "kinds": (["structural_context"] if structural else []) + kinds,
                }
            )
    return items


def check_accounting(row, unit, graph):
    """Check assignment and structural support, never certify meaning by keywords."""
    from .provision_validation import _amounts

    def dollars(claims):
        values = set()
        for claim in claims:
            for money in claim["money"]:
                if money["currency"] == "USD" and money["amount"] is not None:
                    try:
                        values.add(Decimal(money["amount"].replace(",", "")))
                    except InvalidOperation:
                        pass  # The ordinary amount validator reports malformed values.
        return values

    expected = {i["id"]: i for i in source_checklist(unit, graph)}
    supplied = row.get("coverage_items", [])
    ids = [i["item_id"] for i in supplied]
    required = {
        key
        for key, item in expected.items()
        if "structural_context" not in item["kinds"]
    }
    if len(ids) != len(set(ids)) or not set(ids) <= set(expected):
        return [
            (
                "source_checklist_missing",
                "coverage_items",
                "Account for each assigned source item exactly once.",
            )
        ]
    failures = []
    if not required <= set(ids):
        failures.append(
            (
                "source_checklist_missing",
                "coverage_items",
                "Account for each assigned source item exactly once.",
            )
        )

    def add(code, index, message=None):
        failures.append(
            (code, f"coverage_items/{index}", message or code.replace("_", " "))
        )

    for index, item in enumerate(supplied):
        if any(
            type(i) is not int
            for i in item["claim_indexes"] + item["explanation_indexes"]
        ):
            add("source_checklist_invalid", index)
            continue
        if item["status"] == "unresolved":
            if (
                not (item["reason"] or "").strip()
                or item["claim_indexes"]
                or item["explanation_indexes"]
            ):
                add("source_checklist_invalid", index)
            elif "structural_context" not in expected[item["item_id"]]["kinds"]:
                add("source_item_unresolved", index, item["reason"])
            continue
        if (
            item["reason"] is not None
            or not item["claim_indexes"]
            or not item["explanation_indexes"]
        ):
            add("source_checklist_invalid", index)
            continue
        if any(i >= len(row["claims"]) for i in item["claim_indexes"]) or any(
            i > len(row["details"]) for i in item["explanation_indexes"]
        ):
            add("source_checklist_invalid", index)
            continue
        claims = [row["claims"][i] for i in item["claim_indexes"]]
        source = expected[item["item_id"]]
        if any(
            not set(c["evidence_ids"]) & set(source["evidence_ids"]) for c in claims
        ):
            add("source_checklist_evidence", index)
        if "financial" in source["kinds"] and not any(c["money"] for c in claims):
            add(
                "source_item_money_missing",
                index,
                f"Source block {source['start']}:{source['end']} requires a financial entry on its mapped claim. Preserve its purpose and restrictions; use a null amount when no fixed amount is stated, not zero or an invented dollar value.",
            )
        if _amounts(graph.source_text[source["start"] : source["end"]]) - dollars(
            claims
        ):
            add(
                "source_item_amount_missing",
                index,
                "Every explicit dollar amount in this source block must be represented on its mapped claim, not a neighboring rule.",
            )
    for claim_index, claim in enumerate(row["claims"]):
        mapped = [
            expected[item["item_id"]]
            for item in supplied
            if claim_index in item["claim_indexes"]
        ]
        supported_amounts = set().union(
            *(
                _amounts(graph.source_text[item["start"] : item["end"]])
                for item in mapped
            )
        )
        if dollars([claim]) - supported_amounts:
            failures.append(
                (
                    "amount_source_unmapped",
                    f"claims/{claim_index}/money",
                    "This dollar amount is not in the source blocks mapped to this claim.",
                )
            )
        pending = [node for node in [claim["conditions"], *claim["exceptions"]] if node]
        while pending:
            node = pending.pop()
            if node["operator"] != "leaf":
                pending.extend(node["children"])
                continue
            supported = False
            for pid in node["evidence_ids"]:
                passage = graph.passages[pid]
                spans = citation_spans(passage.text, node["text"], limit=None)
                if pid in unit.context_passage_ids and spans:
                    supported = True
                for start, end in spans:
                    if any(
                        pid in item["evidence_ids"]
                        and item["start"] < passage.start + end
                        and passage.start + start < item["end"]
                        for item in mapped
                    ):
                        supported = True
            if not supported:
                failures.append(
                    (
                        "condition_source_unmapped",
                        f"claims/{claim_index}/conditions",
                        "This condition is not supported by the source blocks mapped to this claim or its supplied context. Do not attach a neighboring rule's condition merely because its quote is in the same section.",
                    )
                )
    return failures
