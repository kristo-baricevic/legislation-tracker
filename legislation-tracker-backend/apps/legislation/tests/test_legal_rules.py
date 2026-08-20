from apps.legislation.extraction.federal_structure import parse_federal_structure
from apps.legislation.extraction.legal_rules import (
    extract_applicability_claims,
    extract_claims,
    extract_definition_claims,
    extract_modality_claims,
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
