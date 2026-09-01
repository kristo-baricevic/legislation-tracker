#!/usr/bin/env python3
"""Seed the live browser-test stack with auditable legislative intelligence."""

# ruff: noqa: E402, I001

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.e2e")

import django

django.setup()

from django.utils import timezone

from apps.congress.models import (
    BillCosponsor,
    Committee,
    CommitteeMembership,
    Representative,
    Vote,
    VoteRecord,
)
from apps.ingestion.models import RollCallIngestionState
from apps.legislation.contract_json import contract_hash_from_dict
from apps.legislation.models import (
    Bill,
    BillContract,
    BillDocument,
    BillTopic,
    EvidenceSpan,
    Topic,
)


def _section_path():
    return [
        {"level": "section", "label": "Sec. 2", "heading": "Complete reader fixture"}
    ]


def _reader_contract_fixture():
    source_parts: list[str] = []
    spans: dict[str, list[tuple[int, int, str]]] = {}
    cursor = 0

    def append(path: str, text: str) -> None:
        nonlocal cursor
        start = cursor
        source_parts.append(text)
        cursor += len(text)
        spans.setdefault(path, []).append((start, cursor, text))

    long_text = "LONG EVIDENCE START|" + ("A" * 8_960) + "|LONG EVIDENCE END\n"
    for offset in range(0, len(long_text), 4_000):
        append("line_items[0].display_text", long_text[offset : offset + 4_000])
    for index in range(26):
        append("line_items[1].display_text", f"Evidence page chunk {index + 1:02d}.\n")
    for index in range(2, 61):
        append(
            f"line_items[{index}].display_text",
            f"Exact source for reader provision {index + 1}.\n",
        )

    financial_items = []
    actions = (
        ("appropriation", "increase", "Appropriates"),
        ("authorization", "increase", "Authorizes"),
        ("transfer", "neutral_transfer", "Transfers"),
        ("rescission", "decrease", "Rescinds"),
    )
    for index in range(101):
        action, direction, verb = actions[index % len(actions)]
        amount = f"{index + 1}000.00"
        source_account = "Rural Health Reserve" if action == "transfer" else None
        destination_account = "Hospital Grant Account" if action == "transfer" else None
        display = f"{verb} ${index + 1},000.00"
        if action == "transfer":
            display += f" from {source_account} to {destination_account}"
        display += f" for rural health program {index + 1}."
        append(f"financial_items[{index}].display_text", f"{display}\n")
        financial_items.append(
            {
                "id": f"financial-{index}",
                "source_id": f"financial-{index}",
                "section_id": "section-2",
                "section_label": "Sec. 2",
                "section_path": _section_path(),
                "display_text": display,
                "financial_action": action,
                "direction": direction,
                "amount": amount,
                "amount_type": "specified",
                "currency": "USD",
                "fiscal_years": [2027],
                "purpose": f"rural health program {index + 1}",
                "source_account": source_account,
                "destination_account": destination_account,
                "evidence_paths": [f"financial_items[{index}].display_text"],
            }
        )

    definitions = []
    for index in range(27):
        term = "covered hospital" if index == 0 else f"reader term {index + 1}"
        definition = (
            "a rural hospital eligible for a grant"
            if index == 0
            else f"the statutory meaning for term {index + 1}"
        )
        display = f"Defines “{term}” to mean {definition}."
        append(f"definitions[{index}].display_text", f"{display}\n")
        definitions.append(
            {
                "id": f"definition-{index}",
                "source_id": f"definition-{index}",
                "section_id": "section-2",
                "section_label": "Sec. 2",
                "section_path": _section_path(),
                "display_text": display,
                "term": term,
                "definition": definition,
                "definition_type": "means",
                "evidence_paths": [f"definitions[{index}].display_text"],
            }
        )

    line_items = []
    for index in range(61):
        line_items.append(
            {
                "id": f"line-{index}",
                "source_id": f"requirement-{index}",
                "section_id": "section-2",
                "section_path": _section_path(),
                "kind": "requirement",
                "display_text": (
                    "Requires the Secretary to publish a complete rural health implementation plan."
                    if index == 0
                    else f"Requires the Secretary to complete reader provision {index + 1}."
                ),
                "actor": "the Secretary",
                "action": f"complete reader provision {index + 1}",
                "effect": None,
                "claim_refs": [f"requirement-{index}"],
                "exact_financial_refs": (
                    [f"financial-{item}" for item in range(4)] if index == 0 else []
                ),
                "timeline_refs": [],
                "definition_refs": ["definition-0"] if index == 0 else [],
                "evidence_paths": [f"line_items[{index}].display_text"],
            }
        )

    timeline_items = [
        {
            "id": "timeline-0",
            "source_id": "timeline-0",
            "section_id": "section-2",
            "section_label": "Sec. 2",
            "section_path": _section_path(),
            "display_text": "Sets a deadline 90 days after enactment.",
            "timeline_type": "relative",
            "date": None,
            "relative_value": 90,
            "relative_unit": "days",
            "trigger": "enactment",
            "evidence_paths": ["timeline_items[0].display_text"],
        }
    ]
    append(
        "timeline_items[0].display_text",
        "This Act takes effect 90 days after enactment.\n",
    )

    contract_json = {
        "schema_version": "2.1-legal-nlp",
        "coverage_note": "Complete deterministic E2E reader projection.",
        "orientation": {"purpose_clause": None, "purpose_line_item_id": None},
        "reader_stats": {
            "line_item_count": 61,
            "financial_item_count": 101,
            "timeline_item_count": 1,
            "definition_item_count": 27,
            "section_group_count": 1,
        },
        "section_groups": [
            {
                "source_id": "section-2",
                "section_path": _section_path(),
                "line_item_ids": [f"line-{index}" for index in range(61)],
                "section_financial_refs": [
                    f"financial-{index}" for index in range(4, 101)
                ],
                "section_timeline_refs": ["timeline-0"],
            }
        ],
        "line_items": line_items,
        "financial_items": financial_items,
        "timeline_items": timeline_items,
        "definitions": definitions,
    }
    return "".join(source_parts), contract_json, spans


def main() -> None:
    Topic.objects.get_or_create(name="Education", defaults={"slug": "education"})
    health, _ = Topic.objects.get_or_create(name="Health", defaults={"slug": "health"})

    alex = Representative.objects.create(
        bioguide_id="A000001",
        name="Alex Avery",
        first_name="Alex",
        last_name="Avery",
        chamber="house",
        party="Independent",
        state="NY",
        district="1",
    )
    blair = Representative.objects.create(
        bioguide_id="B000001",
        name="Blair Brooks",
        first_name="Blair",
        last_name="Brooks",
        chamber="house",
        party="Independent",
        state="CA",
        district="2",
    )
    casey = Representative.objects.create(
        bioguide_id="C000001",
        name="Casey Chen",
        first_name="Casey",
        last_name="Chen",
        chamber="house",
        party="Democratic",
        state="WA",
        district="3",
    )
    drew = Representative.objects.create(
        bioguide_id="D000001",
        name="Drew Diaz",
        first_name="Drew",
        last_name="Diaz",
        chamber="house",
        party="Republican",
        state="TX",
        district="4",
    )

    source_text, contract_json, evidence = _reader_contract_fixture()
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR E2E",
        title="Rural Hospital Grants Act",
        summary=(
            "Rural Hospital Grants Act\n\n"
            "This bill directs the Department of Health and Human Services to publish a rural-health implementation plan and creates a complete ledger of explicit funding provisions.\n\n"
            "It also defines eligibility terms and preserves the official roll-call record for public review."
        ),
        summary_source="crs",
        summary_action_date=datetime(2026, 1, 2, tzinfo=UTC).date(),
        summary_version_code="IH",
        summary_last_updated_at=datetime(2026, 1, 2, tzinfo=UTC),
        status="Introduced",
        processing_status="complete",
        sponsor=alex,
    )
    BillTopic.objects.create(bill=bill, topic=health, confidence_score=0.99)
    document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        is_active_version=True,
        extracted_text=source_text,
        raw_text=source_text,
        content_type="text/plain",
        file_size_bytes=len(source_text.encode("utf-8")),
        source_url="https://www.congress.gov/bill/119th-congress/house-bill/9999/text",
        content_hash="e2e-contract-source",
    )
    contract = BillContract.objects.create(
        bill=bill,
        document=document,
        schema_version="2.1-legal-nlp",
        contract_json=contract_json,
        contract_hash=contract_hash_from_dict(contract_json),
    )
    EvidenceSpan.objects.bulk_create(
        [
            EvidenceSpan(
                bill=bill,
                document=document,
                contract=contract,
                field_path=field_path,
                start_char=start,
                end_char=end,
                quoted_text=quote,
            )
            for field_path, chunks in evidence.items()
            for start, end, quote in chunks
        ]
    )
    bill.latest_contract = contract
    bill.save(update_fields=["latest_contract"])

    no_summary_bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR E2E NO CRS",
        title="Bill Without a CRS Summary",
        status="Introduced",
        processing_status="complete",
        sponsor=alex,
    )
    no_summary_document = BillDocument.objects.create(
        bill=no_summary_bill,
        version_label="Introduced",
        is_active_version=True,
        extracted_text="SEC. 1. DUTY.\nThe Secretary shall publish a report.",
        content_hash="e2e-no-summary-source",
    )
    no_summary_json = {
        **contract_json,
        "orientation": {
            "purpose_clause": "This bill requires the Secretary to publish a report.",
            "purpose_line_item_id": "line-0",
        },
        "reader_stats": {**contract_json["reader_stats"], "line_item_count": 1},
        "section_groups": [
            {
                **contract_json["section_groups"][0],
                "line_item_ids": ["line-0"],
            }
        ],
        "line_items": [contract_json["line_items"][0]],
    }
    no_summary_contract = BillContract.objects.create(
        bill=no_summary_bill,
        document=no_summary_document,
        schema_version="2.1-legal-nlp",
        contract_json=no_summary_json,
        contract_hash=contract_hash_from_dict(no_summary_json),
    )
    no_summary_bill.latest_contract = no_summary_contract
    no_summary_bill.save(update_fields=["latest_contract"])

    committee = Committee.objects.create(
        system_code="hsii00",
        name="Rules Committee",
        chamber=Committee.Chamber.HOUSE,
        source_updated_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    CommitteeMembership.objects.bulk_create(
        [
            CommitteeMembership(
                committee=committee,
                representative=alex,
                congress=119,
                rank=1,
                role=CommitteeMembership.Role.CHAIR,
                party_side="majority",
                source_name="e2e",
                source_code="II00",
                source_hash="e2e",
                source_updated_at=datetime(2026, 1, 2, tzinfo=UTC),
            ),
            CommitteeMembership(
                committee=committee,
                representative=blair,
                congress=119,
                rank=2,
                role=CommitteeMembership.Role.MEMBER,
                party_side="minority",
                source_name="e2e",
                source_code="II00",
                source_hash="e2e",
                source_updated_at=datetime(2026, 1, 2, tzinfo=UTC),
            ),
        ]
    )
    BillCosponsor.objects.create(
        bill=bill,
        representative=blair,
        sponsorship_date=datetime(2026, 1, 2, tzinfo=UTC).date(),
        is_original_cosponsor=True,
        source_updated_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    first_vote = Vote.objects.create(
        bill=bill,
        congress=119,
        chamber="house",
        session_number=1,
        roll_number=1,
        vote_date=datetime(2026, 1, 3, tzinfo=UTC),
        result="Passed",
        question="Passage of HR E2E",
        yeas=2,
        nays=0,
        source_updated_at=datetime(2026, 1, 3, tzinfo=UTC),
    )
    second_vote = Vote.objects.create(
        bill=bill,
        congress=119,
        chamber="house",
        session_number=1,
        roll_number=2,
        vote_date=datetime(2026, 1, 4, tzinfo=UTC),
        result="Agreed to",
        question="Procedural question",
        yeas=1,
        nays=1,
        source_updated_at=datetime(2026, 1, 4, tzinfo=UTC),
    )
    VoteRecord.objects.bulk_create(
        [
            VoteRecord(vote=first_vote, representative=alex, position="yes"),
            VoteRecord(vote=first_vote, representative=blair, position="yes"),
            VoteRecord(vote=first_vote, representative=casey, position="present"),
            VoteRecord(vote=first_vote, representative=drew, position="not_voting"),
            VoteRecord(vote=second_vote, representative=alex, position="no"),
            VoteRecord(vote=second_vote, representative=blair, position="yes"),
            VoteRecord(vote=second_vote, representative=casey, position="yes"),
            VoteRecord(vote=second_vote, representative=drew, position="no"),
        ]
    )
    RollCallIngestionState.objects.create(
        congress=119,
        chamber="house",
        session_number=1,
        discovered_roll_count=2,
        source_exhausted_at=timezone.now(),
        source_updated_at=datetime(2026, 1, 4, tzinfo=UTC),
        last_polled_at=timezone.now(),
    )
    RollCallIngestionState.objects.create(
        congress=119,
        chamber="house",
        session_number=2,
        discovered_roll_count=0,
        source_exhausted_at=timezone.now(),
        last_polled_at=timezone.now(),
    )


if __name__ == "__main__":
    main()
