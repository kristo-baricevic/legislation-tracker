# Generated manually for deterministic PostgreSQL search projections.

import django.contrib.postgres.search
import django.contrib.postgres.indexes
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("legislation", "0008_bill_activity_fields")]

    operations = [
        migrations.CreateModel(
            name="BillSearchChunk",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("metadata", "Metadata"), ("contract", "Contract"), ("document", "Document")], max_length=16)),
                ("source_key", models.CharField(max_length=255)),
                ("ordinal", models.PositiveIntegerField(default=0)),
                ("text", models.TextField()),
                ("search_vector", django.contrib.postgres.search.SearchVectorField(editable=False, null=True)),
                ("source_hash", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("bill", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="search_chunks", to="legislation.bill")),
                ("contract", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="search_chunks", to="legislation.billcontract")),
                ("document", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="search_chunks", to="legislation.billdocument")),
            ],
            options={"db_table": "legislation_billsearchchunk"},
        ),
        migrations.AddConstraint(
            model_name="billsearchchunk",
            constraint=models.UniqueConstraint(fields=("bill", "kind", "source_key", "ordinal"), name="legislation_search_chunk_source_uniq"),
        ),
        migrations.AddIndex(
            model_name="billsearchchunk",
            index=models.Index(fields=["bill", "kind"], name="leg_search_bill_kind_idx"),
        ),
        migrations.AddIndex(
            model_name="billsearchchunk",
            index=models.Index(fields=["bill", "source_hash"], name="leg_search_bill_hash_idx"),
        ),
        migrations.AddIndex(
            model_name="billsearchchunk",
            index=django.contrib.postgres.indexes.GinIndex(fields=["search_vector"], name="legislation_search_vector_gin"),
        ),
    ]
