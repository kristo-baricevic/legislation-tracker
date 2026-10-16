import json

import pytest

from apps.legislation.enhancements.provision_pipeline import plan_analysis
from apps.legislation.enhancements.source_graph import build_source_graph
from apps.legislation.evaluation.source_first import preflight_benchmarks, replay


def test_three_pinned_cases_preflight_without_provider():
    report = preflight_benchmarks()
    assert len(report["cases"]) == 3
    assert report["network_calls"] == 0
    assert report["release_gate"] == "blocked"
    for row in report["cases"]:
        assert row["source_sha256"]
        assert row["status"] in {"ready", "budget_exceeded"}
        if row["status"] == "ready":
            assert row["maximum_calls"] <= 6


def test_replay_rejects_identity_drift_before_using_recording():
    graph = build_source_graph("1", "IH", "SEC. 1. TEST\nThe Secretary shall pay $100.")
    plan = plan_analysis(graph, {})
    with pytest.raises(ValueError, match="artifact_identity"):
        replay(plan, {"plan_fingerprint": "wrong", "calls": []})


def test_review_packet_includes_money_conditions_and_only_final_failures():
    from types import SimpleNamespace

    from apps.legislation.evaluation.source_first import review_packet

    case = {
        "expectations": [{"id": "M1", "financial": True}],
        "text_sha256": "source",
        "answer_sha256": "answer",
    }
    row = {
        "id": "u1",
        "unit_id": "u1",
        "status": "explained",
        "summary": "A conditional benefit.",
        "details": ["Only residents qualify."],
        "claims": [
            {
                "actor": "Secretary",
                "action": "pay",
                "modality": "required",
                "money": [{"amount": "10000", "purpose": "student aid"}],
                "conditions": {
                    "operator": "leaf",
                    "text": "enrolled and employed",
                    "evidence_ids": ["p1"],
                },
                "exceptions": [],
                "evidence_ids": ["p1"],
            }
        ],
        "evidence": [{"id": "p1", "text": "source"}],
    }
    result = SimpleNamespace(
        output={
            "provisions": [row],
            "coverage": {
                "unresolved_unit_ids": [],
                "source_items": [{"id": "s1", "status": "mapped_unreviewed"}],
            },
        },
        findings=({"code": "repaired_old_error"},),
    )
    report = review_packet(case, result)
    assert report["output_items"][0]["claims"][0]["money"][0]["amount"] == "10000"
    assert (
        report["output_items"][0]["claims"][0]["conditions"]["text"]
        == "enrolled and employed"
    )
    assert not report["mechanical_failures"]
    assert report["repair_history"] == [{"code": "repaired_old_error"}]
    assert report["source_accounting"] == [{"id": "s1", "status": "mapped_unreviewed"}]
    assert report["dimensions"]["readability"]["statement_count"] == 2
    assert report["dimensions"]["readability"]["max_statement_words"] == 3


def test_fresh_recording_reserves_before_dispatch_and_replays(tmp_path):
    from apps.legislation.evaluation.source_first import execute_recorded

    from .test_source_first_schema import explanation

    graph = build_source_graph(
        "1", "IH", "SEC. 1. PAYMENT\nThe Secretary shall pay $100."
    )
    plan = plan_analysis(graph)
    path = tmp_path / "recording.json"

    def invoke(call):
        saved = json.loads(path.read_text())
        assert saved["calls"][-1]["status"] == "dispatching"
        if call.stage == "synopsis":
            return {
                "text": "The Secretary must pay $100.",
                "explanation_ids": [graph.units[0].id],
            }
        return {"provisions": [explanation(graph)]}

    result = execute_recorded(plan, invoke, path)
    artifact = json.loads(path.read_text())
    assert artifact["status"] == "completed"
    assert artifact["network_calls"] == 2
    assert replay(plan, artifact)["result"]["output"] == result.output
    with pytest.raises(FileExistsError):
        execute_recorded(plan, lambda _: pytest.fail("duplicate charge"), path)


def test_retry_recording_retains_accepted_source_rows_for_offline_replay(tmp_path):
    from apps.legislation.enhancements.source_first_schema import (
        VERSION,
        hydrate_evidence,
    )
    from apps.legislation.evaluation.source_first import execute_recorded

    from .test_source_first_schema import explanation

    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. PAYMENT\nThe Secretary shall pay $100.\nSEC. 2. PAYMENT\nThe Secretary shall pay $100.",
    )
    prior = {
        "schema_version": VERSION,
        "document_fingerprint": graph.document_fingerprint,
        "provisions": [hydrate_evidence(explanation(graph), graph)],
    }
    plan = plan_analysis(graph, reuse_result=prior)
    path = tmp_path / "retry.json"

    def invoke(call):
        if call.stage == "synopsis":
            return {
                "text": "The Secretary must pay $100.",
                "explanation_ids": [graph.units[0].id],
            }
        assert call.unit_ids == (graph.units[1].id,)
        return {"provisions": [explanation(graph, 1)]}

    result = execute_recorded(plan, invoke, path)
    artifact = json.loads(path.read_text())
    rebuilt = plan_analysis(
        graph, artifact["limits"], reuse_result=artifact.get("reuse_result")
    )
    assert rebuilt.fingerprint == plan.fingerprint
    assert replay(rebuilt, artifact)["result"]["output"] == result.output


def test_unknown_call_is_saved_and_not_retried(tmp_path):
    from apps.legislation.enhancements.providers.base import ProviderError
    from apps.legislation.evaluation.source_first import execute_recorded

    graph = build_source_graph(
        "1", "IH", "SEC. 1. PAYMENT\nThe Secretary shall pay $100."
    )
    path = tmp_path / "unknown.json"
    calls = []

    def invoke(call):
        calls.append(call)
        raise ProviderError("outcome_unknown", outcome_unknown=True)

    with pytest.raises(ProviderError):
        execute_recorded(plan_analysis(graph), invoke, path)
    saved = json.loads(path.read_text())
    assert len(calls) == 1
    assert saved["status"] == "failed"
    assert saved["calls"][0]["status"] == "outcome_unknown"
    assert saved["calls"][0]["usage"]["total_tokens"] is None


@pytest.mark.parametrize("use_completed_output", [False, True])
def test_saved_generation_retry_counts_only_actual_provider_calls(
    tmp_path, use_completed_output
):
    from apps.legislation.enhancements.provision_pipeline import digest
    from apps.legislation.evaluation.source_first import execute_recorded

    from .test_source_first_schema import explanation

    graph = build_source_graph(
        "1", "IH", "SEC. 1. PAYMENT\nThe Secretary shall pay $100."
    )
    plan = plan_analysis(graph)
    output = {"provisions": [explanation(graph)]}
    recording = {
        "status": "completed",
        "result": {"output": output},
        "document_fingerprint": graph.document_fingerprint,
        "calls": [
            {
                "stage": "generation",
                "response": output,
                "response_sha256": digest(output),
            }
        ],
    }

    def invoke(call):
        assert call.stage == "synopsis"
        return {
            "text": "The Secretary must pay $100.",
            "explanation_ids": [graph.units[0].id],
        }

    path = tmp_path / "retry.json"
    result = execute_recorded(
        plan,
        invoke,
        path,
        generation_recording=recording,
        use_completed_output=use_completed_output,
    )
    saved = json.loads(path.read_text())
    assert saved["mode"] == (
        "saved_output_live_retry"
        if use_completed_output
        else "saved_generation_live_retry"
    )
    assert saved["network_calls"] == 1
    assert saved["calls"][0]["origin"] == (
        "recorded_output" if use_completed_output else "recorded_generation"
    )
    assert replay(plan, saved)["result"]["output"] == result.output
    recording["calls"][0]["response_sha256"] = "tampered"
    with pytest.raises(ValueError, match="recorded_call_identity"):
        execute_recorded(
            plan,
            invoke,
            tmp_path / "invalid.json",
            generation_recording=recording,
            use_completed_output=use_completed_output,
        )
    assert not (tmp_path / "invalid.json").exists()


def test_execute_command_requires_current_confirmation_before_provider(
    tmp_path, monkeypatch
):
    from django.core.management import call_command
    from django.core.management.base import CommandError
    from django.test import override_settings

    with override_settings(LLM_ENHANCEMENT_EVALUATION_API_KEY="test-key"):
        with pytest.raises(CommandError, match="confirmation"):
            call_command(
                "evaluate_source_first",
                case="BILLS-119hr9300ih",
                execute=True,
                confirm_plan="stale",
                output=tmp_path / "run.json",
            )
    assert not (tmp_path / "run.json").exists()
