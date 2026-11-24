from django.db import migrations


def restore_confirmed_mappings(apps, schema_editor):
    Confirmation = apps.get_model("campaign_finance", "ConfirmedCandidate")
    Mapping = apps.get_model("campaign_finance", "RepresentativeCandidate")
    from itertools import groupby

    confirmations = Confirmation.objects.order_by("representative_id", "candidate_id", "period").values_list(
        "representative_id", "candidate_id", "period")
    for (rep, candidate), group in groupby(confirmations.iterator(), key=lambda row: row[:2]):
        periods = [row[2] for row in group]
        # An existing staff mapping, including a revocation, is authoritative.
        Mapping.objects.get_or_create(representative_id=rep, candidate_id=candidate, defaults={
            "verified": True, "periods": periods, "evidence_url": f"https://www.fec.gov/data/candidate/{candidate}/",
        })


class Migration(migrations.Migration):
    dependencies = [("campaign_finance", "0013_confirmedcandidate")]
    operations = [migrations.RunPython(restore_confirmed_mappings, migrations.RunPython.noop)]
