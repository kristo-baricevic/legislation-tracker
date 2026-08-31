from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.ingestion import tasks
from apps.ingestion.models import IngestionWorkItem
from apps.legislation.models import Bill


@pytest.mark.django_db
def test_search_index_work_is_deduplicated_and_rebuilds_current_projection(monkeypatch):
    from apps.legislation.tasks import enqueue_search_index

    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 902",
        title="Search work bill",
        status="Introduced",
    )
    source_updated_at = timezone.now()
    first = enqueue_search_index(bill, source_updated_at=source_updated_at)
    second = enqueue_search_index(bill, source_updated_at=source_updated_at)
    observed: list[int] = []
    monkeypatch.setattr(
        "apps.legislation.search_index.rebuild_bill_search_index",
        lambda *, bill_id: (
            observed.append(bill_id)
            or SimpleNamespace(bill_id=bill_id, changed=True, chunk_count=1)
        ),
    )

    tasks._process_durable_work(first)

    assert first.pk == second.pk
    assert IngestionWorkItem.objects.filter(kind="search_index").count() == 1
    assert observed == [bill.id]


@pytest.mark.django_db
def test_stale_search_work_is_a_successful_noop(monkeypatch):
    from apps.legislation.tasks import enqueue_search_index

    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 903",
        title="Stale search work bill",
        status="Introduced",
    )
    old = enqueue_search_index(
        bill,
        source_updated_at=timezone.now() - timedelta(minutes=5),
    )
    observed: list[int] = []
    monkeypatch.setattr(
        "apps.legislation.search_index.rebuild_bill_search_index",
        lambda *, bill_id: observed.append(bill_id),
    )
    monkeypatch.setattr(
        "apps.legislation.search_index.latest_search_index_at",
        lambda *, bill_id: timezone.now(),
    )

    result = tasks._process_durable_work(old)

    assert result["stale"] is True
    assert observed == []
