import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("congress", "0010_vote_source_version")]

    operations = [
        migrations.CreateModel(
            name="RepresentativeTerm",
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
                ("chamber", models.CharField(max_length=20)),
                ("state", models.CharField(blank=True, default="", max_length=2)),
                ("district", models.CharField(blank=True, max_length=10, null=True)),
                ("member_type", models.CharField(blank=True, default="", max_length=50)),
                ("start_date", models.DateField()),
                ("end_date", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "representative",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="service_terms",
                        to="congress.representative",
                    ),
                ),
            ],
            options={"db_table": "congress_representativeterm"},
        ),
        migrations.AddConstraint(
            model_name="representativeterm",
            constraint=models.UniqueConstraint(
                fields=("representative", "chamber", "start_date"),
                name="congress_rep_term_identity_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="representativeterm",
            index=models.Index(
                fields=["representative", "start_date", "end_date"],
                name="congress_rep_term_dates_idx",
            ),
        ),
    ]
