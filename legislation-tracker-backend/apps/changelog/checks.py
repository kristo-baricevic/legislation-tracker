"""Schema checks for ChangeLog's PostgreSQL partitioning constraints."""

from django.apps import apps
from django.core.checks import Error, Tags, register


def _inbound_changelog_reference_errors(model_list, changelog_model):
    errors = []
    for model in model_list:
        if model is changelog_model:
            continue
        for field in model._meta.get_fields():
            is_foreign_key = getattr(field, "many_to_one", False) or getattr(
                field, "one_to_one", False
            )
            if (
                not is_foreign_key
                or getattr(field.remote_field, "model", None) is not changelog_model
            ):
                continue
            errors.append(
                Error(
                    f"{model._meta.label}.{field.name} references changelog.ChangeLog.",
                    hint=(
                        "ChangeLog is range-partitioned by created_at and cannot provide "
                        "a single-column unique key for inbound foreign keys. Store the "
                        "event id as an unconstrained value instead."
                    ),
                    obj=field,
                    id="changelog.E001",
                )
            )
    return errors


@register(Tags.models)
def check_for_inbound_changelog_references(app_configs, **kwargs):
    """Reject model FKs that PostgreSQL cannot enforce on the partitioned parent."""
    changelog_model = apps.get_model("changelog", "ChangeLog")
    model_list = (
        app_configs.get_models() if app_configs is not None else apps.get_models()
    )
    return _inbound_changelog_reference_errors(model_list, changelog_model)
