import copy

import pytest

from apps.legislation.enhancements.providers.base import ProviderResult, ProviderUsage
from apps.legislation.enhancements.provision_pipeline import (
    BudgetExceeded,
    plan_analysis,
    run_analysis,
)
from apps.legislation.enhancements.source_graph import build_source_graph

from .test_source_first_schema import explanation


def graph():
    return build_source_graph(
        "1",
        "IH",
        "SEC. 1. PAYMENT\nThe Secretary shall pay $100.\nSEC. 2. PAYMENT\nThe Secretary shall pay $100.",
    )


def test_e2e_provider_passes_the_real_source_accounting_gate():
    from types import SimpleNamespace

    from apps.legislation.enhancements.providers.e2e import E2EEnhancementProvider

    g = build_source_graph(
        "1",
        "IH",
        "SEC. 1. GRANTS.\nThe Secretary shall award $100 in grants to rural hospitals.",
    )
    provider = E2EEnhancementProvider()

    def invoke(call):
        request = SimpleNamespace(
            request_envelope={"source_first_payload": call.payload}
        )
        method = (
            provider.generate_synopsis
            if call.stage == "synopsis"
            else provider.generate_provisions
        )
        return method(api_key="e2e-test", request=request, timeout_seconds=5)

    result = run_analysis(plan_analysis(g), invoke, lambda *args: None)
    assert result.completeness == "complete"
    assert not result.findings


def test_initial_generation_never_silently_truncates():
    many = build_source_graph(
        "1", "IH", "\n".join(f"SEC. {i}. PAYMENT\nPay $100." for i in range(1, 34))
    )
    with pytest.raises(BudgetExceeded):
        plan_analysis(many, {})


def test_large_failed_set_repairs_bounded_subset_without_losing_remaining_failures():
    g = build_source_graph(
        "1",
        "IH",
        "\n".join(
            f"SEC. {i}. PAYMENT\nThe Secretary shall pay $100." for i in range(1, 10)
        ),
    )
    calls = []

    def invoke(call):
        calls.append(call)
        if call.stage == "synopsis":
            return {"text": "", "explanation_ids": []}
        rows = [
            explanation(g, i) for i, u in enumerate(g.units) if u.id in call.unit_ids
        ]
        if call.stage == "generation":
            for row in rows:
                row["summary"] = "The Secretary must pay $1,000."
        else:
            assert len(call.unit_ids) <= 8
        return {"provisions": rows}

    plan = plan_analysis(g)
    result = run_analysis(plan, invoke, lambda *args: None)
    assert len([c for c in calls if c.stage == "repair"]) == 1
    assert (
        len([r for r in result.output["provisions"] if r["status"] == "explained"]) == 8
    )
    assert result.output["provisions"][-1]["status"] == "unresolved"
    assert result.completeness == "partial"
    assert result.call_count <= plan.maximum_calls


def test_aggregate_limit_checked_before_dispatch():
    with pytest.raises(BudgetExceeded):
        plan_analysis(graph(), {"max_input": 100})


def test_accepted_units_preserved_and_repair_is_targeted():
    g = graph()
    plan = plan_analysis(g, {})
    accepted = explanation(g)
    failed = explanation(g, 1)
    failed["summary"] = "The Secretary must pay $1,000."
    calls, checkpoints = [], []

    def invoke(call):
        calls.append(call)
        if call.stage == "generation":
            output = {"provisions": [accepted, failed]}
        elif call.stage == "repair":
            assert call.unit_ids == (g.units[1].id,)
            output = {"provisions": [explanation(g, 1)]}
        else:
            output = {
                "text": "The Secretary must pay $100 under each provision.",
                "explanation_ids": [u.id for u in g.units],
            }
        return ProviderResult(
            copy.deepcopy(output), ProviderUsage(10, 10, 20), "resp", "test"
        )

    result = run_analysis(plan, invoke, lambda *args: checkpoints.append(args))
    assert result.output["provisions"][0]["summary"] == accepted["summary"]
    assert result.completeness == "complete"
    assert [c.stage for c in calls] == ["generation", "repair", "synopsis"]
    assert result.call_count <= plan.maximum_calls
    assert len(checkpoints) == 6


def test_repair_cannot_return_an_accepted_id():
    g = graph()
    plan = plan_analysis(g, {})

    def invoke(call):
        if call.stage == "synopsis":
            return {"text": "Payment.", "explanation_ids": [g.units[0].id]}
        rows = [explanation(g), explanation(g, 1)]
        if call.stage == "generation":
            rows[1]["summary"] = "Pay $1,000."
        return {"provisions": rows}

    result = run_analysis(plan, invoke, lambda *args: None)
    assert result.completeness == "partial"
    assert result.output["provisions"][0]["status"] == "explained"
    assert result.output["provisions"][1]["status"] == "unresolved"


def test_zero_failures_skips_repair_and_bad_synopsis_is_withheld():
    g = graph()
    calls = []

    def invoke(call):
        calls.append(call.stage)
        return (
            {"provisions": [explanation(g), explanation(g, 1)]}
            if call.stage == "generation"
            else {"text": "Made up", "explanation_ids": ["other"]}
        )

    result = run_analysis(plan_analysis(g, {}), invoke, lambda *args: None)
    assert calls == ["generation", "synopsis"]
    assert result.output["synopsis"]["status"] == "unavailable"


def test_mutated_graph_cannot_dispatch():
    g = graph()
    plan = plan_analysis(g, {})
    g.passages.clear()
    with pytest.raises(ValueError, match="source_identity"):
        run_analysis(plan, lambda _: pytest.fail("dispatched"), lambda *args: None)


def test_retry_plan_reuses_accepted_rows_without_dispatch_or_recharge():
    g = graph()
    original = run_analysis(
        plan_analysis(g, {}),
        lambda call: (
            {
                "provisions": [
                    explanation(g),
                    {
                        "unit_id": g.units[1].id,
                        "status": "unresolved",
                        "summary": "",
                        "details": [],
                        "claims": [],
                        "unresolved_reason": "needs review",
                    },
                ]
            }
            if call.stage != "synopsis"
            else {
                "text": "The Secretary must pay $100.",
                "explanation_ids": [g.units[0].id],
            }
        ),
        lambda *args: None,
    )
    retry = plan_analysis(g, {}, reuse_result=original.output)
    assert all(g.units[0].id not in c.unit_ids for c in retry.calls)

    def invoke(call):
        if call.stage == "synopsis":
            return {
                "text": "The Secretary must pay $100.",
                "explanation_ids": [g.units[0].id],
            }
        return {"provisions": [explanation(g, 1)]}

    result = run_analysis(retry, invoke, lambda *args: None)
    assert result.completeness == "complete"
    assert result.output["provisions"][0] == original.output["provisions"][0]
    assert result.call_count == 2


def test_conflicting_shared_evidence_is_repaired_before_synopsis():
    g = build_source_graph(
        "1",
        "IH",
        "SEC. 1. PAYMENT\nSubject to section 2 of this Act, the Secretary shall pay $100.\nSEC. 2. PAYMENT\nThe Secretary shall pay $100.",
    )
    rows = [explanation(g, 0), explanation(g, 1)]
    rows[0]["claims"][0]["evidence_ids"] += list(g.units[0].context_passage_ids)
    rows[1]["claims"][0]["modality"] = "prohibited"
    stages = []

    def invoke(call):
        stages.append(call.stage)
        if call.stage == "synopsis":
            pytest.fail("Contradictory merged claims cannot produce a synopsis")
        return {"provisions": copy.deepcopy(rows)}

    result = run_analysis(plan_analysis(g), invoke, lambda *args: None)
    assert stages == ["generation", "repair"]
    assert result.completeness == "partial"
    assert all(row["status"] == "unresolved" for row in result.output["provisions"])
    assert any(f["code"] == "cross_unit_conflict" for f in result.findings)


def test_external_reference_does_not_hide_explicit_rule_but_limits_analysis():
    g = build_source_graph(
        "1",
        "IH",
        "SEC. 1. PAYMENT\nSubject to section 10 of the Other Act, the Secretary shall pay $100.",
    )
    plan = plan_analysis(g)
    assert plan.calls, (
        "Explicit bill rules must not be discarded with unresolved outside-law context"
    )
    row = explanation(g)
    row["summary"] = (
        "The Secretary must pay $100, subject to section 10 of the Other Act."
    )

    def invoke(call):
        return (
            {"provisions": [row]}
            if call.stage != "synopsis"
            else {"text": row["summary"], "explanation_ids": [g.units[0].id]}
        )

    result = run_analysis(plan, invoke, lambda *args: None)
    assert result.output["provisions"][0]["status"] == "explained"
    assert result.output["provisions"][0]["source_limitations"]
    assert result.output["coverage"]["context_limited_unit_ids"] == [g.units[0].id]
    assert result.output["synopsis"]["status"] == "partial"


def test_reference_only_amendment_stays_unresolved():
    g = build_source_graph(
        "1", "IH", "SEC. 1. AMENDMENT\nSection 10 of the Other Act is amended."
    )
    assert not plan_analysis(g).calls


def test_reasoning_and_output_limits_are_bound_to_confirmation():
    g = graph()
    ordinary = plan_analysis(g, {"reasoning_effort": "none", "output_tokens": 8000})
    changed = plan_analysis(g, {"reasoning_effort": "low", "output_tokens": 4000})
    assert ordinary.fingerprint != changed.fingerprint
    assert ordinary.calls[0].request_fingerprint != changed.calls[0].request_fingerprint
    assert changed.maximum_output == changed.maximum_calls * 4000


@pytest.mark.parametrize("failure", ["missing", "unrelated_evidence"])
def test_one_bad_assignment_does_not_discard_other_valid_units(failure):
    g = graph()
    stages = []

    def invoke(call):
        stages.append(call.stage)
        if call.stage == "generation":
            rows = [explanation(g)]
            if failure == "unrelated_evidence":
                bad = explanation(g, 1)
                bad["claims"][0]["evidence_ids"] = list(g.units[0].own_passage_ids)
                rows.append(bad)
            return {"provisions": rows}
        if call.stage == "repair":
            assert call.unit_ids == (g.units[1].id,)
            return {"provisions": [explanation(g, 1)]}
        return {"text": explanation(g)["summary"], "explanation_ids": [g.units[0].id]}

    result = run_analysis(plan_analysis(g), invoke, lambda *args: None)
    assert result.completeness == "complete"
    assert stages == ["generation", "repair", "synopsis"]
