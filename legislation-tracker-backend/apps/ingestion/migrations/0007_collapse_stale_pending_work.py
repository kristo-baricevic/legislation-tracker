from django.db import migrations
from django.db.models import Exists, OuterRef


def collapse_stale_pending_work(apps, schema_editor):
    work_item = apps.get_model("ingestion", "IngestionWorkItem")
    tracking_request = apps.get_model("ingestion", "BillTrackingRequest")
    while True:
        newer_revision = work_item.objects.filter(
            kind=OuterRef("kind"),
            dedupe_key=OuterRef("dedupe_key"),
            source_updated_at__gt=OuterRef("source_updated_at"),
        )
        stale_ids = list(
            work_item.objects.filter(status="pending", attempt_count=0)
            .exclude(kind="roll_call_vote")
            .annotate(has_newer_revision=Exists(newer_revision))
            .filter(has_newer_revision=True)
            .values_list("pk", flat=True)[:1000]
        )
        if not stale_ids:
            break
        referenced_ids = set(
            tracking_request.objects.filter(work_item_id__in=stale_ids).values_list(
                "work_item_id", flat=True
            )
        )
        for stale in work_item.objects.filter(pk__in=referenced_ids):
            replacement_id = (
                work_item.objects.filter(
                    kind=stale.kind,
                    dedupe_key=stale.dedupe_key,
                    source_updated_at__gt=stale.source_updated_at,
                )
                .order_by("-source_updated_at", "-id")
                .values_list("pk", flat=True)
                .first()
            )
            tracking_request.objects.filter(work_item_id=stale.pk).update(
                work_item_id=replacement_id
            )
        work_item.objects.filter(pk__in=stale_ids, status="pending", attempt_count=0).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("ingestion", "0006_rollcallingestionstate_and_dependencies"),
    ]

    operations = [
        migrations.RunPython(
            collapse_stale_pending_work,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
