from django.apps import AppConfig


class LegislationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.legislation"
    label = "legislation"
    verbose_name = "Legislation"
