# Generated manually for Phase 2 (normal table; partitioning can be added later)

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("legislation", "0002_bill_latest_contract"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChangeLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("change_type", models.CharField(db_index=True, max_length=50)),
                ("old_value", models.JSONField(blank=True, null=True)),
                ("new_value", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "bill",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="changelog_entries",
                        to="legislation.bill",
                    ),
                ),
                (
                    "contract",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="changelog_entries",
                        to="legislation.billcontract",
                    ),
                ),
                (
                    "document",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="changelog_entries",
                        to="legislation.billdocument",
                    ),
                ),
            ],
            options={
                "db_table": "changelog_changelog",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="changelog",
            index=models.Index(fields=["-created_at"], name="changelog_c_created_2a3b4c_idx"),
        ),
        migrations.AddIndex(
            model_name="changelog",
            index=models.Index(fields=["bill"], name="changelog_c_bill_id_5d6e7f_idx"),
        ),
        migrations.AddIndex(
            model_name="changelog",
            index=models.Index(fields=["change_type"], name="changelog_c_change_8f9a0b_idx"),
        ),
        migrations.AddIndex(
            model_name="changelog",
            index=models.Index(fields=["-created_at", "bill"], name="changelog_created_bill_idx"),
        ),
    ]
