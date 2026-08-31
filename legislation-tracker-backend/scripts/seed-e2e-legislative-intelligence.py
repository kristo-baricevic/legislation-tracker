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
from apps.legislation.extraction.service import extract_contract
from apps.legislation.models import Bill, BillContract, BillDocument, EvidenceSpan, Topic


def main() -> None:
    Topic.objects.get_or_create(name="Education", defaults={"slug": "education"})
    Topic.objects.get_or_create(name="Health", defaults={"slug": "health"})

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

    source_text = """SEC. 2. RURAL HOSPITAL GRANTS.
The Secretary of Health and Human Services shall award grants to rural hospitals.
There is authorized to be appropriated $25,000,000 for fiscal year 2027.
This Act takes effect 90 days after enactment."""
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR E2E",
        title="Rural Hospital Grants Act",
        status="Introduced",
        processing_status="complete",
        sponsor=alex,
    )
    document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        is_active_version=True,
        extracted_text=source_text,
        content_hash="e2e-contract-source",
    )
    result = extract_contract(document=document, bill=bill)
    assert result.schema_version == "2.0-legal-nlp"
    contract = BillContract.objects.create(
        bill=bill,
        document=document,
        schema_version=result.schema_version,
        contract_json=result.contract_json,
        contract_hash=contract_hash_from_dict(result.contract_json),
    )
    EvidenceSpan.objects.bulk_create(
        [
            EvidenceSpan(
                bill=bill,
                document=document,
                contract=contract,
                field_path=span.field_path,
                start_char=span.start_char,
                end_char=span.end_char,
                quoted_text=span.quoted_text,
                page_number=span.page_number,
            )
            for span in result.evidence
        ]
    )
    bill.latest_contract = contract
    bill.save(update_fields=["latest_contract"])

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
            VoteRecord(vote=second_vote, representative=alex, position="no"),
            VoteRecord(vote=second_vote, representative=blair, position="yes"),
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
