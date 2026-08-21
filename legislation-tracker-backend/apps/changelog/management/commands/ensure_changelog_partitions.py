from django.core.management.base import BaseCommand, CommandError

from apps.changelog.partitions import ensure_change_log_partitions


class Command(BaseCommand):
    help = "Create the current and future PostgreSQL ChangeLog partitions."

    def add_arguments(self, parser):
        parser.add_argument("--months-ahead", type=int, default=12)

    def handle(self, *args, **options):
        months_ahead = options["months_ahead"]
        if months_ahead < 0:
            raise CommandError("--months-ahead must be zero or greater.")
        created = ensure_change_log_partitions(months_ahead=months_ahead)
        rendered_partitions = ",".join(created) or "none"
        self.stdout.write(f"created={len(created)} partitions={rendered_partitions}")
