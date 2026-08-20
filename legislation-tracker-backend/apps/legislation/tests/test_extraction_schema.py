from copy import deepcopy

import pytest

from apps.legislation.extraction.schema import (
    ContractValidationError,
    validate_contract,
)
from apps.legislation.extraction.types import EvidenceCandidate

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
            lambda value: value.update({"schema_version": "2.1-legal-nlp"}),
            "2.0-legal-nlp",
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
            EvidenceCandidate("requirements[0].display_text", SOURCE, 0, len(SOURCE) + 1),
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

    with pytest.raises(ContractValidationError, match=r"requirements\[0\].display_text"):
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
