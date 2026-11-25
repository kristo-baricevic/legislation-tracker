import pytest
from rest_framework.test import APIClient

from apps.accounts.models import TrackedLegislator
from apps.accounts.tests.test_tracking_api import (
    authenticated_client,
    make_bill,
    make_representative,
    make_user,
)
from apps.research.models import (
    RepresentativeBiography,
    RepresentativePortrait,
    ResearchSource,
)


@pytest.mark.django_db
def test_tracked_cards_use_latest_introduction_not_latest_ingestion_and_saved_bio():
    user = make_user()
    rep = make_representative()
    other = make_representative(bioguide_id="B000001")
    TrackedLegislator.objects.create(user=user, representative=rep)
    source = ResearchSource.objects.create(
        provider="congress",
        url="https://www.congress.gov",
        attribution="Congress",
        content_hash="test",
    )
    RepresentativeBiography.objects.create(
        representative=rep, source=source, text="Works on education."
    )
    RepresentativePortrait.objects.create(
        representative=rep,
        source=source,
        image_url="https://www.congress.gov/img/member/a000001_200.jpg",
    )
    latest = make_bill(sponsor=rep, introduced_at="2026-09-01")
    make_bill(sponsor=rep, bill_number="HR 101", introduced_at="2025-01-01")
    make_bill(sponsor=rep, bill_number="HR 102", introduced_at=None)
    make_bill(sponsor=other, bill_number="HR 103", introduced_at="2026-10-01")
    response = authenticated_client(user).get("/api/tracking/")
    assert response.status_code == 200
    cards = response.json()["legislators"]
    assert len(cards) == 1
    assert cards[0]["card"]["latest_bill"]["id"] == latest.pk
    assert cards[0]["card"]["biography"]["text"] == "Works on education."
    assert cards[0]["card"]["portrait"]["url"].endswith("a000001_200.jpg")
    public_card = APIClient().get(f"/api/representatives/{rep.pk}/card/")
    assert public_card.status_code == 200
    assert public_card.json() == cards[0]["card"]
    assert cards[0]["card"]["top_topics"] == []
    assert cards[0]["card"]["research"]["status"] == "not_started"
    assert "snapshot" not in cards[0]["card"]["research"]


@pytest.mark.django_db
def test_representative_name_search_matches_tokens_and_combines_filters():
    wanted = make_representative(name="Rep. Stansbury, Melanie A. [D-NM-1]", state="NM")
    make_representative(bioguide_id="B000001", name="Melanie Other", state="NY")
    client = APIClient()
    response = client.get(
        "/api/representatives/", {"search": "melanie stansbury", "state": "NM"}
    )
    assert response.status_code == 200
    assert [row["id"] for row in response.json()["results"]] == [wanted.pk]
    assert (
        client.get("/api/representatives/", {"search": "not a member"}).json()["count"]
        == 0
    )


@pytest.mark.django_db
def test_card_batch_queries_do_not_grow_per_representative_and_topics_are_combined():
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from django.utils import timezone

    from apps.accounts.legislator_cards import cards_for_representatives
    from apps.research.models import ResearchRun

    reps = [make_representative(bioguide_id=f"T{index:06}") for index in range(6)]
    period = timezone.now().year + timezone.now().year % 2
    ResearchRun.objects.create(representative=reps[0], period=period, status="queued")
    ResearchRun.objects.create(
        representative=reps[0], period=period - 2, status="failed"
    )

    def metric(id, name, count):
        return {
            "topic": {"id": id, "name": name},
            "grouped": {"topic_observation_count": count},
        }

    activities = {
        reps[0].pk: {
            "channels": {
                "sponsor": {
                    "topics": [metric(9, "Education", 2), metric(4, "Budget", 3)]
                },
                "active_cosponsor": {"topics": [metric(9, "Education", 4)]},
            }
        }
    }
    with CaptureQueriesContext(connection) as single:
        cards_for_representatives([reps[0].pk], activities)
    with CaptureQueriesContext(connection) as multiple:
        cards = cards_for_representatives([rep.pk for rep in reps], activities)
    assert len(multiple) == len(single)
    assert len(multiple) <= 5
    assert cards[reps[0].pk]["top_topics"] == [
        {"id": 9, "name": "Education", "count": 6},
        {"id": 4, "name": "Budget", "count": 3},
    ]
    assert cards[reps[0].pk]["research"]["status"] == "queued"
    assert cards[reps[0].pk]["research"]["period"] == period
    assert cards[reps[1].pk]["topics_available"] is False
