from django.apps import AppConfig


class ChangelogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.changelog"
    label = "changelog"
    verbose_name = "Change log"

    def ready(self):
        from . import checks  # noqa: F401
