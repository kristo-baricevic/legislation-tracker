from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("ingestion", "0004_ingestiontaskfailure_replay_claim"),
        ("legislation", "0007_bill_enhancements"),
    ]

    operations = [
        migrations.CreateModel(
            name="BillTrackingRequest",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("jurisdiction", models.CharField(default="federal", max_length=20)),
                ("congress", models.PositiveIntegerField()),
                ("bill_type", models.CharField(max_length=10)),
                ("bill_number", models.CharField(max_length=32)),
                (
                    "status",
                    models.CharField(
                        choices=[("pending", "Pending"), ("fulfilled", "Fulfilled")],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("fulfilled_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "bill",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="tracking_requests",
                        to="legislation.bill",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bill_tracking_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "work_item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="tracking_requests",
                        to="ingestion.ingestionworkitem",
                    ),
                ),
            ],
            options={
                "db_table": "ingestion_billtrackingrequest",
                "indexes": [
                    models.Index(
                        fields=[
                            "status",
                            "jurisdiction",
                            "congress",
                            "bill_type",
                            "bill_number",
                        ],
                        name="ingest_track_pending_bill_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=(
                            "user",
                            "jurisdiction",
                            "congress",
                            "bill_type",
                            "bill_number",
                        ),
                        name="ingest_tracking_request_user_bill_uniq",
                    )
                ],
            },
        )
    ]
