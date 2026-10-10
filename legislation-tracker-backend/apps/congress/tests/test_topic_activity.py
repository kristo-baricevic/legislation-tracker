from datetime import UTC
from fractions import Fraction

import pytest
from django.core.cache import cache

from apps.accounts.tests.test_recommendations_api import bill, representative, topic
from apps.legislation.models import BillTopic

pytestmark = pytest.mark.django_db(transaction=True)


def test_repeat_group_does_not_inflate_intersection_mass():
    from apps.congress.topic_activity import representative_topic_activity

    cache.clear()
    rep = representative()
    health, education, housing = topic(), topic("education"), topic("housing")
    bill(1, sponsor=rep, topics=(health, education), title="Same title")
    bill(2, sponsor=rep, topics=(health, housing), title="Same title")
    evidence = representative_topic_activity(rep.id)
    channel = evidence["channels"]["sponsor"]
    health_evidence = next(
        item for item in channel["topics"] if item["topic"]["id"] == health.id
    )
    assert channel["grouped_observation_count"] == 1
    assert health_evidence["grouped"]["mass"] == {"numerator": "1", "denominator": "2"}
    assert health_evidence["grouped"]["share"] == 0.5
    assert health_evidence["recurring"] is False


def test_nonpositive_tags_are_unknown_mass_not_denominator_removal():
    from apps.congress.topic_activity import representative_topic_activity

    cache.clear()
    rep, health = representative(), topic()
    bill(1, sponsor=rep, topics=(health,))
    untagged = bill(2, sponsor=rep)
    BillTopic.objects.create(bill=untagged, topic=health, confidence_score=0)
    channel = representative_topic_activity(rep.id)["channels"]["sponsor"]
    assert channel["raw_observation_count"] == 2
    assert channel["raw_tagged_count"] == 1
    assert channel["topics"][0]["raw"]["share"] == 0.5


def test_policy_rejects_nonfinite_threshold():
    from apps.congress.topic_activity import ActivityPolicy

    with pytest.raises(ValueError):
        ActivityPolicy(topic_share="NaN")
    with pytest.raises(ValueError):
        ActivityPolicy(window_months=True)


def test_rounding_is_exact_half_even_at_millionths():
    from apps.congress.topic_activity import quantize_fraction

    assert quantize_fraction(Fraction(5, 2_000_000)) == Fraction(2, 1_000_000)
    assert quantize_fraction(Fraction(7, 2_000_000)) == Fraction(4, 1_000_000)


def test_resolution_counts_belong_to_the_representative():
    from apps.congress.topic_activity import representative_topic_activity

    cache.clear()
    first, second = representative(), representative("B000002")
    resolution = bill(1, sponsor=first)
    resolution.bill_number = "HRES 1"
    resolution.save(update_fields=["bill_number"])
    assert representative_topic_activity(first.id)["resolutions"]["simple_count"] == 1
    assert representative_topic_activity(second.id)["resolutions"]["simple_count"] == 0


def test_passage_evidence_excludes_procedure_and_older_yes_when_latest_record_missing():
    from datetime import datetime

    from apps.congress.models import Vote, VoteRecord
    from apps.congress.topic_activity import representative_topic_activity

    cache.clear()
    rep = representative()
    target = bill(1, sponsor=rep, topics=(topic(),))

    def roll(number, month, question):
        return Vote.objects.create(
            congress=119,
            chamber="house",
            session_number=1,
            roll_number=number,
            vote_date=datetime(2025, month, 10, tzinfo=UTC),
            question=question,
            bill=target,
            source_url=f"https://clerk.house.gov/Votes/2025{number}",
        )

    older = roll(1, 1, "On Passage")
    VoteRecord.objects.create(vote=older, representative=rep, position="yes")
    roll(2, 2, "On Passage")
    procedure = roll(3, 3, "On Ordering the Previous Question")
    VoteRecord.objects.create(vote=procedure, representative=rep, position="yes")
    evidence = representative_topic_activity(rep.id)["passage_evidence"]
    assert evidence["yes"] == 0
    assert evidence["yes_rate"] is None
    assert evidence["status"] == "coverage_unknown"


def test_unknown_vote_session_is_uncertain_evidence():
    from datetime import datetime

    from apps.congress.models import Vote, VoteRecord
    from apps.congress.topic_activity import representative_topic_activity

    cache.clear()
    rep = representative()
    target = bill(1, sponsor=rep, topics=(topic(),))
    vote = Vote.objects.create(
        congress=119,
        chamber="house",
        session_number=None,
        roll_number=1,
        vote_date=datetime(2025, 2, 10, tzinfo=UTC),
        question="On Passage",
        bill=target,
        source_url="https://clerk.house.gov/Votes/20251",
    )
    VoteRecord.objects.create(vote=vote, representative=rep, position="yes")
    evidence = representative_topic_activity(rep.id)["passage_evidence"]
    assert evidence["yes"] == 0
    assert evidence["missing_or_uncertain"] == 1
    assert evidence["topics"][0]["missing_or_uncertain"] == 1
    assert evidence["topics"][0]["yes_rate"] is None


def test_newer_uncertain_roll_blocks_older_yes_and_cross_chamber_is_not_missing():
    from datetime import datetime

    from apps.congress.models import Vote, VoteRecord
    from apps.congress.topic_activity import representative_topic_activity

    cache.clear()
    rep = representative()
    target = bill(1, sponsor=rep, topics=(topic(),))

    def roll(number, month, chamber="house", session=1):
        value = Vote.objects.create(
            congress=119,
            chamber=chamber,
            session_number=session,
            roll_number=number,
            vote_date=datetime(2025, month, 10, tzinfo=UTC),
            question="On Passage",
            bill=target,
            source_url=f"https://clerk.house.gov/Votes/2025{number}",
        )
        VoteRecord.objects.create(
            vote=value, representative=rep, position="yes" if number == 1 else "no"
        )
        return value

    roll(1, 1)
    latest = roll(2, 2, session=None)
    evidence = representative_topic_activity(rep.id)["passage_evidence"]
    assert evidence["yes"] == 0
    assert evidence["yes_rate"] is None
    assert evidence["missing_or_uncertain"] == 1
    latest.session_number = 1
    latest.chamber = "senate"
    latest.save(update_fields=["session_number", "chamber"])
    cache.clear()
    evidence = representative_topic_activity(rep.id)["passage_evidence"]
    assert evidence["no"] == 1
    assert evidence["yes"] == 0
    assert evidence["missing_or_uncertain"] == 0
    assert evidence["cross_chamber_history_count"] == 1
    assert evidence["examples"][0]["cross_chamber_history"] is True


def test_missing_date_count_uses_congress_interval_and_unknown_session_is_separate():
    from datetime import date

    from apps.congress.models import BillCosponsor
    from apps.congress.topic_activity import representative_topic_activity

    cache.clear()
    sponsor, cosponsor = representative(), representative("B000002")
    old = bill(1, sponsor=sponsor)
    old.session = 114
    old.introduced_at = None
    old.save(update_fields=["session", "introduced_at"])
    BillCosponsor.objects.create(
        bill=old, representative=cosponsor, sponsorship_date=date(2025, 2, 1)
    )
    assert (
        representative_topic_activity(sponsor.id)["channels"]["sponsor"][
            "missing_date_count"
        ]
        == 0
    )
    unknown = bill(2, sponsor=sponsor)
    unknown.session = 0
    unknown.save(update_fields=["session"])
    cache.clear()
    channel = representative_topic_activity(sponsor.id)["channels"]["sponsor"]
    assert channel["unknown_session_count"] == 1
    assert channel["raw_observation_count"] == 0


def test_window_calendar_month_clamp_and_washington_date():
    from datetime import date, datetime

    from apps.congress.topic_activity import ActivityPolicy, window_for

    policy = ActivityPolicy(window_months=12)
    start, end = window_for(datetime(2024, 2, 29, 18, tzinfo=UTC), policy)
    assert start == date(2023, 2, 28)
    assert end == date(2024, 3, 1)
    start, end = window_for(datetime(2026, 10, 10, 1, tzinfo=UTC), policy)
    assert start == date(2025, 10, 9)
    assert end == date(2026, 10, 10)


@pytest.mark.parametrize(
    "day,older_count,future_count", [(1, 1, 0), (2, 1, 0), (3, 0, 1)]
)
def test_undated_congress_interval_changes_on_january_third(
    day, older_count, future_count
):
    from datetime import datetime
    from unittest.mock import patch

    from apps.congress.topic_activity import representative_topic_activity

    cache.clear()
    older, future = representative(), representative("B000002")
    for number, session, sponsor in ((1, 118, older), (2, 120, future)):
        item = bill(number, sponsor=sponsor)
        item.session = session
        item.introduced_at = None
        item.save(update_fields=["session", "introduced_at"])
    with patch(
        "apps.congress.topic_activity.timezone.now",
        return_value=datetime(2027, 1, day, 12, tzinfo=UTC),
    ):
        assert (
            representative_topic_activity(older.id)["channels"]["sponsor"][
                "missing_date_count"
            ]
            == older_count
        )
        assert (
            representative_topic_activity(future.id)["channels"]["sponsor"][
                "missing_date_count"
            ]
            == future_count
        )


def test_cosponsor_dates_withdrawal_and_union_do_not_double_count():
    from datetime import date, datetime

    from apps.congress.models import BillCosponsor
    from apps.congress.topic_activity import representative_activity_catalog

    cache.clear()
    rep, health = representative(), topic()
    own = bill(1, sponsor=rep, topics=(health,))
    BillCosponsor.objects.create(
        bill=own, representative=rep, sponsorship_date=date(2025, 2, 1)
    )
    missing = bill(2, topics=(health,))
    BillCosponsor.objects.create(bill=missing, representative=rep)
    withdrawn = bill(3, topics=(health,))
    BillCosponsor.objects.create(
        bill=withdrawn,
        representative=rep,
        sponsorship_date=date(2025, 2, 1),
        withdrawn_at=datetime(2025, 3, 1, tzinfo=UTC),
    )
    item = representative_activity_catalog()["representatives"][str(rep.id)]
    assert item["union_count"] == 1
    cos = item["activity"]["channels"]["active_cosponsor"]
    assert cos["raw_observation_count"] == 1
    assert cos["missing_date_count"] == 1
    assert cos["withdrawn_count"] == 1


def test_catalog_busy_expiry_and_failure_do_not_publish_partial_data():
    from unittest.mock import patch

    from apps.accounts.recommendation_support import RecommendationError
    from apps.congress.topic_activity import representative_activity_catalog

    cache.clear()
    with patch(
        "apps.congress.topic_activity.cache_call",
        side_effect=lambda method, *args, **kwargs: None if method == "get" else False,
    ):
        with pytest.raises(RecommendationError):
            representative_activity_catalog()
    cache.clear()
    with patch("apps.congress.topic_activity._build_catalog", side_effect=TimeoutError):
        with pytest.raises(RecommendationError):
            representative_activity_catalog()
    cache.clear()
    with patch(
        "apps.congress.topic_activity.bounded_json",
        side_effect=RecommendationError("recommendations_metadata_too_large"),
    ):
        with pytest.raises(RecommendationError):
            representative_activity_catalog()
