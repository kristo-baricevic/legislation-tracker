# Generated manually for Phase 2

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("congress", "0001_initial"),
        ("legislation", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Vote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("chamber", models.CharField(max_length=20)),
                ("roll_number", models.PositiveIntegerField()),
                ("vote_date", models.DateTimeField()),
                ("result", models.CharField(max_length=50)),
                ("yeas", models.PositiveIntegerField(default=0)),
                ("nays", models.PositiveIntegerField(default=0)),
                (
                    "bill",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="votes",
                        to="legislation.bill",
                    ),
                ),
            ],
            options={
                "db_table": "congress_vote",
            },
        ),
        migrations.CreateModel(
            name="VoteRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("position", models.CharField(max_length=20)),
                (
                    "representative",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="vote_records",
                        to="congress.representative",
                    ),
                ),
                (
                    "vote",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="records",
                        to="congress.vote",
                    ),
                ),
            ],
            options={
                "db_table": "congress_voterecord",
            },
        ),
        migrations.AddConstraint(
            model_name="vote",
            constraint=models.UniqueConstraint(
                fields=("bill", "chamber", "roll_number"),
                name="congress_vote_bill_chamber_roll_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="voterecord",
            index=models.Index(fields=["vote"], name="congress_vot_vote_id_1a2b3c_idx"),
        ),
        migrations.AddIndex(
            model_name="voterecord",
            index=models.Index(fields=["representative"], name="congress_vot_represe_4d5e6f_idx"),
        ),
    ]
