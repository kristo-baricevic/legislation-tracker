import pytest

from apps.legislation.enhancements.provision_validation import validate_provision
from apps.legislation.enhancements.source_graph import build_source_graph

from .test_source_first_schema import explanation


def test_student_percentage_is_not_a_financial_percentage():
    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. DEFINITIONS\nCompletion rate means the percentage of students who graduate.",
    )
    row = explanation(graph)
    row.update(
        summary="Completion rate measures the percentage of students who graduate."
    )
    row["claims"][0].update(
        action="define completion rate", money=[], modality="unspecified"
    )
    assert not validate_provision(row, graph.units[0], graph)


@pytest.mark.parametrize("detail", ["The details are not included in these assigned items.", "The text does not establish the contents of those referenced provisions."])
def test_generation_cannot_invent_source_availability_limitations(detail):
    graph = build_source_graph("1", "IH", "SEC. 1. PAYMENT\nThe Secretary shall pay $100.")
    row = explanation(graph)
    row["details"] = [detail]
    assert any(f.code == "source_availability_claim" and f.path == "explanations/1" for f in validate_provision(row, graph.units[0], graph))


@pytest.mark.parametrize(
    "statistic",
    [
        "the percentage of students who graduate",
        "75 percent of the time the applicant held work authorization",
    ],
)
def test_nonfinancial_percentage_does_not_become_money_because_section_also_has_fee(
    statistic,
):
    graph = build_source_graph(
        "1",
        "IH",
        f"SEC. 1. RULE\nThe Secretary shall pay $100. The report shall measure {statistic}.",
    )
    row = explanation(graph)
    assert "percentage_base_unverified" not in {
        f.code for f in validate_provision(row, graph.units[0], graph)
    }


@pytest.mark.parametrize(
    "year,conflict", [(2026, False), (2030, False), (2036, False), (2037, True)]
)
def test_fiscal_year_range_is_not_a_conflict_when_restated_in_singular(year, conflict):
    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. FUNDING\nThere are authorized to be appropriated such sums as necessary for fiscal years 2026 through 2036.",
    )
    row = explanation(graph)
    row["summary"] = f"Funding is authorized for fiscal year {year}."
    assert (
        "date_conflict"
        in {f.code for f in validate_provision(row, graph.units[0], graph)}
    ) == conflict


def test_short_title_does_not_inherit_unrelated_definition_conditions():
    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. SHORT TITLE\nThis Act may be cited as the Test Act.\nSEC. 2. DEFINITIONS\nEligible person means a person only if enrolled.",
    )
    row = explanation(graph)
    row.update(summary="The short title is Test Act.")
    row["claims"][0].update(action="cite as Test Act", money=[], modality="permitted")
    assert not validate_provision(row, graph.units[0], graph)


def test_external_subject_to_reference_does_not_import_same_number_bill_definition():
    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. PAYMENT\nSubject to section 2 of the Other Act, the Secretary shall pay $100.\nSEC. 2. DEFINITIONS\nEligible student means a person only if enrolled.",
    )
    row = explanation(graph)
    row["summary"] = (
        "The Secretary must pay $100, subject to section 2 of the Other Act."
    )
    assert not validate_provision(row, graph.units[0], graph)


def test_unrelated_outside_reference_does_not_make_internal_qualification_external():
    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. PAYMENT\nSubject to section 2, the Secretary shall pay $100. Section 10 of the Other Act is referenced.\nSEC. 2. RULE\nPayment is limited to enrolled applicants.",
    )
    row = explanation(graph)
    row["summary"] = "The Secretary must pay $100 to enrolled applicants."
    assert "external_qualification_omitted" not in {
        f.code for f in validate_provision(row, graph.units[0], graph)
    }


def test_contents_heading_about_fees_is_not_a_financial_provision():
    graph = build_source_graph(
        "1",
        "IH",
        "SECTION 1. SHORT TITLE; TABLE OF CONTENTS.\n(a) Short Title.--This Act may be cited as the Test Act.\n(b) Table of Contents.--\nSec. 2. Application fees.\nSEC. 2. APPLICATION FEES.\nThe Secretary may charge $100.",
    )
    row = explanation(graph)
    row.update(
        summary="The short title is Test Act; the section also lists the contents."
    )
    row["claims"][0].update(action="cite as Test Act", money=[], modality="permitted")
    assert not validate_provision(row, graph.units[0], graph)


@pytest.mark.parametrize(
    "source,summary,code",
    [
        (
            "The Secretary shall impose a fine of $10,000.",
            "The Secretary must impose a fine of $1,000.",
            "amount_conflict",
        ),
        (
            "A person shall be fined $10,000.",
            "A person may be fined $10,000.",
            "modality_conflict",
        ),
        (
            "The Secretary of Homeland Security shall pay $100.",
            "The Secretary of State must pay $100.",
            "actor_conflict",
        ),
        (
            "The Secretary shall pay not more than $100.",
            "The Secretary must pay at least $100.",
            "comparator_conflict",
        ),
        (
            "The Secretary shall not pay $100.",
            "The Secretary may pay $100.",
            "modality_conflict",
        ),
        (
            "The Secretary shall pay $100 in fiscal year 2027.",
            "The Secretary must pay $100 in fiscal year 2028.",
            "date_conflict",
        ),
        (
            "The Secretary shall pay 10 percent of the grant.",
            "The Secretary must pay 10 percent.",
            "percentage_base_unverified",
        ),
        (
            "The Secretary shall pay $100 only if the applicant is enrolled and employed.",
            "The Secretary must pay $100.",
            "conditions_unverified",
        ),
        (
            "Section 2 of the Other Act is amended.",
            "The rule now covers everyone.",
            "external_context_unresolved",
        ),
    ],
)
def test_bad_claims_are_not_certified(source, summary, code):
    graph = build_source_graph("1", "IH", "SEC. 1. RULE\n" + source)
    row = explanation(graph)
    row["summary"] = summary
    findings = validate_provision(row, graph.units[0], graph)
    assert any(f.code == code for f in findings)


def test_permission_to_seek_review_does_not_weaken_mandatory_fine():
    graph = build_source_graph(
        "1", "IH", "SEC. 1. FINE\nA person shall be fined $100 and may request review."
    )
    row = explanation(graph)
    row["summary"] = "A person must pay the $100 fine and may request review."
    assert not any(
        f.code == "modality_conflict"
        for f in validate_provision(row, graph.units[0], graph)
    )


def test_unknown_source_identity_is_fatal():
    graph = build_source_graph(
        "1", "IH", "SEC. 1. PAYMENT\nThe Secretary shall pay $100."
    )
    row = explanation(graph)
    row["claims"][0]["evidence_ids"] = ["unknown"]
    assert any(
        f.outcome == "fatal" for f in validate_provision(row, graph.units[0], graph)
    )


def test_exact_but_partial_condition_is_not_sufficient():
    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. PAYMENT\nThe Secretary shall pay $100 only if the applicant is enrolled and employed.",
    )
    row = explanation(graph)
    row["claims"][0]["conditions"] = {
        "operator": "leaf",
        "text": "the applicant is enrolled",
        "evidence_ids": list(graph.units[0].own_passage_ids),
    }
    assert any(
        f.code == "condition_scope_unverified"
        for f in validate_provision(row, graph.units[0], graph)
    )
    finding = next(
        f
        for f in validate_provision(row, graph.units[0], graph)
        if f.code == "condition_scope_unverified"
    )
    assert "only if the applicant is enrolled and employed." in finding.message


def test_financial_documentation_does_not_invent_a_fee_or_payment():
    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. DOCUMENTS\nTo establish exemption from application fees, the applicant may submit government income records.",
    )
    row = explanation(graph)
    row["summary"] = (
        "Applicants may submit government income records to establish a fee exemption."
    )
    row["claims"][0].update(
        action="submit government income records", modality="permitted", money=[]
    )
    assert not validate_provision(row, graph.units[0], graph)


def test_explicit_fee_authority_requires_a_financial_entry_even_without_dollar_amount():
    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. FEES\nThe Secretary may charge a reasonable application fee.",
    )
    row = explanation(graph)
    row["summary"] = "The Secretary may charge a reasonable application fee."
    row["claims"][0].update(action="charge a fee", modality="permitted", money=[])
    assert "financial_coverage_unverified" in {
        f.code for f in validate_provision(row, graph.units[0], graph)
    }


def test_omitted_financial_amount_is_unresolved():
    graph = build_source_graph(
        "1", "IH", "SEC. 1. PAYMENT\nThe Secretary shall pay $100 and charge a $25 fee."
    )
    assert any(
        f.code == "financial_coverage_unverified"
        for f in validate_provision(explanation(graph), graph.units[0], graph)
    )


def test_million_is_not_one_dollar():
    graph = build_source_graph(
        "1", "IH", "SEC. 1. PAYMENT\nThe Secretary shall pay $1 million."
    )
    row = explanation(graph)
    row["summary"] = "The Secretary must pay $1."
    row["claims"][0]["money"][0]["amount"] = "1"
    assert any(
        f.code == "amount_conflict"
        for f in validate_provision(row, graph.units[0], graph)
    )


@pytest.mark.parametrize(
    "reference", ["section 2 of this Act", "section 2", "section 2(a)"]
)
def test_governing_reference_cannot_lose_condition(reference):
    graph = build_source_graph(
        "1",
        "IH",
        f"SEC. 1. PAYMENT\nSubject to {reference}, the Secretary shall pay $100.\nSEC. 2. ELIGIBILITY\nPayment is permitted only if the applicant is enrolled and employed.",
    )
    row = explanation(graph)
    assert validate_provision(row, graph.units[0], graph)


def test_governing_subsection_keeps_its_parent_condition_not_unrelated_siblings():
    from apps.legislation.enhancements.provision_validation import required_conditions

    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. PAYMENT\nSubject to section 2(c)(2), the Secretary shall pay $100.\nSEC. 2. RULES\n(a) A court may hear cases only if filed on time.\n(c) These rules apply only if the person is eligible.\n(1) Give notice only if requested.\n(2) Removal is allowed only if based on criminal grounds.\n(d) A refund is due only if a decision is reversed.",
    )
    conditions = " ".join(c["text"] for c in required_conditions(graph.units[0], graph))
    assert "only if the person is eligible" in conditions
    assert "only if based on criminal grounds" in conditions
    assert "filed on time" not in conditions
    assert "notice only if requested" not in conditions
    assert "decision is reversed" not in conditions


def test_non_dollar_authorization_is_not_covered_by_a_payment():
    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. PAYMENT\nThe Secretary shall pay $100.\nThere are authorized to be appropriated such sums as necessary for a separate research program.",
    )
    assert any(
        f.code == "financial_coverage_unverified"
        for f in validate_provision(explanation(graph), graph.units[0], graph)
    )


def test_governing_subsection_retains_explicit_parent_scoped_tail():
    from apps.legislation.enhancements.provision_validation import required_conditions

    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. PAYMENT\nSubject to section 2(c)(1), the Secretary shall pay $100.\nSEC. 2. RULES\n(c) Requirements.\n(1) The Secretary may approve an application.\n(2) The Secretary may issue rules.\nFor purposes of this subsection, an application may be approved only if the applicant is a citizen.",
    )
    assert any(
        "only if the applicant is a citizen" in c["text"]
        for c in required_conditions(graph.units[0], graph)
    )


def test_governing_exception_preserves_actions_not_disconnected_if_fragments():
    from apps.legislation.enhancements.provision_validation import required_conditions

    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. STAY\nSubject to section 2(c)(2), the Secretary shall stay removal.\nSEC. 2. REVIEW\n(c) Stay.\n(1) A person may seek review.\n(2) Exception.--The Secretary may remove a person if based on criminal grounds. The Secretary shall return the person if the decision is reversed.",
    )
    qualifications = required_conditions(graph.units[0], graph)
    referenced = [
        c["text"]
        for c in qualifications
        if c["evidence_ids"] == list(graph.units[1].own_passage_ids)
    ]
    assert len(referenced) == 1
    assert "may remove a person if" in referenced[0]
    assert "shall return the person if" in referenced[0]


def test_days_are_not_financial_entries():
    graph = build_source_graph(
        "1", "IH", "SEC. 1. RULE\nThe applicant may depart for 90 days."
    )
    row = explanation(graph)
    row.update(summary="Applicants may depart for 90 days.")
    row["claims"][0].update(action="depart", modality="permitted")
    row["claims"][0]["money"][0].update(
        amount="90", currency=None, measure="days of a single departure"
    )
    assert any(
        f.code == "nonfinancial_quantity"
        for f in validate_provision(row, graph.units[0], graph)
    )


def test_mandatory_fine_cannot_be_attached_to_prohibited_conduct():
    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. FINE\nA person who knowingly discloses information shall be fined not more than $100.",
    )
    row = explanation(graph)
    row.update(summary="Knowing disclosure carries a fine of up to $100.")
    row["claims"][0].update(action="disclose information", modality="prohibited")
    row["claims"][0]["money"][0].update(measure="fine")
    assert any(
        f.code == "modality_conflict"
        for f in validate_provision(row, graph.units[0], graph)
    )


def test_eligibility_chapeau_is_required_not_just_following_if_tail():
    from apps.legislation.enhancements.provision_validation import required_conditions

    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. ELIGIBILITY\n(a) The Secretary shall approve a student or a caregiver if--\n(1) the person resides in the State; and\n(2) the person is enrolled.",
    )
    assert any(
        "student or a caregiver" in c["text"]
        for c in required_conditions(graph.units[0], graph)
    )


def test_currency_is_not_provider_authority():
    graph = build_source_graph(
        "1", "IH", "SEC. 1. PAYMENT\nThe Secretary shall pay $100."
    )
    row = explanation(graph)
    row["claims"][0]["money"][0]["currency"] = "EUR"
    assert any(
        f.code == "currency_conflict"
        for f in validate_provision(row, graph.units[0], graph)
    )


def test_structured_fine_cannot_disagree_with_mandatory_prose():
    graph = build_source_graph(
        "1", "IH", "SEC. 1. FINE\nThe Secretary shall impose a fine of $100."
    )
    row = explanation(graph)
    row["summary"] = "The Secretary must impose a fine of $100."
    row["claims"][0].update(action="impose a fine", modality="permitted")
    assert any(
        f.code == "modality_conflict"
        for f in validate_provision(row, graph.units[0], graph)
    )


def test_exact_condition_with_display_whitespace_preserves_meaning():
    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. PAYMENT\nThe Secretary shall pay $100 only if the applicant is enrolled\n    and employed.",
    )
    row = explanation(graph)
    row["claims"][0]["conditions"] = {
        "operator": "leaf",
        "text": "only if the applicant is enrolled and employed.",
        "evidence_ids": list(graph.units[0].own_passage_ids),
    }
    assert not validate_provision(row, graph.units[0], graph)


def test_unresolved_external_qualification_cannot_be_turned_into_unconditional_payment():
    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. PAYMENT\nSubject to section 10 of the Other Act, the Secretary shall pay $100.",
    )
    row = explanation(graph)
    assert any(
        f.code == "external_qualification_omitted"
        for f in validate_provision(row, graph.units[0], graph)
    )


def test_distinct_upper_and_lower_bounds_do_not_conflict():
    from apps.legislation.enhancements.provision_validation import validate_provision
    from apps.legislation.enhancements.source_graph import build_source_graph

    from .test_source_first_schema import explanation

    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. RULES\nThe fee is not more than $100. The response period is not less than 90 days.",
    )
    row = explanation(graph)
    row["summary"] = (
        "The fee is capped at $100. Applicants have at least 90 days to respond."
    )
    assert "comparator_conflict" not in {
        f.code for f in validate_provision(row, graph.units[0], graph)
    }
    row["summary"] = "The fee is at least $100."
    assert "comparator_conflict" in {
        f.code for f in validate_provision(row, graph.units[0], graph)
    }


def test_required_condition_does_not_end_inside_us_code_abbreviation():
    from apps.legislation.enhancements.provision_validation import required_conditions
    from apps.legislation.enhancements.source_graph import build_source_graph

    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. RULES\nThe Secretary may pay only if the applicant meets section 101 (8 U.S.C. 1101) and is eligible.",
    )
    assert (
        required_conditions(graph.units[0], graph)[0]["text"]
        == "only if the applicant meets section 101 (8 U.S.C. 1101) and is eligible."
    )


def test_exact_condition_accepts_source_line_wrapping_but_not_changed_words():
    from apps.legislation.enhancements.provision_validation import validate_provision
    from apps.legislation.enhancements.source_graph import build_source_graph

    from .test_source_first_schema import explanation

    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. RULES\nPay $100 only if evidence-\nbased practices are used.",
    )
    row = explanation(graph)
    row["claims"][0]["conditions"] = {
        "operator": "leaf",
        "text": "only if evidence-based practices are used.",
        "evidence_ids": list(graph.units[0].own_passage_ids),
    }
    assert "condition_meaning_unverified" not in {
        f.code for f in validate_provision(row, graph.units[0], graph)
    }
    row["claims"][0]["conditions"]["text"] = (
        "only if evidence-based practices are optional."
    )
    assert "condition_meaning_unverified" in {
        f.code for f in validate_provision(row, graph.units[0], graph)
    }


def test_percentage_in_section_with_dollars_does_not_require_usd_currency():
    from apps.legislation.enhancements.provision_validation import validate_provision
    from apps.legislation.enhancements.source_graph import build_source_graph

    from .test_source_first_schema import explanation

    graph = build_source_graph(
        "1", "IH", "SEC. 1. RULES\nPay $100. Reserve 20 percent of the funds."
    )
    row = explanation(graph)
    row["claims"][0]["money"].append(
        {
            "amount": "20",
            "currency": None,
            "measure": "percent",
            "comparator": None,
            "base": "funds",
            "purpose": "reservation",
            "period": None,
        }
    )
    assert "currency_conflict" not in {
        f.code for f in validate_provision(row, graph.units[0], graph)
    }
    row["claims"][0]["money"][-1]["amount"] = "100"
    assert "currency_conflict" in {
        f.code for f in validate_provision(row, graph.units[0], graph)
    }
