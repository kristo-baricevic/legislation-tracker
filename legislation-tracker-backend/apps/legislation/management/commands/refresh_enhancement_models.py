from django.core.management.base import BaseCommand
from apps.legislation.enhancements.openrouter_catalog import refresh_catalog


class Command(BaseCommand):
    help = "Refresh selectable free OpenRouter models using public metadata."

    def handle(self, **options):
        self.stdout.write(f"Refreshed {len(refresh_catalog())} model records")
