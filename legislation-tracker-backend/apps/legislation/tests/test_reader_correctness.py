"""Hand-authored oracles and deliberately wrong outputs test the evaluator itself."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from apps.legislation.evaluation.reader_quality import ai_items, nlp_items, score_reader
from apps.legislation.tests.test_reader_synopsis import extract

SOURCE = "If approved, applicants shall pay a fee of $100 for fiscal year 2027."


@pytest.mark.parametrize(
    "replacement",
    [
        "Applicants must pay a fee of $900.",
        "The Secretary may waive the requirement.",
        "",
    ],
)
def test_source_fallback_display_must_preserve_the_linked_source(replacement):
    case = json.loads(
        (
            Path(__file__).parent / "fixtures/reader_evals/synthetic-active-waiver.json"
        ).read_text()
    )
    result = extract(case["text"])
    items = nlp_items(
        result.contract_json, evidence=result.evidence, source_text=case["text"]
    )
    assert score_reader(case, items, pipeline="nlp")["passed"]
    items[0]["text"] = "Source text (not simplified): " + replacement
    assert not score_reader(case, items, pipeline="nlp")["passed"]


@pytest.mark.parametrize(
    "replacement",
    [
        "Not later than May 1, 2028, the Secretary shall require applicants to pay a fee of $100.",
        "Prohibits applicants from paying a fee of $100 by May 1, 2028.",
        "Prohibits Not later than May 1, 2029, the Secretary from requiring applicants to pay a fee of $100.",
    ],
)
def test_calendar_prohibition_rejects_polarity_actor_and_deadline_corruption(
    replacement,
):
    case = json.loads(
        (
            Path(__file__).parent
            / "fixtures/reader_evals/synthetic-calendar-prohibition.json"
        ).read_text()
    )
    result = extract(case["text"])
    items = nlp_items(
        result.contract_json, evidence=result.evidence, source_text=case["text"]
    )
    assert score_reader(case, items, pipeline="nlp")["passed"]
    items[0]["text"] = replacement
    assert not score_reader(case, items, pipeline="nlp")["passed"]


def test_unannotated_source_fallback_still_cannot_fabricate_display():
    item = {
        "category": "line_item",
        "text": "Source text (not simplified): A fee of $900 is required.",
        "evidence_quotes": [SOURCE],
        "evidence_valid": True,
    }
    report = score_reader({}, [item], pipeline="nlp")
    assert not report["passed"]
    assert report["dimensions"]["correctness"]["status"] == "fail"
    assert report["dimensions"]["abstention"]["status"] == "fail"


@pytest.mark.parametrize("long", [False, True])
def test_complete_and_explicitly_truncated_source_previews_remain_valid(long):
    source = SOURCE if not long else SOURCE + " Additional conditions apply." * 180
    display = "Source text (not simplified): " + source
    if long:
        display = display[:3900] + "… Open the source for the complete wording."
    case = {
        "text": source,
        "correctness": {
            "nlp": {"facts": [], "source_only": [{"id": "complete", "quote": source}]}
        },
    }
    item = {
        "category": "line_item",
        "text": display,
        "evidence_quotes": [source],
        "evidence_valid": True,
    }
    assert score_reader(case, [item], pipeline="nlp")["passed"]
    item["text"] += " No fee is required."
    assert not score_reader(case, [item], pipeline="nlp")["passed"]


def annotated_case():
    return {
        "text": SOURCE,
        "correctness": {
            "nlp": {
                "facts": [
                    {
                        "id": "conditional-fee",
                        "category": "financial",
                        "fields": {
                            "financial_action": "fee",
                            "amount": "100.00",
                            "currency": "USD",
                            "amount_type": "specified",
                            "fiscal_years": [2027],
                        },
                        "patterns": [r"If approved", r"\$100\b"],
                        "forbidden_patterns": [r"unconditionally"],
                        "evidence_contains": [SOURCE],
                    }
                ],
                "closed_categories": ["financial"],
            }
        },
    }


def correct_item():
    return {
        "category": "financial",
        "text": SOURCE,
        "financial_action": "fee",
        "amount": "100.00",
        "currency": "USD",
        "amount_type": "specified",
        "fiscal_years": [2027],
        "evidence_quotes": [SOURCE],
        "evidence_valid": True,
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount", "0.00"),
        ("currency", None),
        ("amount_type", "percentage"),
        ("financial_action", "appropriation"),
        ("fiscal_years", [2028]),
        ("fiscal_years", [2027, 2028]),
        ("text", "Applicants shall pay a fee of $100."),
        ("text", SOURCE + " This applies unconditionally."),
        ("evidence_quotes", ["Applicants shall pay a fee of $100."]),
        ("evidence_valid", False),
    ],
)
def test_field_condition_and_evidence_corruption_cannot_pass(field, value):
    case, item = annotated_case(), correct_item()
    assert score_reader(case, [item], pipeline="nlp")["passed"]
    item[field] = value
    report = score_reader(case, [item], pipeline="nlp")
    assert not report["passed"], (field, report)


def test_missing_extra_and_reused_items_fail_separately():
    case, item = annotated_case(), correct_item()
    report = score_reader(case, [], pipeline="nlp")
    assert not report["passed"]
    assert report["correctness"]["missing_fact_ids"] == ["conditional-fee"]
    extra = {**item, "amount": "50.00", "text": "An additional fee is $50."}
    assert not score_reader(case, [item, extra], pipeline="nlp")["passed"]
    case["correctness"]["nlp"]["facts"].append(
        {
            **case["correctness"]["nlp"]["facts"][0],
            "id": "second-fee",
        }
    )
    assert not score_reader(case, [item], pipeline="nlp")["passed"]


def test_matching_does_not_greedily_consume_the_only_specific_candidate():
    case = {
        "correctness": {
            "nlp": {
                "facts": [
                    {
                        "id": "either",
                        "category": "financial",
                        "fields": {"financial_action": "fee"},
                    },
                    {
                        "id": "specific",
                        "category": "financial",
                        "fields": {"amount": "100.00"},
                    },
                ]
            }
        }
    }
    items = [correct_item(), {**correct_item(), "amount": "50.00", "text": "Fee: $50."}]
    report = score_reader(case, items, pipeline="nlp")
    assert report["passed"]
    assert report["correctness"]["matched_fact_count"] == 2


def test_unannotated_correctness_is_unknown_not_perfect():
    report = score_reader({}, [{"text": "A readable sentence."}], pipeline="nlp")
    assert (
        report.get("dimensions", {}).get("correctness", {}).get("status")
        == "not_evaluated"
    )


def test_complete_source_only_is_not_counted_as_a_successful_simplification():
    case = {
        "text": SOURCE,
        "correctness": {
            "nlp": {
                "facts": [],
                "source_only": [{"id": "uncertain", "quote": SOURCE}],
                "closed_categories": ["financial"],
            }
        },
    }
    item = {
        "category": "line_item",
        "text": "Source text (not simplified): " + SOURCE,
        "evidence_quotes": [SOURCE],
        "evidence_valid": True,
    }
    report = score_reader(case, [item], pipeline="nlp")
    assert report["passed"]
    assert report.get("dimensions", {}).get("abstention", {}).get("status") == "pass"
    assert report["correctness"]["fact_recall"] is None
    for change in (
        {"evidence_quotes": ["applicants shall pay a fee of $100"]},
        {"text": "Applicants must pay $100."},
    ):
        assert not score_reader(case, [{**item, **change}], pipeline="nlp")["passed"]
    assert not score_reader(case, [item, correct_item()], pipeline="nlp")["passed"]


def test_source_only_cannot_satisfy_a_required_explanation():
    item = correct_item()
    item["text"] = "Source text (not simplified): " + SOURCE
    assert not score_reader(annotated_case(), [item], pipeline="nlp")["passed"]


def test_same_evidence_text_is_not_a_duplicate_when_financial_facts_differ():
    first, second = correct_item(), {**correct_item(), "amount": "50.00"}
    assert score_reader({}, [first, second], pipeline="nlp")["passed"]
    assert not score_reader({}, [first, deepcopy(first)], pipeline="nlp")["passed"]


def test_nlp_projection_retains_structured_values_for_evaluation():
    contract = {
        "financial_items": [
            {
                "display_text": SOURCE,
                "amount": "100.00",
                "financial_action": "fee",
                "fiscal_years": [2027],
            }
        ]
    }
    item = nlp_items(contract)[0]
    assert item.get("amount") == "100.00"
    assert item.get("fiscal_years") == [2027]


@pytest.mark.parametrize(
    "annotation",
    [
        {"facts": [{"id": "empty", "category": "financial"}]},
        {"facts": [{"id": "bad-regex", "category": "financial", "patterns": ["["]}]},
        {"factz": []},
        {"facts": [], "source_only": [{"id": "empty-source", "quote": "   "}]},
    ],
)
def test_invalid_or_empty_oracles_fail_closed(annotation):
    report = score_reader(
        {"correctness": {"nlp": annotation}}, [correct_item()], pipeline="nlp"
    )
    assert not report["passed"]
    assert "invalid_correctness_annotation" in report["failures"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("actor", "employers"),
        ("modality", "permitted"),
        ("conditions", []),
        ("kind", "permission"),
    ],
)
def test_actor_modality_and_conditions_are_checked_in_real_output(field, value):
    text = "SEC. 1. Fees\n" + SOURCE
    result = extract(text)
    case = {
        "text": text,
        "correctness": {
            "nlp": {
                "facts": [
                    {
                        "id": "duty",
                        "category": "line_item",
                        "fields": {
                            "actor": "applicants",
                            "modality": "required",
                            "kind": "requirement",
                            "conditions": ["If approved"],
                        },
                        "patterns": ["Requires applicants", "If approved"],
                        "evidence_contains": [SOURCE],
                    }
                ]
            }
        },
    }
    items = nlp_items(result.contract_json, evidence=result.evidence, source_text=text)
    assert score_reader(case, items, pipeline="nlp")["passed"]
    duty = next(i for i in items if i.get("kind") == "requirement")
    duty[field] = value
    assert not score_reader(case, items, pipeline="nlp")["passed"]


def test_broken_item_evidence_link_cannot_hide_behind_other_valid_evidence():
    text = "SEC. 1. Fees\n" + SOURCE
    result = extract(text)
    contract = deepcopy(result.contract_json)
    contract["financial_items"][0]["evidence_paths"].append("missing.path")
    report = score_reader(
        {},
        nlp_items(contract, evidence=result.evidence, source_text=text),
        pipeline="nlp",
    )
    assert not report["passed"]
    assert "invalid_item_evidence" in report["failures"]


def test_ai_replay_checks_same_item_conditions_and_actual_quote_not_any_source():
    case = {
        "text": SOURCE,
        "correctness": {
            "ai": {
                "facts": [
                    {
                        "id": "fee",
                        "category": "financial",
                        "patterns": [r"\$100", "If approved"],
                        "evidence_contains": [SOURCE],
                    }
                ]
            }
        },
    }
    output = {
        "funding_and_timing": [
            {
                "kind": "funding",
                "text": SOURCE,
                "source_refs": ["s1"],
                "source_quotes": [{"source_ref": "s1", "quote": SOURCE}],
            }
        ]
    }
    sources = [{"source_ref": "s1", "quoted_text": SOURCE}]
    assert score_reader(case, ai_items(output), sources=sources, pipeline="ai")[
        "passed"
    ]
    output["funding_and_timing"][0]["source_quotes"][0]["quote"] = (
        "applicants shall pay"
    )
    assert not score_reader(case, ai_items(output), sources=sources, pipeline="ai")[
        "passed"
    ]


def test_synopsis_display_cannot_disagree_with_evaluated_purpose_line():
    result = extract("SEC. 1. Fees\n" + SOURCE)
    contract = deepcopy(result.contract_json)
    contract["orientation"]["purpose_clause"] = "The bill requires no fees."
    report = score_reader({}, nlp_items(contract), pipeline="nlp")
    assert not report["passed"]
    assert "inconsistent_synopsis" in report["failures"]


@pytest.mark.parametrize("separator", [" ", "\n"])
@pytest.mark.parametrize("connector", ["and", "or", "but"])
@pytest.mark.parametrize("condition", ["If approved", "Unless denied"])
@pytest.mark.parametrize("reverse", [False, True])
def test_combined_scope_variants_against_fixed_factual_oracles(
    separator, connector, condition, reverse
):
    case = json.loads(
        (
            Path(__file__).parent / "fixtures/reader_evals/synthetic-payment-scope.json"
        ).read_text()
    )
    clauses = [
        "applicants shall pay a fee of $100 for fiscal year 2027",
        "renewing applicants shall pay a fee of $50 for fiscal year 2028",
    ]
    if reverse:
        clauses.reverse()
    sentence = (condition + ", " + f" {connector} ".join(clauses) + ".").replace(
        " ", separator
    )
    case["text"] = "SEC. 1. Fees\n" + sentence
    for fact in case["correctness"]["nlp"]["facts"]:
        fact["patterns"] = [
            p.replace("If approved", condition.replace(" ", r"\s+"))
            for p in fact.get("patterns", [])
        ]
        if "conditions" in fact.get("fields", {}):
            fact["fields"]["conditions"] = [condition]
        if "evidence_contains" in fact:
            fact["evidence_contains"] = [sentence]
    result = extract(case["text"])
    report = score_reader(
        case,
        nlp_items(
            result.contract_json, evidence=result.evidence, source_text=case["text"]
        ),
        pipeline="nlp",
    )
    assert report["passed"], report


def test_correctness_suite_runs_offline_and_writes_separate_dimensions(tmp_path):
    from django.core.management import call_command

    output = tmp_path / "correctness.json"
    call_command("evaluate_reader_quality", suite="correctness", output=str(output))
    artifact = json.loads(output.read_text())
    assert len(artifact["results"]) >= 5
    assert all(r["quality"]["passed"] for r in artifact["results"])
    assert all("dimensions" in r["quality"] for r in artifact["results"])
    assert artifact["evaluator_version"] == "reader-correctness-2"


def test_command_records_structured_failure_before_nonzero_exit(tmp_path, monkeypatch):
    from django.core.management import call_command
    from django.core.management.base import CommandError

    from apps.legislation.management.commands import evaluate_reader_quality as command

    real_extract = command.extract_contract

    def corrupt(**kwargs):
        result = real_extract(**kwargs)
        result.contract_json["financial_items"][0]["fiscal_years"] = [2030]
        return result

    monkeypatch.setattr(command, "extract_contract", corrupt)
    output = tmp_path / "failed.json"
    with pytest.raises(CommandError, match="failed"):
        call_command(
            "evaluate_reader_quality",
            cases=["synthetic-payment-scope"],
            output=str(output),
        )
    quality = json.loads(output.read_text())["results"][0]["quality"]
    assert quality["correctness"]["missing_fact_ids"] == ["initial-fee"]
    assert quality["dimensions"]["correctness"]["status"] == "fail"
    assert quality["dimensions"]["readability"]["status"] == "pass"


def test_oracle_does_not_allow_misspelled_closed_category_to_skip_checks():
    case = {"correctness": {"nlp": {"facts": [], "closed_categories": ["finanical"]}}}
    assert not score_reader(case, [correct_item()], pipeline="nlp")["passed"]


def test_empty_oracle_does_not_claim_correctness_was_evaluated():
    assert not score_reader(
        {"correctness": {"nlp": {"facts": []}}}, [], pipeline="nlp"
    )["passed"]


def test_real_percentage_basis_and_qualifier_mutations_are_caught():
    from apps.legislation.tests.test_reader_quality import extract_fixture

    case, result = extract_fixture()
    items = nlp_items(
        result.contract_json, evidence=result.evidence, source_text=case["text"]
    )
    assert score_reader(case, items, pipeline="nlp")["passed"]
    for field, value in [
        ("currency", "USD"),
        ("amount", "2000.00"),
        ("text", "Sets aside 20 percent for evidence-based grants."),
    ]:
        changed = deepcopy(items)
        next(i for i in changed if i.get("amount") == "20.00")[field] = value
        assert not score_reader(case, changed, pipeline="nlp")["passed"]


@pytest.mark.parametrize("category", ["financial", "line_item"])
def test_displayed_year_cannot_disagree_with_correct_structured_year(category):
    case = json.loads(
        (
            Path(__file__).parent / "fixtures/reader_evals/synthetic-payment-scope.json"
        ).read_text()
    )
    result = extract(case["text"])
    items = nlp_items(
        result.contract_json, evidence=result.evidence, source_text=case["text"]
    )
    assert score_reader(case, items, pipeline="nlp")["passed"]
    item = next(i for i in items if i["category"] == category and "$100" in i["text"])
    item["text"] = item["text"].replace("2027", "2030")
    assert not score_reader(case, items, pipeline="nlp")["passed"]
