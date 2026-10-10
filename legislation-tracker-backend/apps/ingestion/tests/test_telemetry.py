from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.ingestion import source_inventory, tasks
from apps.ingestion.models import IngestionRun, IngestionState, IngestionWorkItem
from apps.ingestion.run_tracking import claim_run, execute_discovery
from apps.ingestion.tests.test_views import authenticated_client
from apps.legislation.models import Bill


def work(key, status="pending", **kwargs):
    return IngestionWorkItem.objects.create(
        kind="bill",
        jurisdiction="federal",
        congress=119,
        dedupe_key=key,
        status=status,
        source_updated_at=kwargs.pop("source_updated_at", timezone.now()),
        **kwargs,
    )


@pytest.mark.django_db
def test_staff_reads_do_not_create_state_or_work_and_reject_scope():
    client = authenticated_client(is_staff=True)
    for path in ["telemetry", "source-readiness"]:
        assert APIClient().get(f"/api/ingestion/{path}/").status_code in [401, 403]
        assert (
            authenticated_client(f"member-{path}@example.com")
            .get(f"/api/ingestion/{path}/")
            .status_code
            == 403
        )
        assert (
            client.get(f"/api/ingestion/{path}/?jurisdiction=state").status_code == 400
        )
        assert client.get(f"/api/ingestion/{path}/?bill_types=hres").status_code == 400
        assert client.get(f"/api/ingestion/{path}/?congress=0").status_code == 400
    assert client.get("/api/ingestion/telemetry/").json()["discovery_run"] is None
    assert (
        client.get("/api/ingestion/source-readiness/").json()["ready_to_start"] is None
    )
    assert not IngestionRun.objects.exists()
    assert not IngestionState.objects.exists()
    assert not IngestionWorkItem.objects.exists()


@pytest.mark.django_db
def test_counts_are_scoped_and_latest_success_is_not_run_completion():
    now = timezone.now()
    work("119-hr-1", "processing", lease_expires_at=now - timedelta(minutes=1))
    work("119-hr-2", "pending", available_at=now + timedelta(minutes=1))
    work("119-hr-3", "succeeded", completed_at=now)
    IngestionWorkItem.objects.create(
        kind="bill",
        congress=118,
        dedupe_key="118-hr-1",
        source_updated_at=now,
        status="dead",
    )
    data = authenticated_client(is_staff=True).get("/api/ingestion/telemetry/").json()
    assert data["stale_leases"] == 1
    assert data["scheduled_pending"] == 1
    assert data["runnable_pending"] == 0
    assert data["last_successful_work_item_at"]
    assert data["discovery_run"] is None
    assert data["downstream_run_completion_available"] is False
    assert sum(row["count"] for row in data["counts_by_kind_and_status"]) == 3


@pytest.mark.django_db
def test_source_check_dedupes_conflicting_work_revisions_and_never_ingests(monkeypatch):
    pages = {
        "hr": [
            {"congress": 119, "type": "HR", "number": n} for n in [1, 2, 3, 4, 5, 6]
        ],
        "s": [],
    }
    monkeypatch.setattr(
        source_inventory,
        "_request",
        lambda method, path, params: {
            "bills": pages[path.split("/")[-1]],
            "pagination": {"count": len(pages[path.split("/")[-1]])},
        },
    )
    monkeypatch.setattr(
        tasks.poll_congress,
        "delay",
        lambda **kwargs: pytest.fail("scanner must not ingest"),
    )
    Bill.objects.create(
        session=119, bill_number="HR 1", jurisdiction="federal", title="Exists"
    )
    work("119-hr-2", "succeeded")
    work(
        "119-hr-2",
        "processing",
        source_updated_at=timezone.now() + timedelta(seconds=1),
    )
    work("119-hr-3", "dead")
    work("119-hr-4", "pending", available_at=timezone.now() + timedelta(minutes=10))
    work("119-hr-5", "blocked")
    before = IngestionWorkItem.objects.count()
    data = source_inventory.scan_inventory(119)
    assert data["complete"]
    assert data["missing_bill_metadata"] == 5
    assert data["missing_unqueued_metadata"] == 1
    assert data["ready_to_start"] is None
    assert IngestionWorkItem.objects.count() == before
    assert not IngestionState.objects.exists()


@pytest.mark.django_db
def test_incomplete_source_scan_and_stale_snapshot_are_unavailable(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("secret-api-key")

    monkeypatch.setattr(source_inventory, "_request", fail)
    data = source_inventory.scan_inventory(119)
    assert not data["complete"] and data["ready_to_start"] is None
    assert "secret" not in str(data)
    data.update(
        complete=True,
        ready_to_start=7,
        checked_completed_at=(timezone.now() - timedelta(minutes=6)).isoformat(),
    )
    cache.set(source_inventory.snapshot_key("federal", 119), data)
    result = (
        authenticated_client(is_staff=True)
        .get("/api/ingestion/source-readiness/")
        .json()
    )
    assert not result["available"] and result["ready_to_start"] is None
    assert source_inventory.snapshot_key(
        "federal", 119
    ) != source_inventory.snapshot_key("federal", 118)


@pytest.mark.django_db(transaction=True)
def test_start_is_coalesced_replayed_and_publication_failure_is_unknown(monkeypatch):
    calls = []
    monkeypatch.setattr(
        tasks.poll_congress,
        "delay",
        lambda **kwargs: calls.append(kwargs) or SimpleNamespace(id="task-1"),
    )
    client = authenticated_client(is_staff=True)
    first = client.post(
        "/api/ingestion/poll-congress/",
        {"congress": 119},
        format="json",
        HTTP_IDEMPOTENCY_KEY="key-1",
    )
    second = client.post(
        "/api/ingestion/poll-congress/",
        {"congress": 119},
        format="json",
        HTTP_IDEMPOTENCY_KEY="key-1",
    )
    third = client.post(
        "/api/ingestion/poll-congress/",
        {"congress": 119},
        format="json",
        HTTP_IDEMPOTENCY_KEY="key-2",
    )
    assert first.status_code == second.status_code == 202
    assert third.status_code == 409
    assert len(calls) == 1
    assert first.json()["run_id"] == third.json()["run_id"]
    assert (
        client.post(
            "/api/ingestion/poll-congress/",
            {"congress": 118},
            format="json",
            HTTP_IDEMPOTENCY_KEY="key-1",
        ).status_code
        == 400
    )
    # Beat uses the same claim and does not run a second discovery implementation.
    assert execute_discovery(
        lambda **kwargs: pytest.fail("duplicate scan"), "federal", 119
    )["coalesced"]
    IngestionRun.objects.update(status="succeeded")

    def fail_publish(**kwargs):
        raise RuntimeError("secret")

    monkeypatch.setattr(tasks.poll_congress, "delay", fail_publish)
    failed = client.post(
        "/api/ingestion/poll-congress/",
        {"congress": 119},
        format="json",
        HTTP_IDEMPOTENCY_KEY="key-3",
    )
    assert failed.status_code == 503
    assert "secret" not in str(failed.json())
    assert IngestionRun.objects.get(request_key="key-3").status == "unknown"


@pytest.mark.django_db
def test_abandoned_claim_is_unknown_and_discovery_completion_is_explicit():
    old, _ = claim_run("federal", 119, "old")
    IngestionRun.objects.filter(pk=old.pk).update(
        lease_expires_at=timezone.now() - timedelta(seconds=1)
    )
    new, created = claim_run("federal", 119, "new")
    assert created
    old.refresh_from_db()
    assert old.status == "unknown"
    execute_discovery(
        lambda **kwargs: {"discovered": 3, "created": 2}, "federal", 119, new.id
    )
    new.refresh_from_db()
    assert new.status == "succeeded" and new.finished_at
    assert new.discovered_count == 3


@pytest.mark.django_db
def test_expired_idempotency_replay_never_enqueues_again(monkeypatch):
    old, _ = claim_run("federal", 119, "old")
    IngestionRun.objects.filter(pk=old.pk).update(
        lease_expires_at=timezone.now() - timedelta(seconds=1)
    )
    monkeypatch.setattr(
        tasks.poll_congress,
        "delay",
        lambda **kwargs: pytest.fail("expired replay must not enqueue"),
    )
    response = authenticated_client(is_staff=True).post(
        "/api/ingestion/poll-congress/",
        {"congress": 119},
        format="json",
        HTTP_IDEMPOTENCY_KEY="old",
    )
    assert response.json()["status"] == "unknown"
    assert (
        authenticated_client("other@example.com", is_staff=True)
        .post("/api/ingestion/poll-congress/", {"congress": 119.9}, format="json")
        .status_code
        == 400
    )


@pytest.mark.django_db
def test_revoked_discovery_claim_cannot_write_cursor_or_work(monkeypatch):
    run, _ = claim_run("federal", 119, "revoked")

    def page(*args, **kwargs):
        if args[1] == "s":
            IngestionRun.objects.filter(pk=run.pk).update(status="unknown")
            return []
        return [
            {
                "congress": 119,
                "type": "hr",
                "number": "1",
                "updateDate": "2026-10-09T00:00:00Z",
            }
        ]

    monkeypatch.setattr(tasks, "bill_list", page)
    monkeypatch.setattr(
        tasks.dispatch_ingestion_work,
        "delay",
        lambda: pytest.fail("revoked claim must not dispatch"),
    )
    with pytest.raises(RuntimeError):
        execute_discovery(tasks._poll_congress_impl, "federal", 119, run.id)
    assert not IngestionWorkItem.objects.exists()
    assert IngestionState.objects.get(congress=119).last_polled_at is None


@pytest.mark.django_db(transaction=True)
def test_rollback_never_publishes_claim(monkeypatch):
    from django.db import transaction

    client = authenticated_client(is_staff=True)
    calls = []
    monkeypatch.setattr(
        tasks.poll_congress, "delay", lambda **kwargs: calls.append(kwargs)
    )
    with pytest.raises(RuntimeError), transaction.atomic():
        assert (
            client.post(
                "/api/ingestion/poll-congress/", {"congress": 119}, format="json"
            ).status_code
            == 202
        )
        assert calls == []
        raise RuntimeError("rollback")
    assert calls == [] and not IngestionRun.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_postgres_concurrent_manual_and_beat_claims_share_one_scope():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import connection, connections

    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locking")
    barrier = Barrier(2)

    def claim(trigger):
        try:
            barrier.wait(timeout=5)
            return claim_run(
                "federal", 119, "manual" if trigger == "manual" else None, trigger
            )
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim, trigger) for trigger in ["manual", "scheduled"]]
        result = [future.result(timeout=10) for future in futures]
    assert len({str(row.id) for row, _ in result}) == 1
    assert sum(created for _, created in result) == 1


@pytest.mark.django_db(transaction=True)
def test_postgres_concurrent_cross_scope_key_conflict_is_controlled():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import connection, connections

    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL uniqueness race")
    barrier = Barrier(2)

    def claim(congress):
        try:
            barrier.wait(timeout=5)
            try:
                return claim_run("federal", congress, "same-global-key")[1]
            except ValueError:
                return "conflict"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim, c) for c in [118, 119]]
        result = [future.result(timeout=10) for future in futures]
    assert sorted(map(str, result)) == ["True", "conflict"]


@pytest.mark.django_db
def test_repeated_source_pages_are_incomplete_not_ready(monkeypatch):
    page = [
        {"congress": 119, "type": "HR", "number": number} for number in range(1, 251)
    ]
    monkeypatch.setattr(
        source_inventory,
        "_request",
        lambda *args, **kwargs: {"bills": page, "pagination": {"count": 500}},
    )
    monkeypatch.setattr(source_inventory.time, "sleep", lambda _: None)
    data = source_inventory.scan_inventory(119)
    assert not data["complete"] and data["ready_to_start"] is None
    assert data["error_code"] == "source_inventory_changed"


@pytest.mark.django_db
def test_empty_complete_inventory_is_real_zero_and_rate_limit_is_unknown(monkeypatch):
    from apps.ingestion.congress_client import CongressAPIError

    monkeypatch.setattr(
        source_inventory,
        "_request",
        lambda *args, **kwargs: {"bills": [], "pagination": {"count": 0}},
    )
    data = source_inventory.scan_inventory(119)
    assert data["complete"] and data["missing_unqueued_metadata"] == 0
    assert data["ready_to_start"] is None

    def limited(*args, **kwargs):
        raise CongressAPIError("secret-key", status_code=429, retry_after_seconds=620)

    monkeypatch.setattr(source_inventory, "_request", limited)
    data = source_inventory.scan_inventory(119)
    assert not data["complete"] and data["ready_to_start"] is None
    assert "secret" not in str(data)
    assert data["retry_after_seconds"] == 620


@pytest.mark.django_db
@pytest.mark.parametrize(
    "stamp", [None, "invalid", "2026-01-01T00:00:00", "2999-01-01T00:00:00+00:00"]
)
def test_invalid_readiness_timestamp_is_unavailable(stamp):
    cache.set(
        source_inventory.snapshot_key("federal", 119),
        {
            "complete": True,
            "checked_completed_at": stamp,
            "missing_unqueued_metadata": 9,
            "missing_bill_metadata": 9,
            "already_scheduled_or_blocked": 0,
        },
    )
    response = authenticated_client(is_staff=True).get(
        "/api/ingestion/source-readiness/"
    )
    assert response.status_code == 200
    data = response.json()
    assert not data["available"] and data["age_seconds"] is None
    assert data["missing_unqueued_metadata"] is None
    assert data["missing_bill_metadata"] is None
    assert data["ready_to_start"] is None


@pytest.mark.django_db
def test_historical_inventory_gap_does_not_claim_incremental_readiness(monkeypatch):
    cursor = timezone.now()
    state = IngestionState.objects.create(
        jurisdiction="federal", congress=119, last_bill_update_seen_at=cursor
    )
    old = (cursor - timedelta(days=30)).isoformat()
    monkeypatch.setattr(
        source_inventory,
        "_request",
        lambda method, path, params: {
            "bills": [{"congress": 119, "type": "HR", "number": "7", "updateDate": old}]
            if path.endswith("hr")
            else [],
            "pagination": {"count": 1 if path.endswith("hr") else 0},
        },
    )
    snapshot = source_inventory.scan_inventory(119)
    assert snapshot["missing_unqueued_metadata"] == 1
    assert snapshot["ready_to_start"] is None
    assert not snapshot["incremental_discoverable_count_available"]

    def incremental(congress, bill_type, **kwargs):
        assert kwargs["from_date_time"] == (cursor - timedelta(minutes=5)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        return []  # synthetic provider honors the retained cursor; older gap is omitted

    monkeypatch.setattr(tasks, "bill_list", incremental)
    monkeypatch.setattr(tasks.dispatch_ingestion_work, "delay", lambda: None)
    result = tasks._poll_congress_impl("federal", 119)
    assert result["created"] == 0 and not IngestionWorkItem.objects.exists()
    state.refresh_from_db()
    assert state.last_bill_update_seen_at == cursor
