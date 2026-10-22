import pytest
from rest_framework.test import APIClient
from apps.accounts.models import TrackedLegislator
from apps.accounts.tests.test_tracking_api import make_user, make_bill, make_representative, authenticated_client
from apps.research.models import RepresentativeBiography, RepresentativePortrait, ResearchSource


@pytest.mark.django_db
def test_tracked_cards_use_latest_introduction_not_latest_ingestion_and_saved_bio():
    user = make_user()
    rep = make_representative()
    other = make_representative(bioguide_id="B000001")
    TrackedLegislator.objects.create(user=user, representative=rep)
    source = ResearchSource.objects.create(provider="congress", url="https://www.congress.gov", attribution="Congress", content_hash="test")
    RepresentativeBiography.objects.create(representative=rep, source=source, text="Works on education.")
    RepresentativePortrait.objects.create(representative=rep, source=source, image_url="https://www.congress.gov/img/member/a000001_200.jpg")
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


@pytest.mark.django_db
def test_representative_name_search_matches_tokens_and_combines_filters():
    wanted = make_representative(name="Rep. Stansbury, Melanie A. [D-NM-1]", state="NM")
    make_representative(bioguide_id="B000001", name="Melanie Other", state="NY")
    client = APIClient()
    response = client.get("/api/representatives/", {"search": "melanie stansbury", "state": "NM"})
    assert response.status_code == 200
    assert [row["id"] for row in response.json()["results"]] == [wanted.pk]
    assert client.get("/api/representatives/", {"search": "not a member"}).json()["count"] == 0
