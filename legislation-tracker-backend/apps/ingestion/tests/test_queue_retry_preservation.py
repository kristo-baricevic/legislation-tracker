from datetime import UTC, datetime, timedelta
from importlib import import_module

import pytest
from django.apps import apps
from django.utils import timezone

from apps.ingestion.models import IngestionWorkItem
from apps.ingestion.work_queue import persist_ingestion_work


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
