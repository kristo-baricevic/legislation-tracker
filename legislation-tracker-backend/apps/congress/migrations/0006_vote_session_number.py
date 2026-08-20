from django.db import migrations, models


def backfill_vote_session_numbers(apps, schema_editor):
    Vote = apps.get_model("congress", "Vote")
    for vote in Vote.objects.select_related("bill").iterator():
        congress_start_year = 1789 + (2 * (vote.bill.session - 1))
        session_number = 1 if vote.vote_date.year <= congress_start_year else 2
        Vote.objects.filter(pk=vote.pk).update(session_number=session_number)


class Migration(migrations.Migration):

    dependencies = [
        ("congress", "0005_representative_roster_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="vote",
            name="session_number",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.RunPython(
            backfill_vote_session_numbers,
            migrations.RunPython.noop,
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
    ]
