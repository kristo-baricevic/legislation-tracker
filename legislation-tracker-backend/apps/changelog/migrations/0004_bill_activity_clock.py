from django.db import migrations, models


def create_activity_clock(apps, schema_editor):
    Clock = apps.get_model("changelog", "BillActivityClock")
    Clock.objects.get_or_create(pk=1, defaults={"committed_sequence": 0})


class Migration(migrations.Migration):
    dependencies = [
        ("changelog", "0003_partition_by_created_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="BillActivityClock",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("committed_sequence", models.BigIntegerField(default=0)),
            ],
            options={
                "db_table": "changelog_billactivityclock",
            },
        ),
        migrations.AddField(
            model_name="changelog",
            name="event_key",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddIndex(
            model_name="changelog",
            index=models.Index(
                fields=["bill", "event_key"], name="changelog_bill_event_key_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="billactivityclock",
            constraint=models.CheckConstraint(
                condition=models.Q(id=1),
                name="changelog_activity_clock_singleton",
            ),
        ),
        migrations.AddConstraint(
            model_name="billactivityclock",
            constraint=models.CheckConstraint(
                condition=models.Q(committed_sequence__gte=0),
                name="changelog_activity_clock_nonnegative",
            ),
        ),
        migrations.RunPython(create_activity_clock, migrations.RunPython.noop),
    ]
