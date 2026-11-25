import pytest
from django.conf import settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import SavedBillSearch, TrackedBill
from apps.accounts.saved_searches import saved_search_queryset
from apps.accounts.tests.test_recommendations_api import bill, client

pytestmark = pytest.mark.django_db


def test_bill_cards_include_sponsor_party_without_a_directory_lookup():
    from apps.accounts.tests.test_recommendations_api import representative

    api = APIClient()
    rep = representative()
    rep.party = "R"
    rep.save()
    bill(1, sponsor=rep)
    assert api.get("/api/bills/").json()["results"][0]["sponsor_party"] == "R"


def test_tracking_filter_is_private_and_applies_before_pagination():
    api, user = client()
    other_api, other = client("other@example.com")
    first, second, third = bill(1), bill(2), bill(3)
    TrackedBill.objects.create(user=user, bill=first)
    TrackedBill.objects.create(user=user, bill=second)
    TrackedBill.objects.create(user=other, bill=third)
    # Use the same JWT cookie as the browser, not Django sessions or forced auth.
    api.force_authenticate(user=None)
    api.cookies[settings.AUTH_ACCESS_COOKIE_NAME] = str(
        RefreshToken.for_user(user).access_token
    )
    response = api.get("/api/bills/", {"tracking": "tracked", "page_size": 1})
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert {"Cookie", "Authorization"} <= set(response["Vary"].split(", "))
    assert response.json()["count"] == 2
    assert response.json()["results"][0]["id"] in {first.id, second.id}
    assert "tracking=tracked" in response.json()["next"]
    assert [
        b["id"]
        for b in api.get("/api/bills/", {"tracking": "untracked"}).json()["results"]
    ] == [third.id]
    assert [
        b["id"]
        for b in other_api.get("/api/bills/", {"tracking": "tracked"}).json()["results"]
    ] == [third.id]
    assert api.get("/api/bills/", {"tracking": "invalid"}).status_code == 400
    assert APIClient().get("/api/bills/", {"tracking": "tracked"}).status_code == 401
    assert APIClient().get("/api/bills/").status_code == 200


def test_saved_tracking_filter_uses_search_owner():
    _, user = client()
    first = bill(1)
    bill(2)
    TrackedBill.objects.create(user=user, bill=first)
    search = SavedBillSearch(user=user, query_json={"tracking": "tracked"})
    assert list(saved_search_queryset(search).values_list("id", flat=True)) == [
        first.id
    ]
