from django.db import migrations, models
from django.db.models import Exists, OuterRef, Q


def preserve_reviewed_mappings(apps, schema_editor):
    Mapping = apps.get_model("campaign_finance", "RepresentativeCandidate")
    Confirmation = apps.get_model("campaign_finance", "ConfirmedCandidate")
    LogEntry = apps.get_model("admin", "LogEntry")
    unverified = Mapping.objects.filter(Q(verified=False) | Q(evidence_url=""))
    confirmed = Confirmation.objects.filter(representative_id=OuterRef("representative_id"), candidate_id=OuterRef("candidate_id"))
    unverified.filter(Exists(confirmed)).update(revoked=True)
    # Old discovery rows have no staff audit entry. Preserve staff decisions
    # on mappings edited through the documented admin workflow.
    edited = LogEntry.objects.filter(content_type__app_label="campaign_finance",
                                     content_type__model="representativecandidate", action_flag__in=[1, 2])
    for pk in edited.values_list("object_id", flat=True).distinct().iterator():
        if pk and pk.isdecimal():
            unverified.filter(pk=int(pk)).update(revoked=True)


class Migration(migrations.Migration):
    dependencies = [("campaign_finance", "0014_confirmed_candidate_mappings"), ("admin", "0003_logentry_add_action_flag_choices")]
    operations = [
        migrations.AddField(model_name="representativecandidate", name="revoked",
                            field=models.BooleanField(default=False, editable=False)),
        migrations.RunPython(preserve_reviewed_mappings, migrations.RunPython.noop),
    ]
