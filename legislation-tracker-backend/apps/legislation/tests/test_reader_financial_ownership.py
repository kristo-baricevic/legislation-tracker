"""Recovered financial evidence keeps every source owner's dependencies."""

import copy

import pytest

from apps.legislation.enhancements.reader_discovery import (
    retain_missing_financial_rules,
    retained_financial_indices,
    validate_source_review,
)
from apps.legislation.enhancements.reader_reconciliation import reconcile_review
from apps.legislation.tests.test_reader_financial_reconciliation import (
    FinancialProvider,
    _financial_plan,
)


@pytest.mark.parametrize("separate_ranges", [False, True])
def test_recovered_financial_rows_receive_each_source_owners_dependencies(
    settings, separate_ranges
):
    plan, review = _financial_plan(settings)
    first, second, dependency = plan.source_snapshot
    # One known financial provision spans two independently mapped sources.
    # Only the second source has outstanding dependency evidence.
    first.pop("deferred_context_source_refs")
    first.pop("deferred_context_quote_ids")
    second["deferred_context_source_refs"] = [dependency["source_ref"]]
    second["deferred_context_quote_ids"] = {dependency["source_ref"]: ["p0001"]}
    first["reader_targets"][0]["evidence_ranges"] = (
        [
            (first["start_char"], first["end_char"]),
            (second["start_char"], second["end_char"]),
        ]
        if separate_ranges
        else [(first["start_char"], second["end_char"])]
    )

    retain_missing_financial_rules(review, plan.source_snapshot)
    recovered = copy.deepcopy(review["financial_items"])
    assert len(recovered) == 2
    for item, source in zip(recovered, (first, second), strict=True):
        assert item["text"] == source["quoted_text"].strip()
        assert {q["source_ref"] for q in item["source_quotes"]} == {
            source["source_ref"]
        }
        assert (
            "".join(q["quote"] for q in item["source_quotes"]) == source["quoted_text"]
        )
    # Reconstruction is stable on resume and does not duplicate either part.
    retain_missing_financial_rules(review, plan.source_snapshot)
    assert review["financial_items"] == recovered

    provider = FinancialProvider()
    result, _, calls = reconcile_review(plan, review, provider, "", lambda: None, 100)
    assert calls == 1
    metadata = result["dependency_review"]
    assert set(metadata["base_items"]) == {"financial_items:1"}
    assert metadata["base_items"]["financial_items:1"]["value"] == recovered[1]
    receipt = metadata["pages"][0]
    assert receipt["descriptor"]["owner_source_ref"] == second["source_ref"]
    assert receipt["descriptor"]["item_ids"] == ["financial_items:1"]
    key = f"{dependency['source_ref']}:p0001"
    assert receipt["response"]["record_checks"][key] == {
        "status": "applies",
        "item_ids": ["financial_items:1"],
        "reason": None,
    }
    assert result["financial_items"][0] == recovered[0]
    assert "providing emergency care" in result["financial_items"][1]["text"]
    assert result["financial_items"][1]["source_quotes"][-1] == {
        "source_ref": dependency["source_ref"],
        "quote": dependency["quoted_text"],
    }
    validate_source_review(result, plan.source_snapshot)

    # Once the accepted receipt exists, replay must not pay for it again.
    class NoCalls:
        def enhance_bill(self, **_):
            pytest.fail("A completed financial dependency was requested twice")

    replayed, _, replay_calls = reconcile_review(
        plan, result, NoCalls(), "", lambda: None, 100
    )
    assert replayed == result
    assert replay_calls == 0


@pytest.mark.parametrize("deferred", [False, True])
def test_mixed_size_recovered_owners_keep_independent_source_provenance(
    settings, deferred
):
    plan, review = _financial_plan(settings, long_source=True)
    first, second, dependency = plan.source_snapshot
    first["reader_targets"][0]["evidence_ranges"] = [
        (first["start_char"], second["end_char"])
    ]
    if deferred:
        # Both the long source and its short sibling enter the receipt base.
        second["deferred_context_source_refs"] = [dependency["source_ref"]]
        second["deferred_context_quote_ids"] = {dependency["source_ref"]: ["p0001"]}
    else:
        for source in plan.source_snapshot:
            source.pop("deferred_context_source_refs", None)
            source.pop("deferred_context_quote_ids", None)

    retain_missing_financial_rules(review, plan.source_snapshot)
    recovered = copy.deepcopy(review["financial_items"])
    assert len(recovered) == 2
    assert len(recovered[0]["text"]) > 1600
    assert len(recovered[1]["text"]) <= 1600
    assert [item["text"] for item in recovered] == [
        source["quoted_text"].strip() for source in (first, second)
    ]
    # The short sibling's coverage cannot suppress reconstruction of the long
    # sibling when checking its exception to the generated-prose length limit.
    assert retained_financial_indices(recovered, plan.source_snapshot) == {0}
    if deferred:
        result, _, _ = reconcile_review(
            plan, review, FinancialProvider(long_source=True), "", lambda: None, 100
        )
        assert {
            key
            for key in result["dependency_review"]["base_items"]
            if key.startswith("financial_items:")
        } == {"financial_items:0", "financial_items:1"}
        assert result["financial_items"] == recovered
    else:
        result = review
    validate_source_review(result, plan.source_snapshot)
