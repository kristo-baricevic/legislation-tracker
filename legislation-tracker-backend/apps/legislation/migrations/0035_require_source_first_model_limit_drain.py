from django.conf import settings
from django.db import migrations
from django.db.models import Exists, OuterRef, Q


def require_source_first_drain(apps, schema_editor):
    attempts = apps.get_model("legislation", "BillEnhancementAttempt").objects.using(schema_editor.connection.alias)
    later = attempts.filter(enhancement_id=OuterRef("enhancement_id"), sequence__gt=OuterRef("sequence"))
    outstanding = attempts.filter(enhancement__output_schema_version="2.0-source-first").filter(
        Q(status__in=("pending", "running")) | (Q(status="paused") & ~Exists(later))
    )
    # The old provision planner capped both settings before packing its calls.
    old_output = min(8000, settings.LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS)
    old_input = min(100000, settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS, settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES)
    for pk, provider, model, manifest in outstanding.values_list(
        "pk", "enhancement__provider", "enhancement__requested_model", "enhancement__source_manifest_json"
    ).iterator():
        if manifest.get("model_limits_version") == 1:
            continue
        limits = settings.LLM_READER_MODEL_CAPACITIES.get(f"{provider}/{model}", {})
        output = min(settings.LLM_READER_MAX_OUTPUT_TOKENS, int(limits.get("output_tokens", settings.LLM_READER_MAX_OUTPUT_TOKENS)))
        context = int(limits.get("context_tokens", settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS + output + 1024))
        # OpenRouter's catalog may change or expire while an attempt is queued.
        if provider == "openrouter" or output < old_output or context < old_input + old_output:
            raise RuntimeError(f"Attempt {pk} needs the previous worker's source-first limits. Drain active work "
                               "and let owners continue outstanding paused jobs before retrying migrate.")


class Migration(migrations.Migration):
    dependencies = [("legislation", "0034_require_legacy_model_limit_drain")]
    operations = [migrations.RunPython(require_source_first_drain, migrations.RunPython.noop)]
