"""Frozen acceptance cases: outputs are hand-specified, not parser-derived.

Changing a supported assertion into silence must fail just as inventing one does.
Uncertain clauses must remain visible as source text, with exact evidence.
"""

import pytest

from apps.legislation.tests.test_reader_synopsis import extract


@pytest.mark.parametrize("separator", [" ", "\n"])
@pytest.mark.parametrize("prefix", ["", "Not later than 180 days after enactment, "])
def test_scope_variants_retain_prohibition_and_valid_adjacent_fee(separator, prefix):
    text = (
        prefix
        + "No Federal agency shall require applicants to pay a fee of $100. Applicants shall pay a fee of $25 whether or not the application is approved."
    )
    c = extract("SEC. 1. Fees\n" + text.replace(" ", separator)).contract_json
    assert [(i["financial_action"], i["amount"]) for i in c["financial_items"]] == [
        ("fee", "25.00")
    ]


def test_nested_uncertain_source_is_grouped_without_duplicate_fragments():
    text = "The Secretary shall review the program which provides that applicants shall pay—\n(1) a fee of $100; and\n(2) a fee of $50."
    c = extract("SEC. 1. Fees\n" + text).contract_json
    assert c["financial_items"] == []
    lines = [
        i
        for i in c["line_items"]
        if i["display_text"].startswith("Source text (not simplified):")
    ]
    assert len(lines) == 1
    assert "$100" in lines[0]["display_text"] and "$50" in lines[0]["display_text"]


def test_evaluation_reports_abstention_separately_from_simplification():
    from apps.legislation.evaluation.reader_quality import nlp_items, score_reader

    c = extract(
        "SEC. 1. Fees\nApplicants who may not renew their permits shall pay a fee of $100."
    ).contract_json
    metrics = score_reader({}, nlp_items(c), pipeline="nlp")["metrics"]
    assert metrics["source_only_item_count"] == 1
    assert metrics["source_only_item_fraction"] == 1.0


def test_discussed_exception_does_not_become_an_actual_fee():
    c = extract(
        "SEC. 1. Reports\nThe Secretary shall report whether applicants shall be exempt from fees, except that applicants shall pay a fee of $100."
    ).contract_json
    assert c["financial_items"] == []
    assert c["orientation"]["purpose_clause"] is None


@pytest.mark.parametrize(
    "subject",
    ["No Federal agency", "No applicants", "Neither the Secretary nor an agency"],
)
def test_prohibited_fee_never_becomes_a_payable_fee(subject):
    result = extract(
        f"SEC. 1. Fees\n{subject} shall require applicants to pay a fee of $100."
    )
    assert result.contract_json["financial_items"] == []
    assert result.contract_json["orientation"]["purpose_clause"] is None
    assert not any(
        i["kind"] == "requirement" for i in result.contract_json["line_items"]
    )
    assert any(subject in i["display_text"] for i in result.contract_json["line_items"])


@pytest.mark.parametrize(
    "ending",
    [
        "whether or not the application is approved",
        "regardless of whether the application is approved",
    ],
)
def test_unconditional_fee_survives_approval_condition(ending):
    c = extract(
        f"SEC. 1. Fees\nApplicants shall pay a fee of $100 {ending}."
    ).contract_json
    assert [(i["financial_action"], i["amount"]) for i in c["financial_items"]] == [
        ("fee", "100.00")
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Applicants who may not renew their permits shall pay a fee of $100.",
        "The Secretary shall review the program under section 3, which provides that the Secretary shall establish a program to award grants to eligible nonprofit organizations to assist eligible applicants.",
        "The Secretary shall report whether a fee is necessary, and applicants shall pay a fee of $100.",
    ],
)
def test_uncertain_scope_is_visible_source_not_a_simplified_claim(text):
    result = extract("SEC. 1. Requirements\n" + text)
    c = result.contract_json
    assert c["orientation"]["purpose_clause"] is None
    assert c["financial_items"] == []
    lines = [
        i
        for i in c["line_items"]
        if i["display_text"].startswith("Source text (not simplified):")
    ]
    assert len(lines) == 1
    assert text in lines[0]["display_text"]
    assert any(e.quoted_text == text for e in result.evidence)
    assert "reader_uncertain_clause" in c["extraction"]["warnings"]


@pytest.mark.parametrize("conjunction", ["and", "but"])
def test_shared_subject_fee_and_exemption_both_survive(conjunction):
    c = extract(
        f"SEC. 1. Fees\nApplicants shall pay a fee of $100 {conjunction} may be exempted from paying the fee if they are minors."
    ).contract_json
    assert {(i["financial_action"], i["amount"]) for i in c["financial_items"]} == {
        ("fee", "100.00"),
        ("fee_exemption", None),
    }


@pytest.mark.parametrize("wrap", [" ", "\n"])
def test_qualified_fee_schedule_keeps_categories_and_each_amount(wrap):
    c = extract(
        "SEC. 1. Fees\nThe Secretary shall require a fee of—\n(1) not more than"
        + wrap
        + "$100 for an application; and\n(2) not less than"
        + wrap
        + "$50 for renewal."
    ).contract_json
    assert [
        (i["financial_action"], i["amount"], i["amount_type"])
        for i in c["financial_items"]
    ] == [("fee", "100.00", "ceiling"), ("fee", "50.00", "specified")]
    assert "not less than" in c["financial_items"][1]["display_text"]
    assert "funding limits" not in c["orientation"]["purpose_clause"]
