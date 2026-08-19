from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("ingestion", "0002_ingestiontaskfailure"),
    ]

    operations = [
        migrations.CreateModel(
            name="IngestionWorkItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(max_length=64)),
                ("dedupe_key", models.CharField(max_length=255)),
                ("jurisdiction", models.CharField(default="federal", max_length=20)),
                ("congress", models.PositiveIntegerField(blank=True, null=True)),
                ("source_updated_at", models.DateTimeField()),
                ("payload_json", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("dispatched", "Dispatched"), ("processing", "Processing"), ("succeeded", "Succeeded"), ("dead", "Dead")], db_index=True, default="pending", max_length=20)),
                ("attempt_count", models.PositiveIntegerField(default=0)),
                ("available_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("lease_expires_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("celery_task_id", models.CharField(blank=True, default="", max_length=255)),
                ("dispatch_token", models.CharField(blank=True, default="", max_length=32)),
                ("last_error", models.TextField(blank=True, default="")),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "ingestion_ingestionworkitem",
                "ordering": ["available_at", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="ingestionworkitem",
            constraint=models.UniqueConstraint(fields=("kind", "dedupe_key", "source_updated_at"), name="ingestion_work_item_source_version_uniq"),
        ),
        migrations.AddIndex(
            model_name="ingestionworkitem",
            index=models.Index(fields=["status", "available_at"], name="ingest_work_status_avail_idx"),
        ),
        migrations.AddField(
            model_name="ingestiontaskfailure",
            name="last_replayed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="ingestiontaskfailure",
            name="replay_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="ingestiontaskfailure",
            name="resolved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="ingestiontaskfailure",
            name="work_item",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="failures", to="ingestion.ingestionworkitem"),
        ),
    ]
