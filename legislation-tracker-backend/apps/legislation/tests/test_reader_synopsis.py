import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.test import override_settings

from apps.legislation.extraction.service import extract_contract


def extract(text):
    with override_settings(LEGAL_NLP_V21_WRITE_ENABLED=True):
        result = extract_contract(
            bill=SimpleNamespace(title="Test bill", jurisdiction="federal"),
            document=SimpleNamespace(extracted_text=text, version_label="Introduced"),
        )
    assert result.fallback_reason is None
    assert all(
        text[e.start_char : e.end_char] == e.quoted_text for e in result.evidence
    )
    return result


def test_full_hr1589_has_a_cited_synopsis_of_paths_conditions_and_money():
    case = json.loads(
        (Path(__file__).parent / "fixtures/reader_evals/hr1589-119-ih.json").read_text()
    )
    result = extract(case["text"])
    orientation = result.contract_json["orientation"]
    synopsis = orientation["purpose_clause"]
    assert synopsis is not None
    for phrase in (
        "conditional permanent residence",
        "children",
        "eligibility",
        "temporary protected status",
        "deferred enforced departure",
        "grant program",
        "fees",
        "exemptions",
    ):
        assert phrase in synopsis.lower()
    assert len(synopsis.split()) <= 160
    line = next(
        i
        for i in result.contract_json["line_items"]
        if i["id"] == orientation["purpose_line_item_id"]
    )
    assert line["display_text"] == synopsis
    evidence = [
        e for e in result.evidence if e.field_path == "orientation.purpose_clause"
    ]
    assert len(evidence) >= 3
    assert "all immigrants" not in synopsis.lower()
    assert "citizenship" not in synopsis.lower()
    assert "January 1, 2021" in synopsis


def test_synopsis_residence_date_tracks_source_not_bill_identity():
    case = json.loads(
        (Path(__file__).parent / "fixtures/reader_evals/hr1589-119-ih.json").read_text()
    )
    text = case["text"].replace("January 1, 2021", "March 2, 2023")
    synopsis = extract(text).contract_json["orientation"]["purpose_clause"]
    assert "March 2, 2023" in synopsis
    assert "January 1, 2021" not in synopsis


@pytest.mark.parametrize(
    "verb",
    [
        "shall not adjust",
        "shall study whether to adjust",
        "may recommend that Congress adjust",
        "shall report whether the Secretary shall adjust",
    ],
)
def test_heading_alone_cannot_claim_a_residence_path(verb):
    result = extract(
        f"SEC. 2. Permanent resident status on a conditional basis for certain long-term residents who entered the United States as children\nThe Secretary {verb} to the status of an alien lawfully admitted for permanent residence on a conditional basis an alien who meets the requirements."
    )
    assert result.contract_json["orientation"]["purpose_clause"] is None


def test_quoted_amendment_language_does_not_create_a_synopsis_claim():
    result = extract(
        "SEC. 1. Reports\nThe Secretary shall publish a report.\n[[QUOTED_BLOCK_START]]\nSEC. 2. Permanent resident status on a conditional basis for certain long-term residents who entered the United States as children\nThe Secretary shall adjust to the status of an alien lawfully admitted for permanent residence on a conditional basis any eligible alien.\n[[QUOTED_BLOCK_END]]"
    )
    assert result.contract_json["orientation"]["purpose_clause"] is None


def test_existing_explicit_purpose_is_preserved():
    result = extract(
        "SEC. 1. Purpose\nThe purpose of this Act is to improve access to rural health care.\nSEC. 2. Reports\nThe Secretary shall report annually."
    )
    assert (
        result.contract_json["orientation"]["purpose_clause"]
        == "This bill aims to improve access to rural health care."
    )


@pytest.mark.parametrize(
    "prefix",
    [
        "No agency shall establish",
        "The Secretary shall report whether the agency shall establish",
        "The Secretary shall not establish",
        "The Secretary shall study whether to establish",
        "The Secretary shall establish whether to create",
    ],
)
def test_nonoperative_grant_language_cannot_create_a_program(prefix):
    result = extract(
        "SEC. 1. Grants\n"
        + prefix
        + " a program to award grants to eligible nonprofit organizations to assist eligible applicants."
    )
    assert not result.contract_json.get("orientation", {}).get("purpose_clause")


def test_negative_subject_cannot_create_a_residence_path():
    result = extract(
        "SEC. 2. Permanent resident status on a conditional basis for certain long-term residents who entered the United States as children\n"
        "No agency shall adjust to the status of an alien lawfully admitted for permanent residence an alien who does not meet these requirements."
    )
    assert result.contract_json["orientation"]["purpose_clause"] is None


def test_wrapped_reporting_clause_cannot_create_a_grant_program():
    result = extract(
        "SEC. 1. Reports\nThe Secretary shall report whether the agency\n"
        "shall establish a program to award grants to eligible nonprofit organizations to assist eligible applicants."
    )
    assert result.contract_json["orientation"]["purpose_clause"] is None
