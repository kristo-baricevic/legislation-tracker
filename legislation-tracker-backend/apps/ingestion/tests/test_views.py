from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import TrackedBill
from apps.ingestion import models as ingestion_models
from apps.ingestion import tasks as ingestion_tasks
from apps.ingestion import views
from apps.ingestion.congress_client import CongressAPIError
from apps.ingestion.models import (
    IngestionTaskFailure,
    IngestionWorkItem,
    IngestionWorkStatus,
)
from apps.legislation.models import Bill
from config.celery import _on_task_failure


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
def test_replayed_durable_failure_does_not_reappear_after_a_later_failure(monkeypatch):
    work = IngestionWorkItem.objects.create(
        kind="bill",
        dedupe_key="119-hr-99",
        source_updated_at="2026-08-19T00:00:00Z",
        payload_json={"bill_key": "119-hr-99"},
        status=IngestionWorkStatus.DEAD,
        attempt_count=5,
        last_error="first failure",
    )
    first_failure = IngestionTaskFailure.objects.create(
        task_id="task-first-99",
        task_name="process_ingestion_work_item",
        work_item=work,
        args_json={"args": [work.id], "kwargs": {}},
        error_message="first failure",
    )
    duplicate_failure = IngestionTaskFailure.objects.create(
        task_id="task-first-99-duplicate",
        task_name="process_ingestion_work_item",
        work_item=work,
        args_json={"args": [work.id], "kwargs": {}},
        error_message="duplicate first failure",
    )
    monkeypatch.setattr(
        views.dispatch_ingestion_work,
        "delay",
        lambda: FakeAsyncResult(),
    )
    client = authenticated_client("replay-history@example.com", is_staff=True)

    replayed = client.post(
        f"/api/ingestion/failures/{first_failure.id}/replay/",
        {},
        format="json",
    )
    assert replayed.status_code == 202

    first_failure.refresh_from_db()
    duplicate_failure.refresh_from_db()
    assert first_failure.resolved_at is not None
    assert duplicate_failure.resolved_at is not None
    work.status = IngestionWorkStatus.DEAD
    work.last_error = "second failure"
    work.save(update_fields=["status", "last_error"])
    second_failure = IngestionTaskFailure.objects.create(
        task_id="task-second-99",
        task_name="process_ingestion_work_item",
        work_item=work,
        args_json={"args": [work.id], "kwargs": {}},
        error_message="second failure",
    )

    listed = client.get("/api/ingestion/failures/")

    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["results"]] == [second_failure.id]
    stale_replay = client.post(
        f"/api/ingestion/failures/{duplicate_failure.id}/replay/",
        {},
        format="json",
    )
    work.refresh_from_db()
    assert stale_replay.status_code == 409
    assert work.status == IngestionWorkStatus.DEAD


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
        lambda args=None, kwargs=None: calls.append((args, kwargs))
        or FakeAsyncResult(),
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
        lambda args=None, kwargs=None: calls.append((args, kwargs))
        or FakeAsyncResult(),
    )

    listed = authenticated_client(is_staff=True).get("/api/ingestion/failures/")
    replayed = authenticated_client(
        "contract-operator@example.com", is_staff=True
    ).post(
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
def test_staff_can_replay_a_dead_lettered_representative_sync(monkeypatch):
    _on_task_failure(
        sender=SimpleNamespace(name="apps.ingestion.tasks.sync_representatives"),
        task_id="task-roster-sync",
        exception=CongressAPIError("Congress member endpoint unavailable"),
        args=(),
        kwargs={"congress": 119},
    )
    failure = IngestionTaskFailure.objects.get(task_id="task-roster-sync")
    calls = []
    monkeypatch.setattr(
        views.sync_representatives,
        "apply_async",
        lambda args=None, kwargs=None: calls.append((args, kwargs))
        or FakeAsyncResult(),
        raising=False,
    )
    client = authenticated_client("roster-replay-operator@example.com", is_staff=True)

    listed = client.get("/api/ingestion/failures/")
    replayed = client.post(
        f"/api/ingestion/failures/{failure.id}/replay/", {}, format="json"
    )

    failure.refresh_from_db()
    assert [item["id"] for item in listed.json()["results"]] == [failure.id]
    assert replayed.status_code == 202
    assert replayed.json()["task_name"] == "apps.ingestion.tasks.sync_representatives"
    assert failure.resolved_at is not None
    assert calls == [([], {"congress": 119})]


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
        lambda args=None, kwargs=None: calls.append((args, kwargs))
        or FakeAsyncResult(),
        raising=False,
    )
    client = authenticated_client("one-time-operator@example.com", is_staff=True)

    first = client.post(
        f"/api/ingestion/failures/{failure.id}/replay/", {}, format="json"
    )
    second = client.post(
        f"/api/ingestion/failures/{failure.id}/replay/", {}, format="json"
    )

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
def test_stage_replay_remains_recoverable_when_the_web_process_stops_after_claiming_it(
    monkeypatch,
):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 47",
        title="Crash-safe replay bill",
        status="Introduced",
    )
    failure = IngestionTaskFailure.objects.create(
        task_id="task-document-47",
        task_name="apps.ingestion.tasks.process_bill_versions",
        bill_id=bill.id,
        args_json={"args": [bill.id], "kwargs": {}},
        error_message="temporary Congress failure",
    )

    def stop_web_process(*args, **kwargs):
        raise SystemExit("web process stopped")

    monkeypatch.setattr(
        views.process_bill_versions,
        "apply_async",
        stop_web_process,
        raising=False,
    )
    client = authenticated_client("crash-replay-operator@example.com", is_staff=True)

    with pytest.raises(SystemExit, match="web process stopped"):
        client.post(f"/api/ingestion/failures/{failure.id}/replay/", {}, format="json")

    failure.refresh_from_db()
    assert failure.resolved_at is None
    assert failure.replay_claim_expires_at is not None

    failure.replay_claim_expires_at = timezone.now() - timedelta(seconds=1)
    failure.save(update_fields=["replay_claim_expires_at"])
    calls = []
    monkeypatch.setattr(
        views.process_bill_versions,
        "apply_async",
        lambda args=None, kwargs=None: calls.append((args, kwargs))
        or FakeAsyncResult(),
        raising=False,
    )

    response = client.post(
        f"/api/ingestion/failures/{failure.id}/replay/", {}, format="json"
    )

    failure.refresh_from_db()
    assert response.status_code == 202
    assert failure.resolved_at is not None
    assert calls == [([bill.id], {})]


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


@pytest.mark.django_db(transaction=True)
def test_staff_ingest_bill_persists_work_and_tracking_intent_when_broker_is_down(
    monkeypatch,
):
    monkeypatch.setattr(
        views.dispatch_ingestion_work,
        "delay",
        lambda: (_ for _ in ()).throw(RuntimeError("broker unavailable")),
    )
    client = authenticated_client("owner@example.com", is_staff=True)

    response = client.post(
        "/api/ingestion/bills/",
        {"congress": 119, "bill_type": "HR", "bill_number": "42"},
        format="json",
    )

    work = IngestionWorkItem.objects.get()
    request = ingestion_models.BillTrackingRequest.objects.get()
    assert response.status_code == 202
    assert response.json() == {
        "work_item_id": work.id,
        "status": "pending",
        "status_url": f"/api/ingestion/work/{work.id}/",
        "tracking_status": "pending",
        "bill_id": None,
    }
    assert (work.kind, work.dedupe_key, work.payload_json) == (
        "bill",
        "119-hr-42",
        {"bill_key": "119-hr-42"},
    )
    assert request.work_item_id == work.id
    assert request.user.email == "owner@example.com"
    assert request.status == "pending"
    assert not Bill.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_duplicate_manual_bill_requests_reuse_work_and_per_user_intent(monkeypatch):
    monkeypatch.setattr(
        views.dispatch_ingestion_work, "delay", lambda: FakeAsyncResult()
    )
    owner_client = authenticated_client("owner@example.com", is_staff=True)
    other_client = authenticated_client("other@example.com", is_staff=True)
    payload = {"congress": 119, "bill_type": "hr", "bill_number": "42"}

    first = owner_client.post("/api/ingestion/bills/", payload, format="json")
    duplicate = owner_client.post("/api/ingestion/bills/", payload, format="json")
    other_user = other_client.post("/api/ingestion/bills/", payload, format="json")

    assert first.status_code == duplicate.status_code == other_user.status_code == 202
    assert first.json()["work_item_id"] == duplicate.json()["work_item_id"]
    assert first.json()["work_item_id"] == other_user.json()["work_item_id"]
    assert IngestionWorkItem.objects.count() == 1
    assert ingestion_models.BillTrackingRequest.objects.count() == 2


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"congress": -1, "bill_type": "hr", "bill_number": "42"}, "congress"),
        ({"congress": 119, "bill_type": "hr", "bill_number": "   "}, "bill_number"),
        ({"congress": 119, "bill_type": "hr", "bill_number": "4A"}, "bill_number"),
        (
            {"congress": 119, "bill_type": "hr", "bill_number": "1" * 33},
            "bill_number",
        ),
    ],
)
def test_manual_bill_request_rejects_values_that_cannot_be_persisted(
    monkeypatch,
    payload,
    field,
):
    monkeypatch.setattr(
        views.dispatch_ingestion_work, "delay", lambda: FakeAsyncResult()
    )

    response = authenticated_client(is_staff=True).post(
        "/api/ingestion/bills/",
        payload,
        format="json",
    )

    assert response.status_code == 400
    assert field in response.json()
    assert not IngestionWorkItem.objects.exists()
    assert not ingestion_models.BillTrackingRequest.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_manual_bill_request_canonicalizes_numeric_bill_numbers(monkeypatch):
    monkeypatch.setattr(
        views.dispatch_ingestion_work, "delay", lambda: FakeAsyncResult()
    )
    client = authenticated_client(is_staff=True)

    first = client.post(
        "/api/ingestion/bills/",
        {"congress": 119, "bill_type": "HR", "bill_number": "00042"},
        format="json",
    )
    duplicate = client.post(
        "/api/ingestion/bills/",
        {"congress": 119, "bill_type": "hr", "bill_number": "42"},
        format="json",
    )

    assert first.status_code == duplicate.status_code == 202
    assert first.json()["work_item_id"] == duplicate.json()["work_item_id"]
    work = IngestionWorkItem.objects.get()
    tracking_request = ingestion_models.BillTrackingRequest.objects.get()
    assert work.dedupe_key == "119-hr-42"
    assert tracking_request.bill_number == "42"


@pytest.mark.django_db(transaction=True)
def test_manual_request_for_existing_bill_tracks_immediately(monkeypatch):
    monkeypatch.setattr(
        views.dispatch_ingestion_work, "delay", lambda: FakeAsyncResult()
    )
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 42",
        title="Shared public bill",
        status="Introduced",
    )
    client = authenticated_client("owner@example.com", is_staff=True)

    response = client.post(
        "/api/ingestion/bills/",
        {"congress": 119, "bill_type": "hr", "bill_number": "42"},
        format="json",
    )

    request = ingestion_models.BillTrackingRequest.objects.get()
    assert response.status_code == 202
    assert response.json()["tracking_status"] == "fulfilled"
    assert response.json()["bill_id"] == bill.id
    assert request.status == "fulfilled"
    assert request.fulfilled_at is not None
    assert request.bill_id == bill.id
    assert TrackedBill.objects.filter(user=request.user, bill=bill).exists()


@pytest.mark.django_db(transaction=True)
def test_repeated_manual_request_restores_tracking_after_the_user_untracks(monkeypatch):
    monkeypatch.setattr(
        views.dispatch_ingestion_work, "delay", lambda: FakeAsyncResult()
    )
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 42",
        title="Shared public bill",
        status="Introduced",
    )
    client = authenticated_client("owner@example.com", is_staff=True)
    payload = {"congress": 119, "bill_type": "hr", "bill_number": "42"}
    first = client.post("/api/ingestion/bills/", payload, format="json")
    tracking_request = ingestion_models.BillTrackingRequest.objects.get()
    TrackedBill.objects.get(user=tracking_request.user, bill=bill).delete()

    repeated = client.post("/api/ingestion/bills/", payload, format="json")

    tracking_request.refresh_from_db()
    assert first.status_code == repeated.status_code == 202
    assert repeated.json()["tracking_status"] == "fulfilled"
    assert repeated.json()["bill_id"] == bill.id
    assert TrackedBill.objects.filter(user=tracking_request.user, bill=bill).exists()


@pytest.mark.django_db(transaction=True)
def test_repeated_manual_request_requeues_succeeded_work_when_the_bill_is_missing(
    monkeypatch,
):
    monkeypatch.setattr(
        views.dispatch_ingestion_work, "delay", lambda: FakeAsyncResult()
    )
    client = authenticated_client("owner@example.com", is_staff=True)
    payload = {"congress": 119, "bill_type": "hr", "bill_number": "42"}
    accepted = client.post("/api/ingestion/bills/", payload, format="json")
    work = IngestionWorkItem.objects.get(pk=accepted.json()["work_item_id"])
    work.status = IngestionWorkStatus.SUCCEEDED
    work.attempt_count = 2
    work.completed_at = timezone.now()
    work.last_error = "old diagnostic"
    work.save(update_fields=["status", "attempt_count", "completed_at", "last_error"])

    repeated = client.post("/api/ingestion/bills/", payload, format="json")

    work.refresh_from_db()
    assert repeated.status_code == 202
    assert repeated.json()["status"] == "pending"
    assert repeated.json()["tracking_status"] == "pending"
    assert work.status == IngestionWorkStatus.PENDING
    assert work.attempt_count == 0
    assert work.completed_at is None
    assert work.last_error == ""


@pytest.mark.django_db(transaction=True)
def test_manual_ingestion_status_is_scoped_to_the_requesting_user(monkeypatch):
    monkeypatch.setattr(
        views.dispatch_ingestion_work, "delay", lambda: FakeAsyncResult()
    )
    owner_client = authenticated_client("owner@example.com", is_staff=True)
    other_client = authenticated_client("other@example.com", is_staff=True)
    accepted = owner_client.post(
        "/api/ingestion/bills/",
        {"congress": 119, "bill_type": "hr", "bill_number": "42"},
        format="json",
    )

    owner_status = owner_client.get(accepted.json()["status_url"])
    other_status = other_client.get(accepted.json()["status_url"])

    assert owner_status.status_code == 200
    assert owner_status.json() == {
        "work_item_id": accepted.json()["work_item_id"],
        "status": "pending",
        "attempt_count": 0,
        "last_error": "",
        "completed_at": None,
        "tracking_status": "pending",
        "bill_id": None,
    }
    assert other_status.status_code == 404


@pytest.mark.django_db(transaction=True)
def test_replayed_manual_bill_work_fulfills_the_original_tracking_request(monkeypatch):
    monkeypatch.setattr(
        views.dispatch_ingestion_work, "delay", lambda: FakeAsyncResult()
    )
    client = authenticated_client("owner@example.com", is_staff=True)
    accepted = client.post(
        "/api/ingestion/bills/",
        {"congress": 119, "bill_type": "hr", "bill_number": "42"},
        format="json",
    )
    work = IngestionWorkItem.objects.get(pk=accepted.json()["work_item_id"])
    work.status = IngestionWorkStatus.DEAD
    work.attempt_count = ingestion_tasks.MAX_INGESTION_WORK_ATTEMPTS
    work.last_error = "Congress unavailable"
    work.save(update_fields=["status", "attempt_count", "last_error"])
    failure = IngestionTaskFailure.objects.create(
        task_id="manual-bill-42",
        task_name="process_ingestion_work_item",
        work_item=work,
        args_json={"args": [work.id], "kwargs": {}},
        error_message="Congress unavailable",
    )
    monkeypatch.setattr(
        ingestion_tasks,
        "bill_detail",
        lambda congress, bill_type, bill_number: {
            "title": "Recovered bill",
            "latestAction": {
                "actionDate": "2026-08-31",
                "text": "Introduced",
            },
            "url": "https://api.congress.gov/v3/bill/119/hr/42",
        },
    )
    monkeypatch.setattr(
        ingestion_tasks, "_queue_bill_stage", lambda *args, **kwargs: None
    )

    replayed = client.post(
        f"/api/ingestion/failures/{failure.id}/replay/",
        {},
        format="json",
    )
    processed = ingestion_tasks.process_ingestion_work_item(work.id)

    work.refresh_from_db()
    request = ingestion_models.BillTrackingRequest.objects.get()
    bill = Bill.objects.get(session=119, bill_number="HR 42")
    assert replayed.status_code == 202
    assert processed == {"work_item_id": work.id, "status": "succeeded"}
    assert request.status == "fulfilled"
    assert request.bill_id == bill.id
    assert TrackedBill.objects.filter(user=request.user, bill=bill).exists()
    status_response = client.get(accepted.json()["status_url"])
    assert status_response.json()["status"] == "succeeded"
    assert status_response.json()["tracking_status"] == "fulfilled"
