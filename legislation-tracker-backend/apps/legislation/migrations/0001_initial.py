# Generated manually for Phase 2

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("congress", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Topic",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("slug", models.SlugField(max_length=100, unique=True)),
                ("description", models.TextField(blank=True, null=True)),
            ],
            options={
                "db_table": "legislation_topic",
            },
        ),
        migrations.CreateModel(
            name="Bill",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("jurisdiction", models.CharField(max_length=20)),
                ("session", models.IntegerField(db_index=True)),
                ("bill_number", models.CharField(db_index=True, max_length=50)),
                ("title", models.TextField()),
                ("summary", models.TextField(blank=True, null=True)),
                ("status", models.CharField(max_length=100)),
                (
                    "processing_status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("processing", "Processing"),
                            ("complete", "Complete"),
                            ("failed", "Failed"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("introduced_at", models.DateField(blank=True, null=True)),
                ("last_action_at", models.DateTimeField(blank=True, null=True)),
                ("source_api_id", models.CharField(blank=True, max_length=255, null=True)),
                ("raw_text_url", models.URLField(blank=True, max_length=1024, null=True)),
                ("pdf_url", models.URLField(blank=True, max_length=1024, null=True)),
                ("metadata_hash", models.CharField(blank=True, db_index=True, max_length=64, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "sponsor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="sponsored_bills",
                        to="congress.representative",
                    ),
                ),
            ],
            options={
                "db_table": "legislation_bill",
            },
        ),
        migrations.CreateModel(
            name="BillDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("version_label", models.CharField(max_length=50)),
                ("is_active_version", models.BooleanField(db_index=True, default=False)),
                ("object_storage_key", models.CharField(blank=True, max_length=512, null=True)),
                ("content_type", models.CharField(blank=True, max_length=128, null=True)),
                ("file_size_bytes", models.PositiveIntegerField(blank=True, null=True)),
                ("source_url", models.URLField(blank=True, max_length=1024, null=True)),
                ("raw_text", models.TextField(blank=True, null=True)),
                ("extracted_text", models.TextField(blank=True, null=True)),
                ("content_hash", models.CharField(blank=True, db_index=True, max_length=64, null=True)),
                ("downloaded_at", models.DateTimeField(blank=True, null=True)),
                ("parsed_at", models.DateTimeField(blank=True, null=True)),
                ("contract_generated_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "bill",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="documents",
                        to="legislation.bill",
                    ),
                ),
            ],
            options={
                "db_table": "legislation_billdocument",
            },
        ),
        migrations.CreateModel(
            name="BillContract",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("schema_version", models.CharField(default="1.0", max_length=20)),
                ("contract_json", models.JSONField(default=dict)),
                ("contract_hash", models.CharField(db_index=True, max_length=64)),
                ("computed_at", models.DateTimeField(auto_now_add=True)),
                (
                    "bill",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="contracts",
                        to="legislation.bill",
                    ),
                ),
                (
                    "document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="contracts",
                        to="legislation.billdocument",
                    ),
                ),
            ],
            options={
                "db_table": "legislation_billcontract",
            },
        ),
        migrations.AddConstraint(
            model_name="bill",
            constraint=models.UniqueConstraint(
                fields=("session", "bill_number"),
                name="legislation_bill_session_number_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="bill",
            index=models.Index(fields=["-updated_at"], name="legislation__updated_7c8e1a_idx"),
        ),
        migrations.AddIndex(
            model_name="bill",
            index=models.Index(fields=["processing_status"], name="legislation__process_2b4f1c_idx"),
        ),
        migrations.AddConstraint(
            model_name="billdocument",
            constraint=models.UniqueConstraint(
                fields=("bill", "version_label"),
                name="legislation_billdocument_bill_version_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="billdocument",
            index=models.Index(fields=["bill"], name="legislation__bill_id_9a2b3c_idx"),
        ),
        migrations.AddIndex(
            model_name="billdocument",
            index=models.Index(fields=["version_label"], name="legislation__version_4d5e6f_idx"),
        ),
        migrations.AddIndex(
            model_name="billdocument",
            index=models.Index(fields=["bill", "is_active_version"], name="legislation__bill_id_7e8f9a_idx"),
        ),
        migrations.AddIndex(
            model_name="billcontract",
            index=models.Index(fields=["bill"], name="legislation__bill_id_1a2b3c_idx"),
        ),
        migrations.AddIndex(
            model_name="billcontract",
            index=models.Index(fields=["contract_hash"], name="legislation__contract_4d5e6f_idx"),
        ),
        migrations.AddIndex(
            model_name="billcontract",
            index=models.Index(fields=["bill", "-computed_at"], name="legislation__bill_id_7e8f0a_idx"),
        ),
        migrations.CreateModel(
            name="EvidenceSpan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("field_path", models.CharField(max_length=255)),
                ("start_char", models.PositiveIntegerField()),
                ("end_char", models.PositiveIntegerField()),
                ("quoted_text", models.TextField()),
                ("page_number", models.PositiveIntegerField(blank=True, null=True)),
                (
                    "bill",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="evidence_spans",
                        to="legislation.bill",
                    ),
                ),
                (
                    "contract",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="evidence_spans",
                        to="legislation.billcontract",
                    ),
                ),
                (
                    "document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="evidence_spans",
                        to="legislation.billdocument",
                    ),
                ),
            ],
            options={
                "db_table": "legislation_evidencespan",
            },
        ),
        migrations.CreateModel(
            name="BillTopic",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("confidence_score", models.FloatField(blank=True, null=True)),
                (
                    "bill",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bill_topics",
                        to="legislation.bill",
                    ),
                ),
                (
                    "topic",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bill_topics",
                        to="legislation.topic",
                    ),
                ),
            ],
            options={
                "db_table": "legislation_billtopic",
            },
        ),
        migrations.CreateModel(
            name="BillSimilarity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("similarity_score", models.FloatField()),
                ("method", models.CharField(max_length=50)),
                ("computed_at", models.DateTimeField(auto_now_add=True)),
                (
                    "bill_a",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="similarity_as_a",
                        to="legislation.bill",
                    ),
                ),
                (
                    "bill_b",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="similarity_as_b",
                        to="legislation.bill",
                    ),
                ),
            ],
            options={
                "db_table": "legislation_billsimilarity",
            },
        ),
        migrations.AddIndex(
            model_name="evidencespan",
            index=models.Index(fields=["contract"], name="legislation__contract_1b2c3d_idx"),
        ),
        migrations.AddIndex(
            model_name="evidencespan",
            index=models.Index(fields=["bill"], name="legislation__bill_id_4e5f6a_idx"),
        ),
        migrations.AddIndex(
            model_name="billtopic",
            index=models.Index(fields=["topic"], name="legislation__topic_i_8a9b0c_idx"),
        ),
        migrations.AddIndex(
            model_name="billtopic",
            index=models.Index(fields=["bill"], name="legislation__bill_id_1d2e3f_idx"),
        ),
        migrations.AddIndex(
            model_name="billtopic",
            index=models.Index(fields=["topic", "bill"], name="legislation__topic_i_4a5b6c_idx"),
        ),
        migrations.AddConstraint(
            model_name="billsimilarity",
            constraint=models.UniqueConstraint(
                fields=("bill_a", "bill_b", "method"),
                name="legislation_billsimilarity_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="billsimilarity",
            constraint=models.CheckConstraint(
                check=models.Q(("bill_a_id__lt", models.F("bill_b_id"))),
                name="legislation_billsimilarity_ordered",
            ),
        ),
        migrations.AddIndex(
            model_name="billsimilarity",
            index=models.Index(fields=["bill_a"], name="legislation__bill_a_7e8f9a_idx"),
        ),
        migrations.AddIndex(
            model_name="billsimilarity",
            index=models.Index(fields=["bill_b"], name="legislation__bill_b_0a1b2c_idx"),
        ),
        migrations.AddIndex(
            model_name="billsimilarity",
            index=models.Index(fields=["-similarity_score"], name="legislation__similari_3d4e5f_idx"),
        ),
    ]
