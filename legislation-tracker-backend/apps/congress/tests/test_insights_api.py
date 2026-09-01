from datetime import UTC, datetime, timedelta

import pytest
from rest_framework.test import APIClient

from apps.congress.models import Representative, Vote, VoteRecord
from apps.legislation.models import Bill


@pytest.mark.django_db
def test_representative_insight_and_comparison_routes_are_public_and_validated():
    left = Representative.objects.create(
        bioguide_id="I000005",
        name="API Left",
        chamber="house",
        party="Independent",
        state="NY",
    )
    right = Representative.objects.create(
        bioguide_id="I000006",
        name="API Right",
        chamber="house",
        party="Independent",
        state="NY",
    )
    client = APIClient()

    insight = client.get(f"/api/representatives/{left.id}/insights/?congress=119")
    comparison = client.get(
        f"/api/representatives/compare/?ids={left.id},{right.id}&congress=119"
    )
    invalid = client.get("/api/representatives/compare/?ids=1&congress=119")

    assert insight.status_code == 200
    assert insight.json()["participation_denominator"] == 0
    assert comparison.status_code == 200
    assert comparison.json()["shared_vote_count"] == 0
    assert invalid.status_code == 400


@pytest.mark.django_db
def test_representative_histories_are_paginated_and_comparison_reports_evidence_cap():
    left = Representative.objects.create(
        bioguide_id="I000030", name="Left", chamber="house", party="I", state="NY"
    )
    right = Representative.objects.create(
        bioguide_id="I000031", name="Right", chamber="house", party="I", state="NY"
    )
    for index in range(22):
        Bill.objects.create(
            jurisdiction="federal",
            session=119,
            bill_number=f"HR {1000 + index}",
            title=f"Sponsored {index}",
            status="Introduced",
            sponsor=left,
        )
    start = datetime(2025, 1, 4, tzinfo=UTC)
    for index in range(101):
        vote = Vote.objects.create(
            congress=119,
            chamber="house",
            session_number=1,
            roll_number=1000 + index,
            vote_date=start + timedelta(days=index),
            result="Passed",
        )
        VoteRecord.objects.create(vote=vote, representative=left, position="yes")
        VoteRecord.objects.create(vote=vote, representative=right, position="yes")

    client = APIClient()
    first_page = client.get(
        f"/api/representatives/{left.id}/sponsored-bills/?congress=119&page=1"
    )
    comparison = client.get(
        f"/api/representatives/compare/?ids={left.id},{right.id}&congress=119"
    )

    assert first_page.status_code == 200
    assert first_page.json()["count"] == 22
    assert len(first_page.json()["results"]) == 20
    assert first_page.json()["next"] is not None
    assert comparison.json()["shared_vote_count"] == 101
    assert comparison.json()["returned_shared_vote_count"] == 100
    assert comparison.json()["shared_votes_truncated"] is True
