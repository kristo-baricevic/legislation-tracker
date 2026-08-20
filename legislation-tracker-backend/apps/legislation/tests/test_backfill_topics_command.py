import pytest
from django.core.management import call_command

from apps.ingestion import tasks as ingestion_tasks
from apps.ingestion.models import IngestionWorkItem
from apps.legislation.management.commands import backfill_topics
from apps.legislation.models import Bill


@pytest.mark.django_db
def test_backfill_topics_persists_work_before_waking_celery(monkeypatch):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 1",
        title="Health bill",
        status="Introduced",
    )
    monkeypatch.setattr(ingestion_tasks.dispatch_ingestion_work, "delay", lambda: None)
    monkeypatch.setattr(
        backfill_topics.update_topics,
        "apply_async",
        lambda *args, **kwargs: pytest.fail(
            "backfill work must be persisted before any broker publish"
        ),
    )

    call_command("backfill_topics", session=119)

    assert list(
        IngestionWorkItem.objects.filter(kind="topic_update").values_list(
            "payload_json", flat=True
        )
    ) == [{"bill_id": bill.id}]
