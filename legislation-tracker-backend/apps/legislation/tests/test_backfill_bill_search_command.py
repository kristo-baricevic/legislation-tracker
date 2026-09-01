import pytest
from django.core.management import call_command

from apps.ingestion.models import IngestionWorkItem
from apps.legislation.models import Bill


@pytest.mark.django_db
def test_backfill_bill_search_previews_then_enqueues_only_when_executed(capsys):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 904",
        title="Backfill search bill",
        status="Introduced",
    )

    call_command("backfill_bill_search", congress=119)
    preview = capsys.readouterr().out
    assert "candidate=1" in preview
    assert not IngestionWorkItem.objects.filter(kind="search_index").exists()

    call_command("backfill_bill_search", congress=119, execute=True)

    assert list(
        IngestionWorkItem.objects.filter(kind="search_index").values_list(
            "payload_json", flat=True
        )
    ) == [{"bill_id": bill.id}]
