from datetime import UTC, datetime

from django.db import migrations


def coalesce(apps, schema_editor):
    Work = apps.get_model("ingestion", "IngestionWorkItem")
    Tracking = apps.get_model("ingestion", "BillTrackingRequest")
    Failure = apps.get_model("ingestion", "IngestionTaskFailure")
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    winners, replacements = {}, {}
    # Preserve leases and terminal history; an in-flight legacy delivery
    # finishes normally. Similarity progress is checkpointed per bill.
    for row in Work.objects.select_for_update().filter(kind="similarity", status="pending").only(
            "id", "payload_json", "dedupe_key", "source_updated_at").order_by("-source_updated_at", "-id").iterator():
        bill = row.payload_json.get("bill_id")
        if not bill:
            continue
        if bill in winners:
            replacements[row.pk] = winners[bill].pk
        else:
            winners[bill] = row
            row.dedupe_key = f"bill:{bill}"
            row.source_updated_at = epoch
    ids = list(replacements)
    for start in range(0, len(ids), 500):
        chunk = ids[start:start+500]
        for model in (Tracking, Failure):
            for ref in model.objects.filter(work_item_id__in=chunk):
                ref.work_item_id = replacements[ref.work_item_id]
                ref.save(update_fields=["work_item"])
        Work.objects.filter(pk__in=chunk).delete()
    Work.objects.bulk_update(list(winners.values()), ["dedupe_key", "source_updated_at"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [("ingestion", "0008_discovery_run")]
    operations = [migrations.RunPython(coalesce, migrations.RunPython.noop)]
