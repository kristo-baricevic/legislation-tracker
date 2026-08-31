import django.db.models.deletion
from django.db import migrations, models

from apps.congress.current import current_congress


def backfill_vote_congress(apps, schema_editor):
    Vote = apps.get_model("congress", "Vote")
    missing = Vote.objects.filter(congress__isnull=True, bill__isnull=True)
    if missing.exists():
        raise RuntimeError("Cannot backfill Congress for unlinked legacy votes")
    for vote in Vote.objects.select_related("bill").filter(congress__isnull=True):
        vote.congress = vote.bill.session
        vote.save(update_fields=["congress"])


class Migration(migrations.Migration):
    dependencies = [("congress", "0006_vote_session_number")]

    operations = [
        migrations.AddField(model_name="vote", name="congress", field=models.PositiveSmallIntegerField(blank=True, db_index=True, null=True)),
        migrations.AddField(model_name="vote", name="question", field=models.TextField(blank=True, default="")),
        migrations.AddField(model_name="vote", name="source_url", field=models.URLField(blank=True, default="", max_length=1024)),
        migrations.AddField(model_name="voterecord", name="raw_position", field=models.CharField(blank=True, default="", max_length=100)),
        migrations.RunPython(backfill_vote_congress, migrations.RunPython.noop),
        migrations.AlterField(model_name="vote", name="bill", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="votes", to="legislation.bill")),
        migrations.AlterField(model_name="vote", name="congress", field=models.PositiveSmallIntegerField(db_index=True, default=current_congress)),
        migrations.AlterField(model_name="voterecord", name="position", field=models.CharField(choices=[("yes", "Yes"), ("no", "No"), ("present", "Present"), ("not_voting", "Not voting"), ("other", "Other")], max_length=20)),
        migrations.RemoveConstraint(model_name="vote", name="congress_vote_bill_chamber_session_roll_uniq"),
        migrations.RemoveConstraint(model_name="vote", name="congress_vote_unknown_session_roll_uniq"),
        migrations.AddConstraint(model_name="vote", constraint=models.UniqueConstraint(fields=("congress", "chamber", "session_number", "roll_number"), name="congress_vote_identity_session_uniq")),
        migrations.AddConstraint(model_name="vote", constraint=models.UniqueConstraint(condition=models.Q(("session_number__isnull", True)), fields=("congress", "chamber", "roll_number"), name="congress_vote_identity_unknown_session_uniq")),
        migrations.AddIndex(model_name="vote", index=models.Index(fields=["congress", "chamber", "vote_date"], name="congress_vote_scope_date_idx")),
        migrations.AddIndex(model_name="voterecord", index=models.Index(fields=["representative", "vote"], name="congress_record_rep_vote_idx")),
    ]
