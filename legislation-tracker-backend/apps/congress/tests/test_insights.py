from datetime import UTC, datetime

import pytest

from apps.congress.insights import compare_representatives, representative_summary
from apps.congress.models import Representative, Vote, VoteRecord


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
