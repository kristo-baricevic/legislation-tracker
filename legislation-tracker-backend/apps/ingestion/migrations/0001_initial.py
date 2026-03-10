# Generated manually for Phase 2

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="IngestionState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("jurisdiction", models.CharField(default="federal", max_length=20)),
                ("congress", models.PositiveIntegerField()),
                ("last_polled_at", models.DateTimeField(blank=True, null=True)),
                ("last_bill_update_seen_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "db_table": "ingestion_ingestionstate",
            },
        ),
        migrations.AddConstraint(
            model_name="ingestionstate",
            constraint=models.UniqueConstraint(
                fields=("jurisdiction", "congress"),
                name="ingestion_state_jurisdiction_congress_uniq",
            ),
        ),
    ]
