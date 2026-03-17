# Generated for Phase 3 dead-letter logging

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ingestion", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="IngestionTaskFailure",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("task_id", models.CharField(db_index=True, max_length=255)),
                ("bill_id", models.PositiveIntegerField(blank=True, db_index=True, null=True)),
                ("task_name", models.CharField(max_length=255)),
                ("args_json", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                "db_table": "ingestion_ingestiontaskfailure",
                "ordering": ["-created_at"],
            },
        ),
    ]
