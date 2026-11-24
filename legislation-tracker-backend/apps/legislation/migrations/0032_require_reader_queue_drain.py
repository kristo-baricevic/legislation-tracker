from django.db import migrations


def require_reader_queue_drain(apps, schema_editor):
    attempts = apps.get_model("legislation", "BillEnhancementAttempt")
    active = attempts.objects.using(schema_editor.connection.alias).filter(
        status__in=("pending", "running"), enhancement__output_schema_version="1.4")
    for attempt_id, manifest in active.values_list("pk", "enhancement__source_manifest_json").iterator():
        if manifest.get("execution_settings", {}).get("reader_execution_version") != 9:
            raise RuntimeError(
                f"Reader attempt {attempt_id} requires the previous worker. Pause enhancement submissions, "
                "drain queued and running jobs on the previous release, then retry migrate."
            )


class Migration(migrations.Migration):
    dependencies = [("legislation", "0031_snapshot_reader_execution")]
    operations = [migrations.RunPython(require_reader_queue_drain, migrations.RunPython.noop)]
