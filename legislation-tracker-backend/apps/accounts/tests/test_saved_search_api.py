import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.accounts.models import SavedBillSearch, User
from apps.accounts.saved_searches import count_saved_search_new_results
from apps.changelog.services import record_bill_change
from apps.legislation.models import Bill

POSTGRESQL_ONLY = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="requires PostgreSQL query composition"
)


@pytest.mark.django_db
def test_saved_search_is_private_and_reports_activity_since_open():
    owner = User.objects.create_user(
        username="owner@example.test",
        email="owner@example.test",
        password="safe-password-123",
    )
    other = User.objects.create_user(
        username="other@example.test",
        email="other@example.test",
        password="safe-password-123",
    )
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 905",
        title="Rural clinic support",
        status="Introduced",
    )
    client = APIClient()
    client.force_authenticate(owner)

    created = client.post(
        "/api/saved-searches/",
        {"name": "Rural care", "query": {"q": "rural clinic"}},
        format="json",
    )
    search_id = created.json()["id"]
    result = client.get(f"/api/saved-searches/{search_id}/results/")
    opened = client.post(
        f"/api/saved-searches/{search_id}/open/",
        {"result_watermark": result.json()["result_watermark"]},
        format="json",
    )
    record_bill_change(
        bill=bill,
        change_type="status_update",
        new_value={"status": "Reported"},
        event_key="saved-search-change",
    )

    listing = client.get("/api/saved-searches/")
    client.force_authenticate(other)
    forbidden = client.get(f"/api/saved-searches/{search_id}/")

    assert created.status_code == 201
    assert result.status_code == 200
    assert opened.status_code == 200
    assert listing.json()["results"][0]["new_result_count"] == 1
    assert forbidden.status_code == 404


@pytest.mark.django_db
def test_saved_search_rejects_unknown_query_keys_and_duplicate_normalized_query():
    user = User.objects.create_user(
        username="saved@example.test",
        email="saved@example.test",
        password="safe-password-123",
    )
    client = APIClient()
    client.force_authenticate(user)

    first = client.post(
        "/api/saved-searches/",
        {"name": "First", "query": {"q": " rural   care "}},
        format="json",
    )
    duplicate = client.post(
        "/api/saved-searches/",
        {"name": "Second", "query": {"q": "rural care"}},
        format="json",
    )
    invalid = client.post(
        "/api/saved-searches/",
        {"name": "Invalid", "query": {"unknown": "value"}},
        format="json",
    )

    assert first.status_code == 201
    assert duplicate.status_code == 400
    assert invalid.status_code == 400


@POSTGRESQL_ONLY
@pytest.mark.django_db
def test_saved_search_activity_counts_are_computed_in_one_database_query():
    user = User.objects.create_user(
        username="query-count@example.test",
        email="query-count@example.test",
        password="safe-password-123",
    )
    Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 906",
        title="Active bill",
        status="Introduced",
        last_activity_sequence=5,
    )
    searches = [
        SavedBillSearch.objects.create(
            user=user,
            name="All active",
            query_json={"session": 119},
            normalized_hash="all-active",
        ),
        SavedBillSearch.objects.create(
            user=user,
            name="Introduced",
            query_json={"session": 119, "status": "Introduced"},
            normalized_hash="introduced",
        ),
    ]

    with CaptureQueriesContext(connection) as queries:
        counts = count_saved_search_new_results(searches)

    assert counts == {searches[0].id: 1, searches[1].id: 1}
    assert len(queries) == 1
    assert "UNION ALL" in queries[0]["sql"]
