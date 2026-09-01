from copy import deepcopy

import pytest

from apps.legislation.extraction.reader_renderer import render_contract
from apps.legislation.extraction.schema import (
    ContractValidationError,
    validate_contract,
)
from apps.legislation.extraction.types import (
    EvidenceCandidate,
    ExtractedClaim,
    SectionPathItem,
    SourceSpan,
    StructuralSection,
)

SOURCE = "The Secretary shall publish a report."
DISPLAY = "The Secretary is required to publish a report."


def valid_contract():
    return {
        "schema_version": "2.0-legal-nlp",
        "title": "Test Act",
        "version_label": "Introduced",
        "extraction": {
            "method": "federal-rules",
            "parser_version": "2.0.0",
            "sections_seen": 1,
            "sections_with_claims": 1,
            "warnings": [],
        },
        "plain_summary": DISPLAY,
        "key_provisions": [
            {
                "kind": "requirement",
                "section_label": "Sec. 2",
                "heading": "Reports",
                "text": DISPLAY,
            }
        ],
        "requirements": [
            {
                "section_label": "Sec. 2",
                "display_text": DISPLAY,
                "modality": "required",
                "actor": "The Secretary",
                "action": "publish a report",
                "object": None,
                "conditions": [],
            }
        ],
        "funding_items": [],
        "timeline_items": [],
        "definitions": [],
        "applicability": [],
        "amendment_operations": [],
        "limitations": [
            "This automated summary is based on explicit patterns in the bill text and is not legal advice."
        ],
    }


def valid_evidence():
    return tuple(
        EvidenceCandidate(
            field_path=path,
            quoted_text=SOURCE,
            start_char=0,
            end_char=len(SOURCE),
        )
        for path in (
            "plain_summary",
            "key_provisions[0].text",
            "requirements[0].display_text",
        )
    )


def test_validate_contract_accepts_a_complete_contract_with_exact_evidence():
    validate_contract(valid_contract(), valid_evidence(), SOURCE)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update({"unexpected": True}), "Additional properties"),
        (lambda value: value.pop("funding_items"), "funding_items"),
        (
            lambda value: value.update({"schema_version": "9.9-legal-nlp"}),
            "Unsupported legal NLP schema version",
        ),
    ],
)
def test_validate_contract_rejects_invalid_json_shape(mutate, message):
    contract = valid_contract()
    mutate(contract)

    with pytest.raises(ContractValidationError, match=message) as exc_info:
        validate_contract(contract, valid_evidence(), SOURCE)

    assert exc_info.value.reason == "schema_validation_failed"


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        (
            EvidenceCandidate("requirements[9].display_text", SOURCE, 0, len(SOURCE)),
            "does not resolve",
        ),
        (
            EvidenceCandidate(
                "requirements[0].display_text", SOURCE, 0, len(SOURCE) + 1
            ),
            "outside source text",
        ),
        (
            EvidenceCandidate("requirements[0].display_text", "wrong", 0, len(SOURCE)),
            "does not match",
        ),
    ],
)
def test_validate_contract_rejects_invalid_evidence(replacement, message):
    evidence = list(valid_evidence())
    evidence[-1] = replacement

    with pytest.raises(ContractValidationError, match=message) as exc_info:
        validate_contract(valid_contract(), evidence, SOURCE)

    assert exc_info.value.reason == "evidence_validation_failed"


def test_validate_contract_rejects_quotes_over_four_thousand_characters():
    source = SOURCE + ("x" * 4001)
    evidence = list(valid_evidence())
    evidence.append(
        EvidenceCandidate(
            "limitations[0]",
            "x" * 4001,
            len(SOURCE),
            len(source),
        )
    )

    with pytest.raises(ContractValidationError, match="4,000") as exc_info:
        validate_contract(valid_contract(), evidence, source)

    assert exc_info.value.reason == "evidence_validation_failed"


def test_validate_contract_requires_evidence_for_each_visible_field():
    evidence = tuple(
        item
        for item in valid_evidence()
        if item.field_path != "requirements[0].display_text"
    )

    with pytest.raises(
        ContractValidationError, match=r"requirements\[0\].display_text"
    ):
        validate_contract(valid_contract(), evidence, SOURCE)


def test_validate_contract_requires_definition_term_and_display_evidence():
    contract = deepcopy(valid_contract())
    contract["definitions"] = [
        {
            "section_label": "Sec. 3",
            "display_text": "The bill defines “covered entity” as a rural hospital.",
            "term": "covered entity",
            "definition": "a rural hospital",
            "definition_type": "means",
        }
    ]

    with pytest.raises(ContractValidationError, match=r"definitions\[0\].term"):
        validate_contract(contract, valid_evidence(), SOURCE)


V21_SOURCE = """SEC. 2. RURAL GRANTS
The Secretary shall allocate $20,000,000 for covered entity grants not later than 30 days after enactment.
SEC. 3. DEFINITIONS
The term “covered entity” means a rural hospital.
"""


def valid_v21_result():
    from apps.legislation.extraction.federal_structure import parse_federal_structure
    from apps.legislation.extraction.financial_rules import extract_financial_claims
    from apps.legislation.extraction.legal_rules import extract_claims

    sections = parse_federal_structure(V21_SOURCE)
    claims = tuple(
        claim
        for claim in extract_claims(V21_SOURCE, sections)
        if claim.category != "funding_items"
    ) + extract_financial_claims(V21_SOURCE, sections)
    return render_contract(
        title="Rural Grants Act",
        version_label="Introduced",
        sections=sections,
        claims=claims,
        source_text=V21_SOURCE,
    )


def test_validate_contract_accepts_complete_v21_reader_contract():
    result = valid_v21_result()
    contract = result.contract_json

    validate_contract(contract, result.evidence, V21_SOURCE)
    assert contract["schema_version"] == "2.1-legal-nlp"
    assert contract["extraction"]["parser_version"] == "2.1.0"
    assert contract["extraction"]["extractor_version"] == "federal-rules-2.1.0"
    assert contract["reader_stats"] == {
        "line_item_count": 1,
        "financial_item_count": 1,
        "timeline_item_count": 1,
        "definition_item_count": 1,
        "section_group_count": 1,
    }
    assert contract["line_items"][0]["section_path"]
    assert contract["financial_items"][0]["section_path"]
    assert (
        "financial_items[0].amount" in contract["financial_items"][0]["evidence_paths"]
    )


def test_validate_contract_rejects_unresolved_v21_references():
    result = valid_v21_result()
    contract = deepcopy(result.contract_json)
    contract["line_items"][0]["exact_financial_refs"] = ["financial-unknown-1"]

    with pytest.raises(ContractValidationError, match="does not resolve") as exc_info:
        validate_contract(contract, result.evidence, V21_SOURCE)

    assert exc_info.value.reason == "schema_validation_failed"


def test_validate_contract_rejects_cross_section_financial_associations():
    result = valid_v21_result()
    contract = deepcopy(result.contract_json)
    contract["financial_items"][0]["section_id"] = "section-999"

    with pytest.raises(ContractValidationError, match="different section"):
        validate_contract(contract, result.evidence, V21_SOURCE)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda item: item.update({"direction": "decrease"}),
        lambda item: item.update({"amount_type": "percentage", "currency": "USD"}),
    ],
)
def test_validate_contract_rejects_inconsistent_financial_axes(mutate):
    result = valid_v21_result()
    contract = deepcopy(result.contract_json)
    mutate(contract["financial_items"][0])

    with pytest.raises(ContractValidationError, match="financial axes"):
        validate_contract(contract, result.evidence, V21_SOURCE)


def test_validate_contract_requires_consistent_evidence_backed_purpose_orientation():
    result = valid_v21_result()
    contract = deepcopy(result.contract_json)
    line = contract["line_items"][0]
    contract["orientation"] = {
        "purpose_clause": line["display_text"],
        "purpose_line_item_id": line["id"],
    }
    line_evidence = next(
        item
        for item in result.evidence
        if item.field_path == "line_items[0].display_text"
    )
    evidence = result.evidence + (
        EvidenceCandidate(
            field_path="orientation.purpose_clause",
            quoted_text=line_evidence.quoted_text,
            start_char=line_evidence.start_char,
            end_char=line_evidence.end_char,
        ),
    )

    validate_contract(contract, evidence, V21_SOURCE)
    contract["orientation"]["purpose_clause"] = "A different purpose."

    with pytest.raises(ContractValidationError, match="same controlled text"):
        validate_contract(contract, evidence, V21_SOURCE)


def test_validate_contract_requires_every_declared_v21_evidence_path():
    result = valid_v21_result()
    evidence = tuple(
        item
        for item in result.evidence
        if item.field_path != "financial_items[0].amount"
    )

    with pytest.raises(ContractValidationError, match=r"financial_items\[0\]\.amount"):
        validate_contract(result.contract_json, evidence, V21_SOURCE)


def test_v21_renderer_splits_long_evidence_without_losing_source_text():
    source = "x" * 9_001
    span = SourceSpan(source, 0, len(source))
    path = (SectionPathItem("Sec. 4", "Long provision", "section"),)
    section = StructuralSection(
        label="Sec. 4",
        heading="Long provision",
        level="section",
        span=span,
        parent_label=None,
        source_id="section-0",
        path=path,
    )
    claim = ExtractedClaim(
        category="requirements",
        fields={
            "modality": "required",
            "actor": "the Secretary",
            "action": "publish a report",
            "object": None,
            "conditions": [],
        },
        section_label="Sec. 4",
        evidence=(span,),
        rule_id="test.long.v1",
        source_id="section-0",
        section_id="section-0",
        section_path=path,
    )

    result = render_contract(
        title="Long Act",
        version_label="Introduced",
        sections=(section,),
        claims=(claim,),
        source_text=source,
    )

    chunks = [
        item
        for item in result.evidence
        if item.field_path == "line_items[0].display_text"
    ]
    assert all(len(item.quoted_text) <= 4_000 for item in chunks)
    assert "".join(item.quoted_text for item in chunks) == source


def test_v21_contract_does_not_cap_substantive_financial_arrays():
    source = "SEC. 5. COMPLETE LEDGER\n" + "\n".join(
        f"There is appropriated ${index + 1},000 for program {index + 1}."
        for index in range(101)
    )
    from apps.legislation.extraction.federal_structure import parse_federal_structure
    from apps.legislation.extraction.financial_rules import extract_financial_claims

    sections = parse_federal_structure(source)
    result = render_contract(
        title="Complete Ledger Act",
        version_label="Introduced",
        sections=sections,
        claims=extract_financial_claims(source, sections),
        source_text=source,
    )

    assert len(result.contract_json["financial_items"]) == 101
    validate_contract(result.contract_json, result.evidence, source)
