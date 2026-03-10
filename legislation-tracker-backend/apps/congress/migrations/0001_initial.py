# Generated manually for Phase 2

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Representative",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("bioguide_id", models.CharField(db_index=True, max_length=20, unique=True)),
                ("name", models.CharField(max_length=255)),
                ("chamber", models.CharField(max_length=20)),
                ("party", models.CharField(max_length=50)),
                ("state", models.CharField(max_length=2)),
                ("district", models.CharField(blank=True, max_length=10, null=True)),
                ("is_current", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "congress_representative",
            },
        ),
        migrations.AddIndex(
            model_name="representative",
            index=models.Index(fields=["chamber"], name="congress_rep_chamber_7b2a0b_idx"),
        ),
        migrations.AddIndex(
            model_name="representative",
            index=models.Index(fields=["state"], name="congress_rep_state_2c8b0d_idx"),
        ),
    ]
