import copy

import pytest
from jsonschema import ValidationError

from apps.legislation.enhancements.source_first_schema import (
    hydrate_evidence,
    validate_source_first_schema,
)
from apps.legislation.enhancements.source_graph import build_source_graph


@pytest.fixture
def graph():
    return build_source_graph(
        "511",
        "IH",
        "SEC. 1. PAYMENT\nThe Secretary shall pay $100.\nSEC. 2. REVIEW\nA court may review a denial.",
    )


def explanation(graph, index=0):
    from apps.legislation.enhancements.source_checklist import source_checklist

    unit = graph.units[index]
    return {
        "unit_id": unit.id,
        "status": "explained",
        "summary": "The Secretary must pay $100.",
        "details": [],
        "unresolved_reason": None,
        "coverage_items": [
            {
                "item_id": item["id"],
                "status": "explained",
                "claim_indexes": [0],
                "explanation_indexes": [0],
                "reason": None,
            }
            for item in source_checklist(unit, graph)
        ],
        "claims": [
            {
                "actor": "The Secretary",
                "action": "pay $100",
                "modality": "required",
                "money": [
                    {
                        "amount": "100",
                        "currency": "USD",
                        "measure": "payment",
                        "comparator": "exact",
                        "purpose": None,
                        "period": None,
                        "base": None,
                    }
                ],
                "conditions": None,
                "exceptions": [],
                "evidence_ids": list(unit.own_passage_ids),
            }
        ],
    }


def test_valid_and_hydrated(graph):
    output = {"provisions": [explanation(graph)]}
    assert (
        validate_source_first_schema(output, graph, unit_ids=[graph.units[0].id])
        == output
    )
    hydrated = hydrate_evidence(output["provisions"][0], graph)
    assert (
        hydrated["evidence"][0]["text"]
        == "SEC. 1. PAYMENT\nThe Secretary shall pay $100.\n"
    )
    assert hydrated["evidence"][0]["url"] == "/documents/511"


def test_complete_source_condition_is_not_subject_to_summary_length_limit():
    condition = (
        "only if " + "the applicant maintains residence and " * 15 + "is employed."
    )
    graph = build_source_graph(
        "1", "IH", "SEC. 1. PAYMENT\nThe Secretary shall pay $100 " + condition
    )
    row = explanation(graph)
    row["claims"][0]["conditions"] = {
        "operator": "leaf",
        "text": condition,
        "evidence_ids": list(graph.units[0].own_passage_ids),
    }
    validate_source_first_schema({"provisions": [row]}, graph)
    row["summary"] = condition
    with pytest.raises(ValidationError):
        validate_source_first_schema({"provisions": [row]}, graph)


@pytest.mark.parametrize(
    "mutation",
    [
        "quote",
        "unknown",
        "unrelated",
        "stale",
        "duplicate",
        "missing",
        "approved",
        "coverage",
        "deep",
    ],
)
def test_rejects_single_invalid_mutation(graph, mutation):
    output = {"provisions": [explanation(graph)]}
    validate_source_first_schema(output, graph, unit_ids=[graph.units[0].id])
    claim = output["provisions"][0]["claims"][0]
    if mutation == "quote":
        claim["quote"] = "invented"
    if mutation == "unknown":
        claim["evidence_ids"] = ["unknown"]
    if mutation == "unrelated":
        claim["evidence_ids"] = list(graph.units[1].own_passage_ids)
    if mutation == "stale":
        claim["evidence_ids"] = list(
            build_source_graph("511", "ENR", graph.source_text).passages
        )[:1]
    if mutation == "duplicate":
        output["provisions"].append(copy.deepcopy(output["provisions"][0]))
    if mutation == "missing":
        output["provisions"] = []
    if mutation == "approved":
        output["semantic_review_status"] = "approved"
    if mutation == "coverage":
        output["coverage"] = "complete"
    if mutation == "deep":
        node = {
            "operator": "leaf",
            "text": "only residents",
            "evidence_ids": list(graph.units[0].own_passage_ids),
        }
        for _ in range(10):
            node = {"operator": "all", "children": [node]}
        claim["conditions"] = node
    with pytest.raises(ValidationError):
        validate_source_first_schema(output, graph, unit_ids=[graph.units[0].id])
