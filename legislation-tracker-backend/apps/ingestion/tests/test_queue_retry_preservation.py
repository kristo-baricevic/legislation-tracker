from datetime import UTC, datetime, timedelta
from importlib import import_module

import pytest
from django.apps import apps
from django.utils import timezone

from apps.ingestion.models import IngestionWorkItem
from apps.ingestion.work_queue import persist_ingestion_work


@pytest.mark.django_db
@pytest.mark.parametrize("cleanup", ["migration", "runtime", "late"])
@pytest.mark.parametrize("newest_first", [False, True])
def test_cleanup_preserves_contextual_roll_call_payloads(
    cleanup, newest_first, monkeypatch
):
    from apps.congress.models import Representative, Vote
    from apps.ingestion import tasks
    from apps.legislation.models import Bill

    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 44",
        title="Vote cleanup",
        status="Introduced",
    )
    Representative.objects.create(
        bioguide_id="A000001",
        name="Test Member",
        chamber="house",
        party="I",
        state="VT",
    )
    payload = {
        "congress": 119,
        "chamber": "house",
        "session_number": 1,
        "roll_number": 44,
        "source_url": "",
    }
    old = IngestionWorkItem.objects.create(
        kind="roll_call_vote",
        dedupe_key="vote:119:house:1:44",
        source_updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        payload_json={**payload, "bill_id": bill.id},
    )
    if cleanup in {"migration", "late"}:
        IngestionWorkItem.objects.create(
            kind=old.kind,
            dedupe_key=old.dedupe_key,
            source_updated_at=datetime(2026, 1, 2, tzinfo=UTC),
            payload_json=payload,
        )
    if cleanup == "migration":
        import_module(
            "apps.ingestion.migrations.0007_collapse_stale_pending_work"
        ).collapse_stale_pending_work(apps, None)
    elif cleanup == "late":
        persist_ingestion_work(
            kind=old.kind,
            dedupe_key=old.dedupe_key,
            source_updated_at=old.source_updated_at,
            payload_json=old.payload_json,
        )
    else:
        persist_ingestion_work(
            kind=old.kind,
            dedupe_key=old.dedupe_key,
            source_updated_at=datetime(2026, 1, 2, tzinfo=UTC),
            payload_json=payload,
        )
    monkeypatch.setattr(
        tasks,
        "vote_detail",
        lambda *args, **kwargs: {
            "members": [{"bioguideId": "A000001", "position": "Yea"}],
            "date": "2026-01-01T12:00:00Z",
            "result": "Passed",
            "yeas": 1,
            "nays": 0,
        },
    )
    for work in IngestionWorkItem.objects.filter(kind="roll_call_vote").order_by(
        "-source_updated_at" if newest_first else "source_updated_at"
    ):
        tasks._process_roll_call_vote_impl(work)
    assert (
        Vote.objects.get(
            congress=119, chamber="house", session_number=1, roll_number=44
        ).bill_id
        == bill.id
    )


@pytest.mark.django_db
@pytest.mark.parametrize("cleanup", ["newer", "late", "migration"])
def test_cleanup_preserves_previously_attempted_pending_work(cleanup):
    retry_at = timezone.now() + timedelta(minutes=15)
    old = IngestionWorkItem.objects.create(
        kind="bill",
        dedupe_key="119-hr-900001",
        source_updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        payload_json={"bill_key": "119-hr-900001"},
        status="pending",
        attempt_count=3,
        last_error="provider unavailable",
        available_at=retry_at,
    )
    if cleanup != "newer":
        IngestionWorkItem.objects.create(
            kind="bill",
            dedupe_key=old.dedupe_key,
            source_updated_at=datetime(2026, 1, 3, tzinfo=UTC),
            payload_json=old.payload_json,
        )
    if cleanup == "migration":
        import_module(
            "apps.ingestion.migrations.0007_collapse_stale_pending_work"
        ).collapse_stale_pending_work(apps, None)
    else:
        persist_ingestion_work(
            kind="bill",
            dedupe_key=old.dedupe_key,
            source_updated_at=datetime(2026, 1, 2, tzinfo=UTC),
            payload_json=old.payload_json,
        )
    assert IngestionWorkItem.objects.filter(pk=old.pk).exists()
    old.refresh_from_db()
    assert old.attempt_count == 3
    assert old.available_at == retry_at
    assert old.last_error == "provider unavailable"
