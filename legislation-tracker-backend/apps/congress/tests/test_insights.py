from datetime import UTC, datetime

import pytest

from apps.congress import insights
from apps.congress.insights import compare_representatives, representative_summary
from apps.congress.models import Representative, RepresentativeTerm, Vote, VoteRecord
from apps.ingestion.models import RollCallIngestionState


@pytest.mark.django_db
def test_representative_insight_uses_raw_counts_and_never_labels_partial_coverage_complete():
    representative = Representative.objects.create(
        bioguide_id="I000002",
        name="Insight Voter",
        chamber="house",
        party="Independent",
        state="NY",
    )
    vote_one = Vote.objects.create(
        congress=119,
        chamber="house",
        session_number=1,
        roll_number=1,
        vote_date=datetime(2026, 1, 1, tzinfo=UTC),
        result="Passed",
    )
    vote_two = Vote.objects.create(
        congress=119,
        chamber="house",
        session_number=1,
        roll_number=2,
        vote_date=datetime(2026, 1, 2, tzinfo=UTC),
        result="Passed",
    )
    VoteRecord.objects.create(vote=vote_one, representative=representative, position="yes")
    VoteRecord.objects.create(vote=vote_two, representative=representative, position="not_voting")

    summary = representative_summary(representative=representative, congress=119)

    assert summary.total_roll_calls == 2
    assert summary.participation_numerator == 1
    assert summary.participation_denominator == 2
    assert summary.coverage_complete is False


@pytest.mark.django_db
def test_representative_coverage_requires_every_current_session(monkeypatch):
    representative = Representative.objects.create(
        bioguide_id="I000005",
        name="Incomplete sessions",
        chamber="house",
        party="Independent",
        state="NY",
    )
    RollCallIngestionState.objects.create(
        congress=119,
        chamber="house",
        session_number=1,
        discovered_roll_count=0,
        source_exhausted_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    monkeypatch.setattr(insights, "current_congress", lambda: 119)
    monkeypatch.setattr(insights, "current_congress_session", lambda: 2)

    summary = representative_summary(representative=representative, congress=119)

    assert summary.coverage_complete is False
    assert summary.coverage_reason == (
        "Roll-call discovery has not started for every applicable session."
    )


@pytest.mark.django_db
def test_representative_comparison_only_uses_shared_yes_no_votes():
    left = Representative.objects.create(
        bioguide_id="I000003",
        name="Left",
        chamber="house",
        party="Independent",
        state="NY",
    )
    right = Representative.objects.create(
        bioguide_id="I000004",
        name="Right",
        chamber="house",
        party="Independent",
        state="NY",
    )
    vote = Vote.objects.create(
        congress=119,
        chamber="house",
        session_number=1,
        roll_number=3,
        vote_date=datetime(2026, 1, 3, tzinfo=UTC),
        result="Passed",
    )
    VoteRecord.objects.create(vote=vote, representative=left, position="yes")
    VoteRecord.objects.create(vote=vote, representative=right, position="no")

    comparison = compare_representatives(left=left, right=right, congress=119)

    assert comparison.shared_vote_count == 1
    assert comparison.agree_count == 0
    assert comparison.agreement_rate == 0


@pytest.mark.django_db
def test_historical_insight_uses_chamber_and_dates_from_service_terms():
    representative = Representative.objects.create(
        bioguide_id="I000020",
        name="Former House Member",
        chamber="senate",
        party="Independent",
        state="NY",
        is_current=False,
    )
    RepresentativeTerm.objects.create(
        representative=representative,
        chamber="house",
        state="NY",
        district="1",
        start_date=datetime(2025, 1, 3, tzinfo=UTC).date(),
        end_date=datetime(2027, 1, 3, tzinfo=UTC).date(),
    )
    house_vote = Vote.objects.create(
        congress=119,
        chamber="house",
        session_number=1,
        roll_number=20,
        vote_date=datetime(2026, 1, 2, tzinfo=UTC),
        result="Passed",
    )
    senate_vote = Vote.objects.create(
        congress=119,
        chamber="senate",
        session_number=1,
        roll_number=20,
        vote_date=datetime(2026, 1, 2, tzinfo=UTC),
        result="Passed",
    )
    VoteRecord.objects.create(
        vote=house_vote, representative=representative, position="yes"
    )
    VoteRecord.objects.create(
        vote=senate_vote, representative=representative, position="no"
    )

    summary = representative_summary(representative=representative, congress=119)

    assert summary.total_roll_calls == 1
    assert summary.position_counts["yes"] == 1
    assert summary.position_counts["no"] == 0


@pytest.mark.django_db
def test_historical_insight_does_not_infer_service_from_a_current_profile(monkeypatch):
    representative = Representative.objects.create(
        bioguide_id="I000021",
        name="Current Member Without History",
        chamber="house",
        party="Independent",
        state="NY",
        is_current=True,
    )
    vote = Vote.objects.create(
        congress=118,
        chamber="house",
        session_number=1,
        roll_number=21,
        vote_date=datetime(2023, 1, 4, tzinfo=UTC),
        result="Passed",
    )
    VoteRecord.objects.create(
        vote=vote,
        representative=representative,
        position="yes",
    )
    monkeypatch.setattr(insights, "current_congress", lambda: 119)

    summary = representative_summary(representative=representative, congress=118)

    assert summary.total_roll_calls == 0
    assert summary.coverage_complete is False
    assert summary.coverage_reason == (
        "Service-term history is unavailable for this Congress."
    )
