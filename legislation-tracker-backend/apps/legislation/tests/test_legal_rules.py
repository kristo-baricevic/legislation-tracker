from apps.legislation.extraction.federal_structure import parse_federal_structure
from apps.legislation.extraction.legal_rules import (
    extract_amendment_claims,
    extract_applicability_claims,
    extract_claims,
    extract_definition_claims,
    extract_funding_claims,
    extract_modality_claims,
    extract_timeline_claims,
    normalize_usd_amount,
)


def assert_exact_evidence(source, claims):
    for claim in claims:
        assert len(claim.evidence) == 1
        evidence = claim.evidence[0]
        assert source[evidence.start_char : evidence.end_char] == evidence.text


def test_extract_modality_claims_maps_supported_phrases_and_conditions():
    source = """SEC. 2. DUTIES
The Secretary shall publish a report.
The Administrator must review applications.
The Director is required to notify Congress.
The Secretary shall not disclose patient records.
The Administrator may not approve incomplete applications.
The Director is prohibited from releasing private data.
The Secretary may establish an advisory committee.
The Administrator is authorized to award grants, subject to available funds.
"""

    claims = extract_modality_claims(source, parse_federal_structure(source))

    assert [claim.fields["modality"] for claim in claims] == [
        "required",
        "required",
        "required",
        "prohibited",
        "prohibited",
        "prohibited",
        "permitted",
        "permitted",
    ]
    assert claims[0].fields == {
        "modality": "required",
        "actor": "The Secretary",
        "action": "publish a report",
        "object": None,
        "conditions": [],
    }
    assert claims[-1].fields["conditions"] == ["subject to available funds"]
    assert claims[-1].fields["action"] == "award grants"
    assert claims[0].rule_id == "modality.shall.v1"
    assert_exact_evidence(source, claims)


def test_extract_definitions_requires_explicit_syntax_or_definition_context():
    source = '''SEC. 3. DEFINITIONS
The term "covered entity" means a rural hospital.
“Covered service” includes hospital care and emergency transport.
SEC. 4. FINDINGS
Coverage means access to insurance.
'''

    claims = extract_definition_claims(source, parse_federal_structure(source))

    assert [claim.fields for claim in claims] == [
        {
            "term": "covered entity",
            "definition": "a rural hospital",
            "definition_type": "means",
        },
        {
            "term": "Covered service",
            "definition": "hospital care and emergency transport",
            "definition_type": "includes",
        },
    ]
    assert [claim.rule_id for claim in claims] == [
        "definition.term_means.v1",
        "definition.section_includes.v1",
    ]
    assert_exact_evidence(source, claims)


def test_extract_applicability_claims_uses_only_explicit_relationships():
    source = """SEC. 5. APPLICABILITY AND ELIGIBILITY
The program applies to rural hospitals.
The program does not apply to private insurers.
An eligible entity is a rural hospital or health clinic.
The program excludes for-profit hospitals.
"""

    claims = extract_applicability_claims(source, parse_federal_structure(source))

    assert [claim.fields for claim in claims] == [
        {
            "subject": "The program",
            "scope": "rural hospitals",
            "applicability_type": "applies",
        },
        {
            "subject": "The program",
            "scope": "private insurers",
            "applicability_type": "does_not_apply",
        },
        {
            "subject": "eligible entity",
            "scope": "a rural hospital or health clinic",
            "applicability_type": "eligible",
        },
        {
            "subject": "The program",
            "scope": "for-profit hospitals",
            "applicability_type": "excluded",
        },
    ]
    assert_exact_evidence(source, claims)


def test_extract_claims_filters_nonoperative_and_quoted_modal_language():
    source = '''SEC. 1. TABLE OF CONTENTS
Sec. 4. The Secretary shall report
SEC. 2. DEFINITIONS
The term "requirement" means a rule that shall apply to covered entities.
SEC. 3. AMENDMENT
Strike “the Secretary shall publish”.
SEC. 4. DISCUSSION
The report may discuss whether the agency should act.
A notice states “the agency may waive a rule”.
SEC. 5. DUTY
The Secretary shall publish a current report.
'''

    claims = extract_claims(source, parse_federal_structure(source))
    modality_claims = [claim for claim in claims if claim.category == "requirements"]

    assert len(modality_claims) == 1
    assert modality_claims[0].fields["actor"] == "The Secretary"
    assert modality_claims[0].fields["action"] == "publish a current report"
    assert_exact_evidence(source, claims)


def test_nested_subdivision_claim_is_emitted_once_with_full_sentence_evidence():
    source = """SEC. 6. REPORTS
(a) IN GENERAL.—The Secretary shall publish a report.
(1) CONTENTS.—The report shall describe program outcomes.
"""

    claims = extract_modality_claims(source, parse_federal_structure(source))

    assert [claim.fields["actor"] for claim in claims] == [
        "The Secretary",
        "The report",
    ]
    assert [claim.section_label for claim in claims] == ["(a)", "(1)"]
    assert_exact_evidence(source, claims)


def test_normalize_usd_amount_uses_decimal_scaling():
    assert normalize_usd_amount("$25,000,000") == "25000000.00"
    assert normalize_usd_amount("$1.5 million") == "1500000.00"
    assert normalize_usd_amount("2 billion dollars") == "2000000000.00"


def test_extract_funding_claims_distinguishes_amounts_and_authority():
    source = """SEC. 7. FUNDING
There is authorized to be appropriated $25,000,000 for fiscal year 2027 to carry out this Act.
There are appropriated $1.5 million for fiscal years 2027 through 2029 for rural grants.
There are authorized to be appropriated such sums as may be necessary for fiscal year 2030 for administration.
"""

    sections = parse_federal_structure(source)
    claims = extract_funding_claims(source, sections)

    assert [claim.fields["amount"] for claim in claims] == [
        "25000000.00",
        "1500000.00",
        None,
    ]
    assert [claim.fields["amount_type"] for claim in claims] == [
        "specified",
        "specified",
        "such_sums",
    ]
    assert [claim.fields["currency"] for claim in claims] == ["USD", "USD", None]
    assert [claim.fields["fiscal_years"] for claim in claims] == [
        [2027],
        [2027, 2028, 2029],
        [2030],
    ]
    assert [claim.rule_id for claim in claims] == [
        "funding.authorization.v1",
        "funding.appropriation.v1",
        "funding.authorization_such_sums.v1",
    ]
    assert not extract_modality_claims(source, sections)
    assert_exact_evidence(source, claims)


def test_extract_timeline_claims_normalizes_dates_and_relative_deadlines():
    source = """SEC. 8. DEADLINES
The program begins on January 1, 2028.
Not later than 90 days after enactment, the Secretary shall publish a report.
A review shall occur 2 years after the date of enactment.
This Act takes effect on March 3, 2028.
The invalid period begins on February 30, 2028.
"""

    claims = extract_timeline_claims(source, parse_federal_structure(source))

    assert [claim.fields for claim in claims] == [
        {
            "timeline_type": "absolute",
            "date": "2028-01-01",
            "relative_value": None,
            "relative_unit": None,
            "trigger": None,
        },
        {
            "timeline_type": "relative",
            "date": None,
            "relative_value": 90,
            "relative_unit": "days",
            "trigger": "enactment",
        },
        {
            "timeline_type": "relative",
            "date": None,
            "relative_value": 2,
            "relative_unit": "years",
            "trigger": "the date of enactment",
        },
        {
            "timeline_type": "effective",
            "date": "2028-03-03",
            "relative_value": None,
            "relative_unit": None,
            "trigger": None,
        },
    ]
    assert_exact_evidence(source, claims)


def test_extract_amendments_applies_precedence_and_captures_payloads():
    source = '''SEC. 9. AMENDMENTS
Section 5 of the Example Act is amended by adding at the end the following: “new subsection”.
In section 6, insert “new text” after “old text”.
In section 7, strike “obsolete text”.
In section 8, strike “the Secretary shall publish” and insert “the Secretary may waive”.
In section 9, replace “old term” with “new term”.
Paragraph (2) is redesignated as paragraph (3).
Section 10 is repealed.
Section 11 is amended.
'''

    sections = parse_federal_structure(source)
    claims = extract_amendment_claims(source, sections)

    assert [claim.fields["operation"] for claim in claims] == [
        "add",
        "insert",
        "strike",
        "strike_and_insert",
        "replace",
        "redesignate",
        "repeal",
        "amend",
    ]
    assert claims[0].fields["target"] == "Section 5 of the Example Act"
    assert claims[0].fields["inserted_text"] == "new subsection"
    assert claims[2].fields["removed_text"] == "obsolete text"
    assert claims[3].fields["removed_text"] == "the Secretary shall publish"
    assert claims[3].fields["inserted_text"] == "the Secretary may waive"
    assert claims[4].fields["removed_text"] == "old term"
    assert claims[4].fields["inserted_text"] == "new term"
    assert not extract_modality_claims(source, sections)
    assert_exact_evidence(source, claims)


def test_extract_claims_orders_categories_by_evidence_then_category():
    source = """SEC. 10. PROGRAM
The Secretary shall award the $5 million appropriated for fiscal year 2028 not later than 30 days after enactment.
"""

    claims = extract_claims(source, parse_federal_structure(source))

    assert [claim.category for claim in claims] == [
        "requirements",
        "funding_items",
        "timeline_items",
    ]
