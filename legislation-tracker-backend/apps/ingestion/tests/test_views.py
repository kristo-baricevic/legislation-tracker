import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.accounts.models import TrackedBill
from apps.ingestion.models import IngestionTaskFailure, IngestionWorkItem, IngestionWorkStatus
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
def test_sync_representatives_endpoint_enqueues_roster_sync_for_staff_user(monkeypatch):
    calls = []
    monkeypatch.setattr(
        views.sync_representatives,
        "delay",
        lambda **kwargs: calls.append(kwargs) or FakeAsyncResult(),
    )

    response = authenticated_client(is_staff=True).post(
        "/api/ingestion/sync-representatives/",
        {"congress": 119},
        format="json",
    )

    assert response.status_code == 202
    assert response.json() == {
        "task_id": "task-123",
        "task_name": "sync_representatives",
        "congress": 119,
    }
    assert calls == [{"congress": 119}]


@pytest.mark.django_db
def test_sync_representatives_endpoint_rejects_a_historical_congress(monkeypatch):
    monkeypatch.setattr(
        views.sync_representatives,
        "delay",
        lambda **kwargs: pytest.fail("historical roster must not be queued"),
    )

    response = authenticated_client(is_staff=True).post(
        "/api/ingestion/sync-representatives/",
        {"congress": 118},
        format="json",
    )

    assert response.status_code == 400
    assert response.json() == {"error": "congress must be the current Congress (119)"}


@pytest.mark.django_db
def test_staff_can_list_dead_lettered_ingestion_work():
    work = IngestionWorkItem.objects.create(
        kind="bill",
        dedupe_key="119-hr-42",
        source_updated_at="2026-08-19T00:00:00Z",
        payload_json={"bill_key": "119-hr-42"},
        status=IngestionWorkStatus.DEAD,
        last_error="Congress unavailable",
    )
    failure = IngestionTaskFailure.objects.create(
        task_id="task-42",
        task_name="process_ingestion_work_item",
        work_item=work,
        args_json={"args": [work.id], "kwargs": {}},
        error_message="Congress unavailable",
    )

    response = authenticated_client(is_staff=True).get("/api/ingestion/failures/")

    assert response.status_code == 200
    assert response.json() == {
        "count": 1,
        "results": [
            {
                "id": failure.id,
                "task_id": "task-42",
                "task_name": "process_ingestion_work_item",
                "work_item_id": work.id,
                "bill_id": None,
                "error_message": "Congress unavailable",
                "replay_count": 0,
            }
        ],
    }


@pytest.mark.django_db
def test_staff_can_replay_dead_lettered_ingestion_work(monkeypatch):
    work = IngestionWorkItem.objects.create(
        kind="bill",
        dedupe_key="119-hr-42",
        source_updated_at="2026-08-19T00:00:00Z",
        payload_json={"bill_key": "119-hr-42"},
        status=IngestionWorkStatus.DEAD,
        attempt_count=5,
        last_error="Congress unavailable",
    )
    failure = IngestionTaskFailure.objects.create(
        task_id="task-42",
        task_name="process_ingestion_work_item",
        work_item=work,
        args_json={"args": [work.id], "kwargs": {}},
        error_message="Congress unavailable",
    )
    calls = []
    monkeypatch.setattr(
        views.dispatch_ingestion_work,
        "delay",
        lambda: calls.append(True) or FakeAsyncResult(),
    )

    response = authenticated_client(is_staff=True).post(
        f"/api/ingestion/failures/{failure.id}/replay/",
        {},
        format="json",
    )

    work.refresh_from_db()
    failure.refresh_from_db()
    assert response.status_code == 202
    assert response.json() == {
        "id": failure.id,
        "work_item_id": work.id,
        "status": "pending",
        "replay_count": 1,
    }
    assert work.status == IngestionWorkStatus.PENDING
    assert work.attempt_count == 0
    assert work.last_error == ""
    assert failure.replay_count == 1
    assert failure.last_replayed_at is not None
    assert calls == [True]


@pytest.mark.django_db
def test_staff_can_replay_a_dead_lettered_document_stage(monkeypatch):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 43",
        title="Document replay bill",
        status="Introduced",
    )
    failure = IngestionTaskFailure.objects.create(
        task_id="task-document-43",
        task_name="apps.ingestion.tasks.process_bill_versions",
        bill_id=bill.id,
        args_json={"args": [bill.id], "kwargs": {}},
        error_message="temporary Congress failure",
    )
    calls = []
    monkeypatch.setattr(
        views.process_bill_versions,
        "apply_async",
        lambda args=None, kwargs=None: calls.append((args, kwargs)) or FakeAsyncResult(),
        raising=False,
    )

    listed = authenticated_client(is_staff=True).get("/api/ingestion/failures/")
    replayed = authenticated_client("replay-operator@example.com", is_staff=True).post(
        f"/api/ingestion/failures/{failure.id}/replay/",
        {},
        format="json",
    )

    failure.refresh_from_db()
    assert listed.status_code == 200
    assert listed.json()["results"][0]["id"] == failure.id
    assert replayed.status_code == 202
    assert replayed.json()["task_name"] == "apps.ingestion.tasks.process_bill_versions"
    assert failure.resolved_at is not None
    assert calls == [([bill.id], {})]


@pytest.mark.django_db
def test_staff_can_replay_a_dead_lettered_contract_stage(monkeypatch):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 44",
        title="Contract replay bill",
        status="Introduced",
    )
    failure = IngestionTaskFailure.objects.create(
        task_id="task-contract-44",
        task_name="apps.legislation.tasks.generate_contract",
        bill_id=bill.id,
        args_json={"args": [44], "kwargs": {}},
        error_message="contract generation failed",
    )
    calls = []
    monkeypatch.setattr(
        views.generate_contract,
        "apply_async",
        lambda args=None, kwargs=None: calls.append((args, kwargs)) or FakeAsyncResult(),
    )

    listed = authenticated_client(is_staff=True).get("/api/ingestion/failures/")
    replayed = authenticated_client("contract-operator@example.com", is_staff=True).post(
        f"/api/ingestion/failures/{failure.id}/replay/",
        {},
        format="json",
    )

    failure.refresh_from_db()
    assert [item["id"] for item in listed.json()["results"]] == [failure.id]
    assert replayed.status_code == 202
    assert replayed.json()["task_name"] == "apps.legislation.tasks.generate_contract"
    assert failure.resolved_at is not None
    assert calls == [([44], {})]


@pytest.mark.django_db
def test_resolved_dead_lettered_stage_cannot_be_replayed_twice(monkeypatch):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 45",
        title="One-time replay bill",
        status="Introduced",
    )
    failure = IngestionTaskFailure.objects.create(
        task_id="task-document-45",
        task_name="apps.ingestion.tasks.process_bill_versions",
        bill_id=bill.id,
        args_json={"args": [bill.id], "kwargs": {}},
        error_message="temporary Congress failure",
    )
    calls = []
    monkeypatch.setattr(
        views.process_bill_versions,
        "apply_async",
        lambda args=None, kwargs=None: calls.append((args, kwargs)) or FakeAsyncResult(),
        raising=False,
    )
    client = authenticated_client("one-time-operator@example.com", is_staff=True)

    first = client.post(f"/api/ingestion/failures/{failure.id}/replay/", {}, format="json")
    second = client.post(f"/api/ingestion/failures/{failure.id}/replay/", {}, format="json")

    assert first.status_code == 202
    assert second.status_code == 409
    assert calls == [([bill.id], {})]


@pytest.mark.django_db
def test_failed_dead_letter_replay_releases_the_failure_for_retry(monkeypatch):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 46",
        title="Retryable replay bill",
        status="Introduced",
    )
    failure = IngestionTaskFailure.objects.create(
        task_id="task-document-46",
        task_name="apps.ingestion.tasks.process_bill_versions",
        bill_id=bill.id,
        args_json={"args": [bill.id], "kwargs": {}},
        error_message="temporary Congress failure",
    )

    def fail_enqueue(*args, **kwargs):
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(
        views.process_bill_versions,
        "apply_async",
        fail_enqueue,
        raising=False,
    )

    response = authenticated_client("retry-operator@example.com", is_staff=True).post(
        f"/api/ingestion/failures/{failure.id}/replay/",
        {},
        format="json",
    )

    failure.refresh_from_db()
    assert response.status_code == 503
    assert failure.resolved_at is None


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
