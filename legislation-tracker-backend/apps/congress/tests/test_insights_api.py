import pytest
from rest_framework.test import APIClient

from apps.congress.models import Representative


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
