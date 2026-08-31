import pytest
from django.core.management import call_command

from apps.ingestion.models import IngestionWorkItem
from apps.legislation.models import Bill


@pytest.mark.django_db
def test_representative_insights_backfill_is_preview_first(capsys):
    Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 1",
        title="One",
        status="Introduced",
    )

    call_command("backfill_representative_insights", congress=119)

    assert "Preview only" in capsys.readouterr().out
    assert not IngestionWorkItem.objects.exists()


@pytest.mark.django_db
def test_representative_insights_backfill_queues_relationship_work(monkeypatch):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 2",
        title="Two",
        status="Introduced",
    )
    monkeypatch.setattr(
        "apps.congress.management.commands.backfill_representative_insights.current_congress",
        lambda: 119,
    )
    monkeypatch.setattr("apps.ingestion.tasks.dispatch_ingestion_work.delay", lambda: None)

    call_command("backfill_representative_insights", congress=119, execute=True)

    assert IngestionWorkItem.objects.get().payload_json == {"bill_id": bill.id}
