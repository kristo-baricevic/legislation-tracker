"""Real provider failures, not idealized model responses."""

import json
from pathlib import Path

import pytest

from apps.legislation.enhancements.provision_pipeline import plan_analysis
from apps.legislation.enhancements.provision_validation import validate_provision
from apps.legislation.enhancements.source_graph import build_source_graph
from apps.legislation.evaluation.whole_bill import load_cases


def recorded_grants():
    case = next(c for c in load_cases() if c["id"] == "BILLS-119hr9300ih")
    graph = build_source_graph(case["id"], case["id"], case["text"])
    path = (
        Path(__file__).resolve().parents[4]
        / "docs/benchmarks/bill-understanding/source-first-live-20261016-190216-BILLS-119hr9300ih.json"
    )
    artifact = json.loads(path.read_text())
    return graph, artifact["calls"][1]["response"]["provisions"]


def test_real_definition_response_does_not_require_money_for_completion_rate():
    graph, rows = recorded_grants()
    row = rows[2]
    unit = next(u for u in graph.units if u.id == row["unit_id"])
    assert not validate_provision(row, unit, graph)


def test_real_campus_restriction_is_in_generation_checklist_and_still_rejected_when_lost():
    graph, rows = recorded_grants()
    row = rows[-1]
    unit = next(u for u in graph.units if u.id == row["unit_id"])
    assert "condition_scope_unverified" in {
        f.code for f in validate_provision(row, unit, graph)
    }
    plan = plan_analysis(graph)
    sent_unit = next(
        u for call in plan.calls for u in call.payload["units"] if u["id"] == unit.id
    )
    assert any(
        "only receive a grant" in item["text"]
        for item in sent_unit["required_conditions"]
    )


def test_real_cut_off_grant_explanation_is_not_accepted_as_readable():
    case = next(c for c in load_cases() if c["id"] == "BILLS-119hr9300ih")
    graph = build_source_graph(case["id"], case["id"], case["text"])
    path = (
        Path(__file__).resolve().parents[4]
        / "docs/benchmarks/bill-understanding/source-first-live-20261016-193226-BILLS-119hr9300ih.json"
    )
    rows = json.loads(path.read_text())["calls"][0]["response"]["provisions"]
    row = rows[-1]
    assert any(text.endswith("recruiting and ret a") for text in row["details"])
    assert "reader_prose_incomplete" in {
        f.code for f in validate_provision(row, graph.units[-1], graph)
    }


@pytest.mark.parametrize(
    "section,code",
    [
        ("102", "condition_scope_unverified"),
        ("304", "nonfinancial_quantity"),
        ("309", "modality_conflict"),
    ],
)
def test_real_previously_accepted_immigration_errors_are_rejected(section, code):
    case = next(c for c in load_cases() if c["id"] == "BILLS-119hr1589ih")
    graph = build_source_graph(case["id"], case["id"], case["text"])
    path = (
        Path(__file__).resolve().parents[4]
        / "docs/benchmarks/bill-understanding/claim-repair-v14-low-20261016-210108-BILLS-119hr1589ih.json"
    )
    saved = json.loads(path.read_text())["result"]["output"]["provisions"]
    row = next(
        p
        for p in saved
        if p["evidence"][0]["section_label"].startswith(f"Sec. {section} ·")
    )
    row = {
        k: v
        for k, v in row.items()
        if k not in {"id", "evidence", "source_limitations"}
    }
    unit = next(u for u in graph.units if u.id == row["unit_id"])
    assert code in {
        f.code for f in validate_provision(row, unit, graph, require_coverage=True)
    }
