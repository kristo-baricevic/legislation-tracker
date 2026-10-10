from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.ingestion import congress_client, tasks
from apps.ingestion import discoverable_readiness as readiness
from apps.ingestion.models import IngestionState, IngestionWorkItem
from apps.ingestion.source_inventory import snapshot_key
from apps.ingestion.tests.test_telemetry import work
from apps.ingestion.tests.test_views import authenticated_client
from apps.legislation.models import Bill


def provider(monkeypatch, items, calls=None):
    def page(method, path, params):
        assert method == "GET"
        if calls is not None:
            calls.append(params.copy())
        rows = [row for row in items if row["type"].lower() == path.split("/")[-1]]
        if params.get("fromDateTime"):
            boundary = readiness._parse_congress_update_datetime(params["fromDateTime"])
            rows = [
                row
                for row in rows
                if not row.get("updateDate")
                or readiness._parse_congress_update_datetime(row["updateDate"])
                >= boundary
            ]
        return {"bills": rows, "pagination": {"count": len(rows)}}

    monkeypatch.setattr(readiness, "_request", page)
    monkeypatch.setattr(congress_client, "_request", page)
    monkeypatch.setattr(congress_client, "_throttle", lambda: None)
    monkeypatch.setattr(tasks.dispatch_ingestion_work, "delay", lambda: None)


@pytest.mark.django_db
def test_count_matches_actual_poll_revision_creation_not_metadata_or_status(
    monkeypatch,
):
    now = timezone.now().replace(microsecond=0)
    IngestionState.objects.create(
        jurisdiction="federal", congress=119, last_bill_update_seen_at=now
    )
    rows = [
        {"congress": 119, "type": "HR", "number": str(n), "updateDate": now.isoformat()}
        for n in range(1, 7)
    ]
    rows += [{"congress": 119, "type": "S", "number": "1"}]
    work("119-hr-1", "pending", source_updated_at=now)
    work("119-hr-2", "dead", source_updated_at=now)
    work("119-hr-3", "succeeded", source_updated_at=now + timedelta(seconds=1))
    work("119-hr-4", "processing", source_updated_at=now - timedelta(seconds=1))
    Bill.objects.create(
        session=119, jurisdiction="federal", bill_number="HR 5", title="Metadata exists"
    )
    calls = []
    provider(monkeypatch, rows, calls)
    before = IngestionWorkItem.objects.count()
    result = readiness.observe_discoverable(119)
    assert (
        result["ready_to_start"] == 4
    )  # newer active revision, metadata-only, new identity, unknown-date identity
    assert result["incremental_discoverable_count_available"]
    assert IngestionWorkItem.objects.count() == before
    assert all(
        row["fromDateTime"]
        == (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for row in calls
    )
    actual = tasks._poll_congress_impl("federal", 119)
    assert actual["created"] == result["ready_to_start"]


@pytest.mark.django_db
def test_retained_cursor_excludes_historical_gap_and_returns_real_zero(monkeypatch):
    now = timezone.now().replace(microsecond=0)
    state = IngestionState.objects.create(
        jurisdiction="federal", congress=119, last_bill_update_seen_at=now
    )
    provider(
        monkeypatch,
        [
            {
                "congress": 119,
                "type": "HR",
                "number": "77",
                "updateDate": (now - timedelta(days=30)).isoformat(),
            }
        ],
    )
    result = readiness.observe_discoverable(119)
    assert result["ready_to_start"] == 0 and result["discovery_source_complete"]
    assert result["discovery_basis"]["cursor_at"] == now.isoformat()
    state.refresh_from_db()
    assert state.last_bill_update_seen_at == now
    assert not IngestionWorkItem.objects.exists()


@pytest.mark.django_db
def test_no_cursor_and_unknown_date_exact_revision_use_poll_semantics(monkeypatch):
    work("119-hr-1", "dead", source_updated_at=readiness.UNKNOWN_SOURCE_UPDATED_AT)
    provider(
        monkeypatch,
        [
            {"congress": 119, "type": "HR", "number": "1"},
            {"congress": 119, "type": "HR", "number": "2", "updateDate": "malformed"},
        ],
    )
    result = readiness.observe_discoverable(119)
    assert result["ready_to_start"] == 1
    assert result["discovery_basis"]["from_date_time"] is None
    assert not IngestionState.objects.exists()
    assert tasks._poll_congress_impl("federal", 119)["created"] == 1


@pytest.mark.django_db
@pytest.mark.parametrize("change", ["cursor", "work", "timestamp"])
def test_cached_count_invalidates_when_observation_basis_changes(monkeypatch, change):
    now = timezone.now()
    state = IngestionState.objects.create(
        jurisdiction="federal", congress=119, last_bill_update_seen_at=now
    )
    provider(monkeypatch, [])
    snapshot = {
        "complete": True,
        "checked_completed_at": now.isoformat(),
        "missing_unqueued_metadata": 8,
        **readiness.observe_discoverable(119),
    }
    cache.set(snapshot_key("federal", 119), snapshot)
    client = authenticated_client(is_staff=True)
    assert client.get("/api/ingestion/source-readiness/").json()["ready_to_start"] == 0
    if change == "cursor":
        IngestionState.objects.filter(pk=state.pk).update(
            last_bill_update_seen_at=now + timedelta(seconds=1)
        )
    elif change == "work":
        work("119-hr-88", "dead")
    else:
        snapshot["discovery_checked_completed_at"] = "2999-01-01T00:00:00+00:00"
        cache.set(snapshot_key("federal", 119), snapshot)
    result = client.get("/api/ingestion/source-readiness/").json()
    assert (
        result["ready_to_start"] is None
        and not result["incremental_discoverable_count_available"]
    )
    assert (
        result["missing_unqueued_metadata"] == 8
    )  # separate historical inventory observation


@pytest.mark.django_db
def test_incomplete_coverage_and_mid_scan_basis_change_return_unknown(monkeypatch):
    monkeypatch.setattr(
        readiness,
        "_request",
        lambda *args, **kwargs: {"bills": [], "pagination": {"count": 1}},
    )
    result = readiness.observe_discoverable(119)
    assert result["ready_to_start"] is None and not result["discovery_source_complete"]

    def racing(*args, **kwargs):
        if not IngestionState.objects.exists():
            IngestionState.objects.create(
                jurisdiction="federal",
                congress=119,
                last_bill_update_seen_at=timezone.now(),
            )
        return {"bills": [], "pagination": {"count": 0}}

    monkeypatch.setattr(readiness, "_request", racing)
    result = readiness.observe_discoverable(119)
    assert result["discovery_error_code"] == "discovery_basis_changed"
    assert result["ready_to_start"] is None
