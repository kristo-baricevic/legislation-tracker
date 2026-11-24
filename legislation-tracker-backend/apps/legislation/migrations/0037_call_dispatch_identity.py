from django.db import migrations, models


def identify_pending_calls(apps, schema_editor):
    Cache = apps.get_model("legislation", "BillEnhancementCallCache")
    Step = apps.get_model("legislation", "BillEnhancementStep")
    pending = Cache.objects.filter(status="dispatching")
    for key, diagnostics in Step.objects.filter(request_fingerprint__in=pending.values("pk")).values_list(
        "request_fingerprint", "diagnostics"
    ).iterator():
        pending.filter(pk=key).update(dispatch_identity=diagnostics.get("logical_fingerprint") or key)


class Migration(migrations.Migration):
    dependencies = [("legislation", "0036_remove_billenhancement_legislation_enhancement_request_uniq_and_more")]
    operations = [
        migrations.AddField(model_name="billenhancementcallcache", name="dispatch_identity",
                            field=models.CharField(max_length=64, blank=True, db_index=True, default="")),
        migrations.RunPython(identify_pending_calls, migrations.RunPython.noop),
    ]
