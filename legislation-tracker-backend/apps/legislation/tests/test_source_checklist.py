import copy

import pytest
from jsonschema import ValidationError

from apps.legislation.enhancements.provision_pipeline import plan_analysis, run_analysis
from apps.legislation.enhancements.source_first_transport import prepare_transport
from apps.legislation.enhancements.source_graph import build_source_graph

from .test_source_first_schema import explanation


def sample():
    return build_source_graph(
        "1",
        "IH",
        "SEC. 1. GRANTS\n(a) Awards.--The Secretary shall award grants.\n(b) Uses.--Recipients shall use funds for--\n    (1) tutoring; and\n    (2) emergency financial assistance.\n(c) Amendment.--Strike Attorney General and insert Secretary of Homeland Security.",
    )


def test_payload_accounts_for_every_source_character_without_cutting_off_conditions():
    graph = sample()
    payload = plan_analysis(graph).calls[0].payload
    items = payload["units"][0].get("source_checklist", [])
    assert len(items) == 6
    passage = graph.passages[graph.units[0].own_passage_ids[0]]
    assert (
        "".join(
            passage.text[i["start"] - passage.start : i["end"] - passage.start]
            for i in items
        )
        == passage.text
    )
    assert items[-1]["kinds"] == ["amendment"]
    assert len({i["id"] for i in items}) == 6
    assert all(i["evidence_ids"] == [passage.id] for i in items)


def test_section_response_without_item_accounting_cannot_pass_pipeline():
    graph = build_source_graph(
        "1", "IH", "SEC. 1. PAYMENT\nThe Secretary shall pay $100."
    )
    row = explanation(graph)
    row.pop("coverage_items", None)
    result = run_analysis(
        plan_analysis(graph),
        lambda call: {"provisions": [copy.deepcopy(row)]},
        lambda *args: None,
    )
    assert result.completeness == "partial"
    assert any(f["code"] == "source_checklist_missing" for f in result.findings)


def test_partial_item_accounting_exposes_unresolved_items_in_final_output():
    graph = build_source_graph(
        "1", "IH", "SEC. 1. PAYMENT\nThe Secretary shall pay $100."
    )
    row = explanation(graph)
    row.pop("coverage_items", None)
    result = run_analysis(
        plan_analysis(graph),
        lambda call: {"provisions": [copy.deepcopy(row)]},
        lambda *args: None,
    )
    items = result.output["coverage"].get("source_items", [])
    assert len(items) == 1
    assert items[0]["status"] == "unresolved"
    assert items[0]["start"] == 0
    assert items[0]["end"] == len(graph.source_text)


def test_transport_requires_short_exact_checklist_ids_and_restores_them():
    graph = sample()
    payload = plan_analysis(graph).calls[0].payload
    transport = prepare_transport("generation", payload)
    items = transport.payload["units"][0]["source_checklist"]
    assert [i["id"] for i in items] == [f"s{i}" for i in range(1, 7)]
    row = explanation(graph)
    row["unit_id"] = "u1"
    row["claims"][0]["evidence_ids"] = ["p1"]
    row.pop("coverage_items")
    row.pop("details")
    row["unresolved_items"] = []
    row["claims"][0].update(
        source_item_ids=[i["id"] for i in items],
        explanations=["The Secretary must pay $100."],
    )
    decoded = transport.decode({"provisions": [row]})
    assert (
        decoded["provisions"][0]["coverage_items"][0]["item_id"]
        == payload["units"][0]["source_checklist"][0]["id"]
    )
    assert decoded["provisions"][0]["coverage_items"][0]["claim_indexes"] == [0]
    assert decoded["provisions"][0]["coverage_items"][0]["explanation_indexes"] == [1]
    row["claims"][0]["source_item_ids"][0] = "s999"
    with pytest.raises(ValidationError):
        transport.decode({"provisions": [row]})


def test_generation_batches_reserve_output_space_for_checklist_not_just_input():
    from apps.legislation.evaluation.whole_bill import load_cases

    case = next(c for c in load_cases() if c["id"] == "BILLS-119hr1589ih")
    graph = build_source_graph(case["id"], case["id"], case["text"])
    plan = plan_analysis(graph)
    assert all(
        sum(len(u["source_checklist"]) for u in call.payload["units"]) * 80
        <= plan.output_tokens
        for call in plan.calls
    )


@pytest.mark.parametrize(
    "mutation",
    ["missing", "duplicate", "unknown", "index", "blank_reason", "financial"],
)
def test_accounting_rejects_invalid_mappings(mutation):
    from apps.legislation.enhancements.provision_validation import validate_provision
    from apps.legislation.enhancements.source_checklist import source_checklist

    graph = build_source_graph(
        "1", "IH", "SEC. 1. GRANTS\nThe Secretary shall award grants."
    )
    row = explanation(graph)
    row["summary"] = "The Secretary must award grants."
    row["claims"][0]["action"] = "award grants"
    row["claims"][0]["money"][0]["amount"] = None
    row["coverage_items"] = [
        {
            "item_id": i["id"],
            "status": "explained",
            "claim_indexes": [0],
            "explanation_indexes": [0],
            "reason": None,
        }
        for i in source_checklist(graph.units[0], graph)
    ]
    assert not validate_provision(row, graph.units[0], graph, require_coverage=True)
    if mutation == "missing":
        row["coverage_items"] = []
    if mutation == "duplicate":
        row["coverage_items"] *= 2
    if mutation == "unknown":
        row["coverage_items"][0]["item_id"] = "unknown"
    if mutation == "index":
        row["coverage_items"][0]["explanation_indexes"] = [1]
    if mutation == "blank_reason":
        row["coverage_items"][0].update(
            status="unresolved", reason=" ", claim_indexes=[], explanation_indexes=[]
        )
    if mutation == "financial":
        row["claims"][0]["money"] = []
    assert validate_provision(row, graph.units[0], graph, require_coverage=True)


def test_missing_money_diagnostic_identifies_every_affected_source_block():
    from apps.legislation.enhancements.provision_validation import validate_provision

    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. GRANTS\n(a) The Secretary shall award grants.\n(b) Recipients shall use grant funds for tutoring.",
    )
    row = explanation(graph)
    row["summary"] = "The Secretary awards grants for tutoring."
    row["claims"][0]["money"] = []
    findings = [
        f
        for f in validate_provision(row, graph.units[0], graph, require_coverage=True)
        if f.code == "source_item_money_missing"
    ]
    assert len(findings) == 2
    assert {f.path for f in findings} == {"coverage_items/1", "coverage_items/2"}
    assert all("null amount" in f.message for f in findings)


@pytest.mark.parametrize("field", ["claim_indexes", "explanation_indexes"])
def test_schema_integer_floats_are_rejected_without_crashing(field):
    from apps.legislation.enhancements.provision_validation import validate_provision

    graph = build_source_graph(
        "1", "IH", "SEC. 1. PAYMENT\nThe Secretary shall pay $100."
    )
    row = explanation(graph)
    row["coverage_items"][0][field] = [0.0]
    assert "source_checklist_invalid" in {
        f.code
        for f in validate_provision(row, graph.units[0], graph, require_coverage=True)
    }


def test_many_distinct_rules_can_use_short_separate_sentences():
    from apps.legislation.enhancements.source_first_schema import (
        validate_source_first_schema,
    )

    sentences = [f"The Secretary shall publish report {i}." for i in range(1, 21)]
    graph = build_source_graph("1", "IH", "SEC. 1. REPORTS\n" + "\n".join(sentences))
    row = explanation(graph)
    row["summary"] = "The Secretary must publish twenty reports."
    row["details"] = sentences
    row["claims"][0]["money"] = []
    row["claims"][0]["action"] = "publish twenty reports"
    validate_source_first_schema({"provisions": [row]}, graph)


@pytest.mark.parametrize("missing_item", [False, True])
def test_condition_from_neighboring_rule_cannot_be_attached_to_definition(missing_item):
    from apps.legislation.enhancements.provision_validation import validate_provision

    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. RULES\n(a) Definition.--Student means an enrolled person.\n(b) Payment.--The Secretary shall pay $100 only if the student qualifies.",
    )
    row = explanation(graph)
    row["claims"].append(copy.deepcopy(row["claims"][0]))
    row["claims"][1].update(
        action="define student",
        money=[],
        conditions={
            "operator": "leaf",
            "text": "only if the student qualifies.",
            "evidence_ids": list(graph.units[0].own_passage_ids),
        },
    )
    row["coverage_items"][1]["claim_indexes"] = [1]
    if missing_item:
        row["coverage_items"].pop()
    assert "condition_source_unmapped" in {
        f.code
        for f in validate_provision(row, graph.units[0], graph, require_coverage=True)
    }


@pytest.mark.parametrize(
    "fee_rule",
    [
        "For a qualifying applicant, the Secretary may require payment of a reasonable fee commensurate with processing costs.",
        "The Secretary may require an applicant who meets the requirements for lawful permanent residence without the conditional basis under section 104(c)(2) to pay a fee that is commensurate with the cost of processing the application.",
    ],
)
def test_optional_cost_based_fee_needs_its_own_financial_entry(fee_rule):
    from apps.legislation.enhancements.source_checklist import check_accounting

    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. FEES\n(a) The Secretary may charge a $100 fee.\n(b) " + fee_rule,
    )
    row = explanation(graph)
    row["claims"].append(
        {
            **copy.deepcopy(row["claims"][0]),
            "action": "require a cost-based processing fee",
            "modality": "permitted",
            "money": [],
        }
    )
    row["coverage_items"][-1]["claim_indexes"] = [1]
    assert "source_item_money_missing" in {
        code for code, _, _ in check_accounting(row, graph.units[0], graph)
    }


def test_repeated_condition_can_support_third_source_block():
    from apps.legislation.enhancements.source_checklist import check_accounting

    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. RULES\n(a) Act only if eligible.\n(b) Act only if eligible.\n(c) Act only if eligible.",
    )
    row = explanation(graph)
    row["claims"][0]["money"] = []
    row["claims"].append(copy.deepcopy(row["claims"][0]))
    row["claims"][1]["conditions"] = {
        "operator": "leaf",
        "text": "only if eligible.",
        "evidence_ids": list(graph.units[0].own_passage_ids),
    }
    row["coverage_items"][-1]["claim_indexes"] = [1]
    assert not check_accounting(row, graph.units[0], graph)


def test_provider_receives_exact_block_text_not_only_character_offsets():
    from apps.legislation.enhancements.source_first_transport import prepare_transport

    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. RULES\n(a) Pay $100 only if eligible.\n(b) Publish a report.",
    )
    call = plan_analysis(graph).calls[0]
    wire = prepare_transport("generation", call.payload).payload
    items = wire["units"][0]["source_checklist"]
    assert items[1]["text"] == "(a) Pay $100 only if eligible.\n"
    assert items[2]["text"] == "(b) Publish a report."


def test_condition_block_reference_expands_exact_source_and_disallows_invented_quote():
    from jsonschema import ValidationError

    from apps.legislation.enhancements.source_first_transport import prepare_transport

    graph = build_source_graph("1", "IH", "SEC. 1. RULES\nPay $100 only if eligible.")
    transport = prepare_transport("generation", plan_analysis(graph).calls[0].payload)
    row = explanation(graph)
    row.update(unit_id="u1", unresolved_items=[])
    row.pop("details")
    row.pop("coverage_items")
    claim = row["claims"][0]
    claim.update(
        evidence_ids=["p1"],
        source_item_ids=["s1"],
        explanations=["The Secretary must pay $100 only if eligible."],
        conditions={"operator": "block", "item_id": "s1"},
    )
    decoded = transport.decode({"provisions": [row]})
    assert (
        decoded["provisions"][0]["claims"][0]["conditions"]["text"]
        == "SEC. 1. RULES\nPay $100 only if eligible."
    )
    claim["conditions"] = {
        "operator": "leaf",
        "text": "An invented paraphrase.",
        "evidence_ids": ["p1"],
    }
    with pytest.raises(ValidationError):
        transport.decode({"provisions": [row]})


def test_unassigned_heading_is_context_but_unassigned_operative_text_is_failure():
    from apps.legislation.enhancements.source_checklist import check_accounting

    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. PAYMENT.\n\n(a) Requirements.--\n(1) The Secretary shall pay $100.",
    )
    row = explanation(graph)
    row["coverage_items"] = row["coverage_items"][2:]
    assert not check_accounting(row, graph.units[0], graph)
    row["coverage_items"] = []
    assert (
        check_accounting(row, graph.units[0], graph)[0][0] == "source_checklist_missing"
    )


def test_explicitly_unexplained_structural_heading_does_not_reject_operative_claims():
    from apps.legislation.enhancements.source_checklist import check_accounting

    graph = build_source_graph(
        "1", "IH", "SEC. 1. PAYMENT.\n(a) The Secretary shall pay $100."
    )
    row = explanation(graph)
    row["coverage_items"][0].update(
        status="unresolved",
        claim_indexes=[],
        explanation_indexes=[],
        reason="Heading, not a legal rule.",
    )
    assert not check_accounting(row, graph.units[0], graph)


@pytest.mark.parametrize(
    "duty",
    ["THE SECRETARY SHALL SUBMIT REPORTS.", "DISCLOSURE OF REPORTS IS PROHIBITED."],
)
def test_uppercase_legal_duty_is_not_optional_heading_context(duty):
    from apps.legislation.enhancements.source_checklist import check_accounting

    graph = build_source_graph(
        "1",
        "IH",
        f"SEC. 1. REPORTS\n{duty}\n(a) A court may review a denial.",
    )
    row = explanation(graph)
    row["claims"][0]["money"] = []
    row["coverage_items"] = row["coverage_items"][1:]
    assert (
        check_accounting(row, graph.units[0], graph)[0][0] == "source_checklist_missing"
    )


def test_wire_schema_constrains_each_units_source_items_before_generation():
    from jsonschema import Draft202012Validator

    from apps.legislation.enhancements.source_first_transport import prepare_transport

    graph = build_source_graph(
        "1", "IH", "SEC. 1. RULE\nPay $100.\nSEC. 2. RULE\nPay $200."
    )
    transport = prepare_transport("generation", plan_analysis(graph).calls[0].payload)
    row_schema = transport.schema["properties"]["provisions"]["items"]
    row = {
        "unit_id": "u1",
        "status": "unresolved",
        "summary": "",
        "claims": [],
        "unresolved_reason": "missing context",
        "unresolved_items": [{"item_id": "s2", "reason": "missing context"}],
    }
    assert list(
        Draft202012Validator(
            {**row_schema, "$defs": transport.schema["$defs"]}
        ).iter_errors(row)
    )
    row["unresolved_items"][0]["item_id"] = "s1"
    assert not list(
        Draft202012Validator(
            {**row_schema, "$defs": transport.schema["$defs"]}
        ).iter_errors(row)
    )


@pytest.mark.parametrize("wrong", ["condition", "evidence", "block"])
def test_wire_rejects_other_units_conditions_and_evidence(wrong):
    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. RULE\nPay $100 only if enrolled.\nSEC. 2. RULE\nPay $200 only if employed.",
    )
    transport = prepare_transport("generation", plan_analysis(graph).calls[0].payload)
    row = explanation(graph)
    row.update(unit_id="u1", unresolved_items=[])
    row.pop("details")
    row.pop("coverage_items")
    claim = row["claims"][0]
    claim.update(
        evidence_ids=transport.payload["units"][0]["own_passage_ids"],
        source_item_ids=["s1"],
        explanations=["Pay $100 only if enrolled."],
        conditions={"operator": "source", "condition_id": "c1"},
    )
    other = {
        "unit_id": "u2",
        "status": "unresolved",
        "summary": "",
        "claims": [],
        "unresolved_reason": "test",
        "unresolved_items": [{"item_id": "s2", "reason": "test"}],
    }
    transport.decode({"provisions": [row, other]})
    if wrong == "condition":
        claim["conditions"]["condition_id"] = "c2"
    elif wrong == "evidence":
        claim["evidence_ids"] = transport.payload["units"][1]["own_passage_ids"]
    else:
        claim["conditions"] = {"operator": "block", "item_id": "s2"}
    with pytest.raises(ValidationError):
        transport.decode({"provisions": [row, other]})
