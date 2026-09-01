from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ingestion", "0005_billtrackingrequest")]

    operations = [
        migrations.AddField(
            model_name="ingestionworkitem",
            name="dependency_keys",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AlterField(
            model_name="ingestionworkitem",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("dispatched", "Dispatched"),
                    ("processing", "Processing"),
                    ("blocked", "Blocked"),
                    ("succeeded", "Succeeded"),
                    ("dead", "Dead"),
                ],
                db_index=True,
                default="pending",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="RollCallIngestionState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("congress", models.PositiveSmallIntegerField()),
                ("chamber", models.CharField(max_length=16)),
                ("session_number", models.PositiveSmallIntegerField()),
                ("next_page_or_roll", models.CharField(blank=True, default="", max_length=255)),
                ("discovered_roll_count", models.PositiveIntegerField(default=0)),
                ("source_exhausted_at", models.DateTimeField(blank=True, null=True)),
                ("source_updated_at", models.DateTimeField(blank=True, null=True)),
                ("last_polled_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"db_table": "ingestion_rollcallingestionstate"},
        ),
        migrations.AddConstraint(
            model_name="rollcallingestionstate",
            constraint=models.UniqueConstraint(
                fields=("congress", "chamber", "session_number"),
                name="ingest_roll_state_scope_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="rollcallingestionstate",
            index=models.Index(
                fields=["congress", "chamber", "session_number"],
                name="ingest_roll_state_scope_idx",
            ),
        ),
    ]
