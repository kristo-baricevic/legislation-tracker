"""Inserted law is operative; quotations of deleted/background law are not."""
import json
from decimal import Decimal
from pathlib import Path

import pytest

from apps.legislation.extraction.federal_clauses import _quoted_block_ranges
from .test_reader_synopsis import extract


@pytest.mark.parametrize("instruction", [
    "The Public Health Service Act is amended by inserting after section 229 (42 U.S.C. 237a) the following:",
    "Section 4 is amended to read as follows:",
    "Section 4 is amended to read—",
    "Section 4 is transferred to title 14, redesignated as section 102, and amended to read as follows:",
    "Section 4 is amended by inserting at the end",
    "Section 4 is amended by inserting after paragraph (3) the following, and redesignating succeeding paragraphs accordingly:",
    "Section 4 is amended by adding at the end the following:",
    "Section 4 is amended by adding at the end the following new subclause:",
    "Section 4 is amended by adding at the end the following subparagraph:",
    "Section 4 is amended by adding at the end the following new part:",
    "Section 4 is amended by adding at the end the following new sections:",
    "The table of contents is amended by adding at the end the following new item:",
    "Section 4 is amended by striking the period, and by adding at the end the following new subparagraph:",
    "Section 4 is amended by adding at the end the following new flush sentence:",
    "Section 4 is amended by inserting in numerical sequence the following new subheading:",
    "Section 4 is amended by adding at the end—",
    "Section 4 is amended by inserting at the end—",
    "Section 4 is amended by adding at the end a new subchapter:",
    "Section 4 is amended by inserting, after section 1151, the following new section 1152:",
    "Section 4 is amended by redesignating paragraph (C) as (D) and inserting after paragraph (B) the following:",
    "Section 4 is amended by adding at the end the following new section (and conforming the table of sections accordingly):",
    "Section 4 is amended to read as follows (and by conforming the table of sections accordingly):",
    "Section 4 is amended by amending paragraph (B) to read as follows:",
])
def test_explicit_insertions_are_operative(instruction):
    text = f"{instruction}\n[[QUOTED_BLOCK_START]]\nSEC. 5. Grants\nThe Secretary shall award grants.\n[[QUOTED_BLOCK_END]]"
    assert _quoted_block_ranges(text) == ()


@pytest.mark.parametrize("instruction", [
    "The committee discussed the following:",
    "Section 4 is amended by striking the following:",
    "The report recommends inserting the following:",
    'Section 4 is amended by striking the words "by adding the following":',
    "Section 4 is amended by striking the words 'by adding the following':",
])
def test_nonoperative_quotes_stay_excluded(instruction):
    text = f"{instruction}\n[[QUOTED_BLOCK_START]]\nThe Secretary shall award grants.\n[[QUOTED_BLOCK_END]]"
    assert _quoted_block_ranges(text)


def test_nested_insertion_inherits_its_structural_amendment_only():
    body = '(B) by inserting after clause (ii) the following new clause:\n[[QUOTED_BLOCK_START]]\n(iii) The Secretary shall report.\n[[QUOTED_BLOCK_END]]'
    assert not _quoted_block_ranges('SEC. 1. Amendment\n(a) Section 4 is amended—\n(A) by striking the heading; and\n' + body)
    assert _quoted_block_ranges('SEC. 1. Amendment\nSection 4 is amended—\nSEC. 2. Report\n' + body)


def test_conforming_table_instruction_does_not_hide_inserted_law():
    text = ('SEC. 1. Transcripts\nSubchapter III of chapter 33 is amended by adding at the end the following new section (and amending the table of sections accordingly):\n[[QUOTED_BLOCK_START]]\nSEC. 3328. Transcripts\nAn institution may not withhold a transcript solely because a student owes a debt.\n[[QUOTED_BLOCK_END]]')
    assert not _quoted_block_ranges(text)
    assert extract(text).contract_json['line_items']


def test_hr9842_inserted_program_and_authorization_are_not_lost():
    case = json.loads((Path(__file__).parent / "fixtures/reader_evals/hr9842-119-ih.json").read_text())
    result = extract(case["text"])
    contract = result.contract_json
    assert contract["financial_items"]
    money = json.dumps(contract["financial_items"])
    assert "55000000" in money
    assert "authorization" in money
    assert "2027" in money and "2031" in money
    authorization = next(m for m in contract["financial_items"] if m["financial_action"] == "authorization")
    assert "each" in authorization["display_text"]
    assert "State offices" in authorization["display_text"]
    assert "there are authorized" not in authorization["display_text"]
    allocations = [m for m in contract["financial_items"] if m["financial_action"] == "allocation"]
    assert len(allocations) == 2
    assert all(Decimal(m["amount"]) == Decimal("50") for m in allocations)
    assert any("equally" in m["display_text"] for m in allocations)
    assert any("maternal mortality" in m["display_text"] for m in allocations)
    displayed = " ".join(i["display_text"] for i in contract["line_items"])
    assert "eligible State" in displayed
    assert "may not" in displayed.lower() or "prohibit" in displayed.lower()
    synopsis = contract["orientation"]["purpose_clause"]
    assert synopsis and "State" in synopsis and "health" in synopsis
    assert "intentionally discourage" in displayed
    assert "social determinants" in displayed


def test_nested_background_quote_and_unclosed_insert_remain_excluded():
    intro = "Section 4 is amended to read as follows:\n"
    nested = "[[QUOTED_BLOCK_START]]\nThe Secretary shall report.\nBackground:\n[[QUOTED_BLOCK_START]]\nOld law.\n[[QUOTED_BLOCK_END]]\n[[QUOTED_BLOCK_END]]"
    ranges = _quoted_block_ranges(intro + nested)
    assert len(ranges) == 1
    assert "Old law." in (intro + nested)[ranges[0][0]:ranges[0][1]]
    assert _quoted_block_ranges(intro + "[[QUOTED_BLOCK_START]]\nUnclosed")


def test_uninterpreted_amendment_is_explicitly_incomplete():
    result = extract(
        "SEC. 1. Short title\nThis Act may be cited as the Test Act.\n"
        "SEC. 2. Amendment\nSection 4 is amended as provided below:\n"
        "[[QUOTED_BLOCK_START]]\nThe Secretary shall award grants of $55,000,000.\n"
        "[[QUOTED_BLOCK_END]]"
    )
    assert "incomplete_amendment_extraction" in result.contract_json["extraction"]["warnings"]
    assert "incomplete" in result.contract_json["coverage_note"].lower()


def test_empty_table_of_contents_block_is_not_missing_substantive_analysis():
    result = extract('SEC. 1. Report\nThe Secretary shall report annually.\nThe table of contents is amended by read as follows:\n[[QUOTED_BLOCK_START]]\n.\n[[QUOTED_BLOCK_END]]')
    assert 'incomplete_amendment_extraction' not in result.contract_json['extraction']['warnings']


@pytest.mark.django_db
def test_incomplete_amendment_is_not_marked_complete(monkeypatch):
    from django.test import override_settings
    from apps.ingestion import tasks as ingestion_tasks
    from apps.legislation import tasks
    from apps.legislation.models import Bill, BillDocument
    monkeypatch.setattr(ingestion_tasks.dispatch_ingestion_work, "delay", lambda: None)
    bill = Bill.objects.create(jurisdiction="federal", session=119, bill_number="HR 1",
                               title="Test", status="Introduced")
    doc = BillDocument.objects.create(
        bill=bill, version_label="Introduced", is_active_version=True,
        extracted_text="SEC. 1. Short title\nThis Act may be cited as the Test Act.\n"
        "SEC. 2. Amendment\nSection 4 is amended as provided below:\n"
        "[[QUOTED_BLOCK_START]]\nThe Secretary shall award grants.\n[[QUOTED_BLOCK_END]]",
    )
    with override_settings(LEGAL_NLP_V21_WRITE_ENABLED=True):
        tasks.generate_contract(doc.pk)
    bill.refresh_from_db()
    assert bill.processing_status == "failed"
