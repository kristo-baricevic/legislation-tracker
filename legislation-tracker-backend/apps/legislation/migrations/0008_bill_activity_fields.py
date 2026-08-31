from django.db import migrations, models


def backfill_bill_activity(apps, schema_editor):
    Bill = apps.get_model("legislation", "Bill")
    ChangeLog = apps.get_model("changelog", "ChangeLog")
    Clock = apps.get_model("changelog", "BillActivityClock")

    latest_by_bill = {}
    for event in ChangeLog.objects.order_by("created_at", "id").values(
        "bill_id", "created_at", "id"
    ):
        latest_by_bill[event["bill_id"]] = (event["created_at"], event["id"])

    sequence = 0
    for bill_id, (created_at, event_id) in sorted(
        latest_by_bill.items(), key=lambda item: (item[1][0], item[1][1], item[0])
    ):
        sequence += 1
        Bill.objects.filter(pk=bill_id).update(
            last_activity_at=created_at,
            last_activity_sequence=sequence,
        )

    Clock.objects.update_or_create(pk=1, defaults={"committed_sequence": sequence})


def clear_bill_activity(apps, schema_editor):
    Bill = apps.get_model("legislation", "Bill")
    Bill.objects.update(last_activity_at=None, last_activity_sequence=None)


class Migration(migrations.Migration):
    dependencies = [
        ("legislation", "0007_bill_enhancements"),
        ("changelog", "0004_bill_activity_clock"),
    ]

    operations = [
        migrations.AddField(
            model_name="bill",
            name="last_activity_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="bill",
            name="last_activity_sequence",
            field=models.BigIntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.RunPython(backfill_bill_activity, clear_bill_activity),
    ]
