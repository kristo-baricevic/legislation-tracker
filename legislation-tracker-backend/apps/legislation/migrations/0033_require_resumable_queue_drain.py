from django.db import migrations
from django.db.models import Exists, OuterRef, Q


def require_resumable_queue_drain(apps, schema_editor):
    attempts = apps.get_model("legislation", "BillEnhancementAttempt").objects.using(schema_editor.connection.alias)
    later = attempts.filter(enhancement_id=OuterRef("enhancement_id"), sequence__gt=OuterRef("sequence"))
    outstanding = attempts.filter(Q(status__in=("pending", "running")) | (Q(status="paused") & ~Exists(later)))
    incompatible = outstanding.filter(enhancement__provider="openrouter", enhancement__reasoning_effort="none")
    legacy_readers = outstanding.filter(enhancement__output_schema_version="1.4")
    for pk, manifest, provider, effort in (incompatible | legacy_readers).values_list(
            "pk", "enhancement__source_manifest_json", "enhancement__provider", "enhancement__reasoning_effort").iterator():
        if ((provider == "openrouter" and effort == "none")
                or manifest.get("execution_settings", {}).get("reader_execution_version") != 9):
            raise RuntimeError(f"Attempt {pk} needs the previous worker. Drain active work and let owners "
                               "confirm continuation of outstanding paused jobs before retrying migrate.")


class Migration(migrations.Migration):
    dependencies = [("legislation", "0032_require_reader_queue_drain")]
    operations = [migrations.RunPython(require_resumable_queue_drain, migrations.RunPython.noop)]
