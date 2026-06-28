import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.accounts.models import TrackedBill
from apps.ingestion import views
from apps.legislation.models import Bill


class FakeAsyncResult:
    id = "task-123"


def authenticated_client(email="operator@example.com", *, is_staff=False):
    user = get_user_model().objects.create_user(
        username=email,
        email=email,
        password="password",
        is_staff=is_staff,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_poll_congress_endpoint_requires_authentication(monkeypatch):
    monkeypatch.setattr(
        views.poll_congress,
        "delay",
        lambda **kwargs: FakeAsyncResult(),
    )

    response = APIClient().post(
        "/api/ingestion/poll-congress/",
        {"jurisdiction": "federal", "congress": 118},
        format="json",
    )

    assert response.status_code in (401, 403)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/api/ingestion/bills/",
            {"congress": 119, "bill_type": "hr", "bill_number": "42"},
        ),
        (
            "/api/ingestion/poll-congress/",
            {"jurisdiction": "federal", "congress": 119},
        ),
        ("/api/ingestion/backfill-documents/", {"session": 119}),
        ("/api/ingestion/backfill-topics/", {"session": 119}),
    ],
)
def test_ingestion_endpoints_reject_non_staff_users(monkeypatch, path, payload):
    def fake_process_bill(bill_key):
        bill = Bill.objects.create(
            jurisdiction="federal",
            session=119,
            bill_number="HR 42",
            title="Shared public bill",
            status="Introduced",
        )
        return {"bill_id": bill.id, "unchanged": False}

    monkeypatch.setattr(
        views.poll_congress,
        "delay",
        lambda **kwargs: FakeAsyncResult(),
    )
    monkeypatch.setattr(
        views.backfill_process_bill_versions_for_all_bills,
        "delay",
        lambda **kwargs: FakeAsyncResult(),
    )
    monkeypatch.setattr(
        views.backfill_update_topics,
        "delay",
        lambda **kwargs: FakeAsyncResult(),
        raising=False,
    )
    monkeypatch.setattr(
        views,
        "_process_bill_impl",
        fake_process_bill,
        raising=False,
    )

    response = authenticated_client("member@example.com").post(
        path,
        payload,
        format="json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_poll_congress_endpoint_enqueues_task_for_staff_user(monkeypatch):
    calls = []
    monkeypatch.setattr(
        views.poll_congress,
        "delay",
        lambda **kwargs: calls.append(kwargs) or FakeAsyncResult(),
    )

    response = authenticated_client(is_staff=True).post(
        "/api/ingestion/poll-congress/",
        {"jurisdiction": "federal", "congress": 118},
        format="json",
    )

    assert response.status_code == 202
    assert response.json() == {
        "task_id": "task-123",
        "task_name": "poll_congress",
        "jurisdiction": "federal",
        "congress": 118,
    }
    assert calls == [{"jurisdiction": "federal", "congress": 118}]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("path", "payload", "error"),
    [
        (
            "/api/ingestion/bills/",
            {"congress": "bad", "bill_type": "hr", "bill_number": "42"},
            "congress must be an integer",
        ),
        (
            "/api/ingestion/poll-congress/",
            {"jurisdiction": "federal", "congress": "bad"},
            "congress must be an integer",
        ),
        (
            "/api/ingestion/backfill-documents/",
            {"session": "bad"},
            "session must be an integer",
        ),
        (
            "/api/ingestion/backfill-topics/",
            {"session": "bad"},
            "session must be an integer",
        ),
    ],
)
def test_ingestion_endpoints_validate_integer_params(path, payload, error):
    response = authenticated_client(is_staff=True).post(path, payload, format="json")

    assert response.status_code == 400
    assert response.json() == {"error": error}


@pytest.mark.django_db
def test_backfill_documents_endpoint_enqueues_task_for_staff_user(monkeypatch):
    calls = []
    monkeypatch.setattr(
        views.backfill_process_bill_versions_for_all_bills,
        "delay",
        lambda **kwargs: calls.append(kwargs) or FakeAsyncResult(),
    )

    response = authenticated_client(is_staff=True).post(
        "/api/ingestion/backfill-documents/",
        {"session": 119},
        format="json",
    )

    assert response.status_code == 202
    assert response.json() == {
        "task_id": "task-123",
        "task_name": "backfill_process_bill_versions_for_all_bills",
        "session": 119,
    }
    assert calls == [{"session": 119}]


@pytest.mark.django_db
def test_backfill_topics_endpoint_enqueues_task_for_staff_user(monkeypatch):
    calls = []
    monkeypatch.setattr(
        views.backfill_update_topics,
        "delay",
        lambda **kwargs: calls.append(kwargs) or FakeAsyncResult(),
        raising=False,
    )

    response = authenticated_client(is_staff=True).post(
        "/api/ingestion/backfill-topics/",
        {"session": 119},
        format="json",
    )

    assert response.status_code == 202
    assert response.json() == {
        "task_id": "task-123",
        "task_name": "backfill_update_topics",
        "session": 119,
    }
    assert calls == [{"session": 119}]


@pytest.mark.django_db
def test_staff_ingest_bill_creates_shared_public_bill_and_private_tracking(monkeypatch):
    def fake_process_bill(bill_key):
        assert bill_key == "119-hr-42"
        bill, created = Bill.objects.get_or_create(
            session=119,
            bill_number="HR 42",
            defaults={
                "jurisdiction": "federal",
                "title": "Shared public bill",
                "status": "Introduced",
            },
        )
        return {"bill_id": bill.id, "unchanged": not created}

    monkeypatch.setattr(views, "_process_bill_impl", fake_process_bill, raising=False)
    owner_client = authenticated_client("owner@example.com", is_staff=True)
    other_client = authenticated_client("other@example.com", is_staff=True)

    first = owner_client.post(
        "/api/ingestion/bills/",
        {"congress": 119, "bill_type": "hr", "bill_number": "42"},
        format="json",
    )
    duplicate_owner = owner_client.post(
        "/api/ingestion/bills/",
        {"congress": 119, "bill_type": "hr", "bill_number": "42"},
        format="json",
    )
    other_user = other_client.post(
        "/api/ingestion/bills/",
        {"congress": 119, "bill_type": "hr", "bill_number": "42"},
        format="json",
    )

    assert first.status_code == 201
    assert duplicate_owner.status_code == 200
    assert other_user.status_code == 201

    bill = Bill.objects.get()

    public_detail = APIClient().get(f"/api/bills/{bill.id}/")
    owner_summary = owner_client.get("/api/tracking/")
    other_summary = other_client.get("/api/tracking/")

    assert first.json()["bill"]["id"] == bill.id
    assert duplicate_owner.json()["bill"]["id"] == bill.id
    assert other_user.json()["bill"]["id"] == bill.id
    assert Bill.objects.count() == 1
    assert TrackedBill.objects.count() == 2
    assert public_detail.status_code == 200
    assert public_detail.json()["id"] == bill.id
    assert [item["bill"]["id"] for item in owner_summary.json()["bills"]] == [bill.id]
    assert [item["bill"]["id"] for item in other_summary.json()["bills"]] == [bill.id]
