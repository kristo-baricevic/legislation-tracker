"""Bounded, hand-annotated correctness checks; never infer gold facts from output."""

import re

from jsonschema import ValidationError, validate

STRINGS = {
    "type": "array",
    "items": {"type": "string", "minLength": 1},
    "uniqueItems": True,
}
CATEGORY = {
    "enum": [
        "financial",
        "line_item",
        "definition",
        "synopsis",
        "overview",
        "key_impacts",
        "obligations",
        "funding_and_timing",
        "uncertain_language",
    ]
}
FACT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "category"],
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "category": CATEGORY,
        "fields": {"type": "object", "minProperties": 1},
        "patterns": {**STRINGS, "minItems": 1},
        "forbidden_patterns": STRINGS,
        "evidence_contains": {**STRINGS, "minItems": 1},
    },
    "anyOf": [{"required": ["fields"]}, {"required": ["patterns"]}],
}
PROFILE = {
    "type": "object",
    "additionalProperties": False,
    "required": ["facts"],
    "properties": {
        "facts": {"type": "array", "items": FACT},
        "closed_categories": {**STRINGS, "items": CATEGORY},
        "source_only": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "quote"],
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "quote": {"type": "string", "minLength": 1},
                },
            },
        },
    },
}
ANNOTATION = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"nlp": PROFILE, "ai": PROFILE},
    "minProperties": 1,
}


def source_only(item):
    return item.get("text", "").startswith("Source text (not simplified):")


def normalized(text):
    return " ".join(text.split())


def _value(value):
    if isinstance(value, str):
        return normalized(value)
    if isinstance(value, list):
        return [_value(v) for v in value]
    return value


def _matches(fact, item):
    if source_only(item) or item.get("category") != fact["category"]:
        return False
    if any(
        key not in item or _value(item[key]) != _value(value)
        for key, value in fact.get("fields", {}).items()
    ):
        return False
    text = normalized(item.get("text", ""))
    if not all(re.search(p, text, re.I | re.S) for p in fact.get("patterns", [])):
        return False
    if any(re.search(p, text, re.I | re.S) for p in fact.get("forbidden_patterns", [])):
        return False
    quotes = item.get("evidence_quotes", [])
    if fact.get("evidence_contains") and item.get("evidence_valid") is not True:
        return False
    return all(
        any(normalized(q) in normalized(actual) for actual in quotes)
        for q in fact.get("evidence_contains", [])
    )


def score_correctness(case, items, pipeline):
    result = {
        "evaluated": False,
        "failures": [],
        "missing_fact_ids": [],
        "unexpected_item_indices": [],
        "missing_source_only_ids": [],
        "source_only_leak_indices": [],
        "matched_fact_count": 0,
        "expected_fact_count": 0,
        "fact_recall": None,
        "closed_category_precision": None,
        "expected_source_only_count": 0,
    }
    if "correctness" not in case:
        return result
    try:
        validate(case["correctness"], ANNOTATION)
        for profile in case["correctness"].values():
            if not any(
                profile.get(k) for k in ("facts", "closed_categories", "source_only")
            ):
                raise ValueError("Empty correctness profile")
            all_ids = [
                f["id"] for f in profile["facts"] + profile.get("source_only", [])
            ]
            if len(set(all_ids)) != len(all_ids):
                raise ValueError("Duplicate oracle IDs")
            for fact in profile["facts"]:
                for pattern in fact.get("patterns", []) + fact.get(
                    "forbidden_patterns", []
                ):
                    re.compile(pattern)
                for quote in fact.get("evidence_contains", []):
                    if not normalized(quote) or normalized(quote) not in normalized(
                        case.get("text", "")
                    ):
                        raise ValueError("Oracle evidence is absent from source")
            for expected in profile.get("source_only", []):
                if not normalized(expected["quote"]) or normalized(
                    expected["quote"]
                ) not in normalized(case.get("text", "")):
                    raise ValueError("Source-only oracle is absent from source")
    except (ValidationError, ValueError, re.error):
        result["failures"] = ["invalid_correctness_annotation"]
        return result
    profile = case["correctness"].get(pipeline)
    if profile is None:
        return result
    result["evaluated"] = True
    facts = profile["facts"]
    # Maximum bipartite matching: one output may satisfy only one gold fact.
    # Reassign broad matches when a later, more specific fact needs that item.
    edges = [
        [j for j, item in enumerate(items) if _matches(fact, item)] for fact in facts
    ]
    owners = {}

    def assign(fact_index, visited):
        for item_index in edges[fact_index]:
            if item_index in visited:
                continue
            visited.add(item_index)
            if item_index not in owners or assign(owners[item_index], visited):
                owners[item_index] = fact_index
                return True
        return False

    for index in range(len(facts)):
        assign(index, set())
    matched = set(owners.values())
    result["missing_fact_ids"] = [
        f["id"] for i, f in enumerate(facts) if i not in matched
    ]
    result["expected_fact_count"] = len(facts)
    result["matched_fact_count"] = len(matched)
    result["fact_recall"] = len(matched) / len(facts) if facts else None
    closed = profile.get("closed_categories", [])
    candidates = [i for i, item in enumerate(items) if item.get("category") in closed]
    result["unexpected_item_indices"] = [i for i in candidates if i not in owners]
    result["closed_category_precision"] = (
        sum(i in owners for i in candidates) / len(candidates) if candidates else None
    )
    source_expectations = profile.get("source_only", [])
    result["expected_source_only_count"] = len(source_expectations)
    leaks = set()
    for expected in source_expectations:
        quote = normalized(expected["quote"])
        if not any(
            source_only(item)
            and item.get("evidence_valid") is True
            and any(quote in normalized(q) for q in item.get("evidence_quotes", []))
            for item in items
        ):
            result["missing_source_only_ids"].append(expected["id"])
        for index, item in enumerate(items):
            if source_only(item):
                continue
            if any(
                quote in normalized(q) or normalized(q) in quote
                for q in item.get("evidence_quotes", [])
                if q.strip()
            ):
                leaks.add(index)
    result["source_only_leak_indices"] = sorted(leaks)
    for key, failure in (
        ("missing_fact_ids", "incorrect_or_missing_facts"),
        ("unexpected_item_indices", "unexpected_claims"),
        ("missing_source_only_ids", "incomplete_source_only"),
        ("source_only_leak_indices", "unsafe_partial_interpretation"),
    ):
        if result[key]:
            result["failures"].append(failure)
    return result
