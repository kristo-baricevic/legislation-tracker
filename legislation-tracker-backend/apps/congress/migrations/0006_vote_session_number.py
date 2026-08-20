from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("congress", "0005_representative_roster_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="vote",
            name="session_number",
            field=models.PositiveSmallIntegerField(blank=True, default=None, null=True),
        ),
        migrations.RemoveConstraint(
            model_name="vote",
            name="congress_vote_bill_chamber_roll_uniq",
        ),
        migrations.AddConstraint(
            model_name="vote",
            constraint=models.UniqueConstraint(
                fields=("bill", "chamber", "session_number", "roll_number"),
                name="congress_vote_bill_chamber_session_roll_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="vote",
            constraint=models.UniqueConstraint(
                condition=models.Q(session_number__isnull=True),
                fields=("bill", "chamber", "roll_number"),
                name="congress_vote_unknown_session_roll_uniq",
            ),
        ),
    ]
