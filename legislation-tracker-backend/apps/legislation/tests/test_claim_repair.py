import copy

import pytest

from apps.legislation.enhancements.provision_pipeline import plan_analysis, run_analysis
from apps.legislation.enhancements.source_graph import build_source_graph

from .test_source_first_schema import explanation


def fixture():
    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. SUPPORT\n(a) The Secretary shall pay $100.\n(b) Recipients shall use grant funds for tutoring.",
    )
    row = explanation(graph)
    row["summary"] = "The bill requires a payment and restricts grant spending."
    row["details"] = [
        "The Secretary must pay $100.",
        "Recipients must use grant funds for tutoring.",
    ]
    row["claims"].append(copy.deepcopy(row["claims"][0]))
    row["claims"][1].update(
        actor="Recipients", action="use grant funds for tutoring", money=[]
    )
    for i, item in enumerate(row["coverage_items"]):
        item["claim_indexes"] = [0 if i < 2 else 1]
        item["explanation_indexes"] = [1 if i < 2 else 2]
    return graph, row


@pytest.mark.parametrize("overwrite", [False, True])
def test_repair_only_failed_claim_and_never_overwrites_valid_claim(overwrite):
    graph, original = fixture()
    target_id = original["coverage_items"][-1]["item_id"]
    stages = []

    def invoke(call):
        stages.append(call.stage)
        if call.stage == "generation":
            return {"provisions": [copy.deepcopy(original)]}
        if call.stage == "synopsis":
            return {"text": original["summary"], "explanation_ids": [graph.units[0].id]}
        unit = call.payload["units"][0]
        assert [item["id"] for item in unit["source_checklist"]] == [target_id]
        # Complete source is still supplied; narrowing assignments must not strip context.
        assert (
            "The Secretary shall pay $100"
            in next(iter(call.payload["passages"].values()))["text"]
        )
        repaired = copy.deepcopy(original)
        repaired["claims"] = [copy.deepcopy(original["claims"][1])]
        repaired["claims"][0]["money"] = [
            {
                "amount": None,
                "currency": "USD",
                "measure": "restricted use of grant funds",
                "comparator": None,
                "purpose": "tutoring",
                "period": None,
                "base": None,
            }
        ]
        repaired["summary"] = (
            "This replacement overview must not replace the accepted overview."
        )
        repaired["details"] = [original["details"][1]]
        repaired["coverage_items"] = [
            {
                "item_id": target_id,
                "status": "explained",
                "claim_indexes": [0],
                "explanation_indexes": [1],
                "reason": None,
            }
        ]
        if overwrite:
            repaired["coverage_items"].append(
                copy.deepcopy(original["coverage_items"][0])
            )
        return {"provisions": [repaired]}

    result = run_analysis(plan_analysis(graph), invoke, lambda *args: None)
    assert "repair" in stages
    if overwrite:
        assert result.completeness == "partial"
    else:
        assert result.completeness == "complete"
        row = result.output["provisions"][0]
        assert row["summary"] == original["summary"]
        assert row["claims"][0] == original["claims"][0]
        assert row["details"][0] == original["details"][0]
        assert row["claims"][1]["money"][0]["purpose"] == "tutoring"


def test_full_claim_repair_preserves_an_already_valid_summary():
    graph, original = fixture()
    original["coverage_items"][2]["explanation_indexes"] = [0]

    def invoke(call):
        if call.stage == "synopsis":
            return {"text": original["summary"], "explanation_ids": [graph.units[0].id]}
        row = copy.deepcopy(original)
        if call.stage == "repair":
            row["summary"] = ""
            row["claims"][1]["money"] = [
                {
                    "amount": None,
                    "currency": "USD",
                    "measure": "restricted use",
                    "comparator": None,
                    "purpose": "tutoring",
                    "period": None,
                    "base": None,
                }
            ]
        return {"provisions": [row]}

    result = run_analysis(plan_analysis(graph), invoke, lambda *args: None)
    assert result.completeness == "complete"
    assert result.output["provisions"][0]["summary"] == original["summary"]


def test_missing_condition_repairs_its_source_component_not_unrelated_rules():
    from apps.legislation.enhancements.claim_repair import repair_items
    from apps.legislation.enhancements.provision_validation import validate_provision

    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. SUPPORT\n(a) The Secretary shall pay $100.\n(b) The Secretary may waive the fee only if the person is enrolled.",
    )
    row = explanation(graph)
    row["summary"] = "The section sets payment and exemption rules."
    row["details"] = [
        "The Secretary must pay $100.",
        "The Secretary may waive the fee for enrolled applicants.",
    ]
    row["claims"].append(
        {
            **copy.deepcopy(row["claims"][0]),
            "action": "waive the fee",
            "modality": "permitted",
            "money": [],
            "conditions": {
                "operator": "leaf",
                "text": "the person is enrolled",
                "evidence_ids": list(graph.units[0].own_passage_ids),
            },
        }
    )
    for i, item in enumerate(row["coverage_items"]):
        item["claim_indexes"] = [0 if i < 2 else 1]
        item["explanation_indexes"] = [1 if i < 2 else 2]
    findings = validate_provision(row, graph.units[0], graph, require_coverage=True)
    assert {f.code for f in findings} == {"condition_scope_unverified"}
    assert repair_items(row, findings, graph.units[0], graph) == {
        row["coverage_items"][-1]["item_id"]
    }


def test_missing_source_item_can_be_added_without_erasing_existing_claims():
    from apps.legislation.enhancements.claim_repair import merge_repair, repair_items
    from apps.legislation.enhancements.provision_validation import validate_provision

    graph, original = fixture()
    missing = original["coverage_items"].pop()
    original["claims"] = original["claims"][:1]
    original["details"] = original["details"][:1]
    checks = validate_provision(original, graph.units[0], graph, require_coverage=True)
    targets = repair_items(original, checks, graph.units[0], graph)
    assert targets == {missing["item_id"]}
    patch = copy.deepcopy(original)
    patch["claims"][0].update(actor="Recipients", action="use grant funds for tutoring")
    patch["details"] = ["Recipients must use grant funds for tutoring."]
    patch["coverage_items"] = [
        {**missing, "claim_indexes": [0], "explanation_indexes": [1]}
    ]
    merged = merge_repair(original, patch, targets, graph)
    assert merged["claims"][0] == original["claims"][0]
    assert merged["details"][0] == original["details"][0]
    assert merged["coverage_items"][-1]["item_id"] == missing["item_id"]


def test_money_only_patch_cannot_rewrite_any_legal_claim_or_explanation():
    graph, original = fixture()

    def invoke(call):
        if call.stage == "generation":
            return {"provisions": [copy.deepcopy(original)]}
        if call.stage == "synopsis":
            return {"text": original["summary"], "explanation_ids": [graph.units[0].id]}
        assert call.payload["repair_mode"] == "money_only"
        return {
            "financial_patches": [
                {
                    "unit_id": graph.units[0].id,
                    "claim_index": 1,
                    "money": [
                        {
                            "amount": None,
                            "currency": "USD",
                            "measure": "restricted use",
                            "comparator": None,
                            "purpose": "tutoring",
                            "period": None,
                            "base": None,
                        }
                    ],
                }
            ]
        }

    result = run_analysis(plan_analysis(graph), invoke, lambda *args: None)
    assert result.completeness == "complete"
    row = result.output["provisions"][0]
    assert row["details"] == original["details"]
    assert row["summary"] == original["summary"]
    assert {k: v for k, v in row["claims"][1].items() if k != "money"} == {
        k: v for k, v in original["claims"][1].items() if k != "money"
    }


@pytest.mark.parametrize("wrong_clause", [False, True])
def test_money_repair_targets_partial_and_empty_claims_without_moving_amounts(
    wrong_clause,
):
    graph, original = fixture()
    graph = build_source_graph(
        "1", "IH", graph.source_text.replace("$100.", "$100 and $200.")
    )
    fresh = explanation(graph)
    original["unit_id"] = fresh["unit_id"]
    original["coverage_items"] = fresh["coverage_items"]
    for claim in original["claims"]:
        claim["evidence_ids"] = fresh["claims"][0]["evidence_ids"]
    for i, item in enumerate(original["coverage_items"]):
        item["claim_indexes"] = [0 if i < 2 else 1]
        item["explanation_indexes"] = [1 if i < 2 else 2]
    original["details"][0] = "The Secretary must pay $100 and $200."

    def invoke(call):
        if call.stage == "generation":
            return {"provisions": [copy.deepcopy(original)]}
        if call.stage == "synopsis":
            return {"text": original["summary"], "explanation_ids": [graph.units[0].id]}
        assert call.payload["repair_mode"] == "money_only"
        assert {
            c["claim_index"] for c in call.payload["units"][0]["financial_claims"]
        } == {0, 1}
        extra = {**original["claims"][0]["money"][0], "amount": "200"}
        restriction = {
            **extra,
            "amount": None,
            "purpose": "tutoring",
            "measure": "restricted use",
        }
        return {
            "financial_patches": [
                {
                    "unit_id": graph.units[0].id,
                    "claim_index": 0,
                    "money": original["claims"][0]["money"]
                    + ([] if wrong_clause else [extra]),
                },
                {
                    "unit_id": graph.units[0].id,
                    "claim_index": 1,
                    "money": [extra if wrong_clause else restriction],
                },
            ]
        }

    result = run_analysis(plan_analysis(graph), invoke, lambda *args: None)
    assert result.completeness == ("partial" if wrong_clause else "complete")


@pytest.mark.parametrize(
    "amount", ["sNaN", "NaN", "Infinity", "1e999999", "$100", "1,00"]
)
def test_non_decimal_provider_amount_is_rejected_without_crashing(amount):
    graph, original = fixture()

    def invoke(call):
        if call.stage == "generation":
            return {"provisions": [copy.deepcopy(original)]}
        if call.stage == "synopsis":
            return {"text": original["summary"], "explanation_ids": [graph.units[0].id]}
        money = {**original["claims"][0]["money"][0], "amount": amount}
        return {
            "financial_patches": [
                {"unit_id": graph.units[0].id, "claim_index": 1, "money": [money]}
            ]
        }

    assert (
        run_analysis(plan_analysis(graph), invoke, lambda *args: None).completeness
        == "partial"
    )
