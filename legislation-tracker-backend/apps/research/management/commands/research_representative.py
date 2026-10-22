from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from apps.research.services import request_research


class Command(BaseCommand):
    help = "Queue research for one representative; never performs an all-member backfill."

    def add_arguments(self, parser):
        parser.add_argument("representative_id", type=int)
        parser.add_argument("--period", type=int, required=True)
        parser.add_argument("--user-id", type=int, required=True)

    def handle(self, *args, **options):
        if not get_user_model().objects.filter(pk=options["user_id"], is_active=True).exists():
            raise CommandError("An active requesting user is required.")
        try:
            run = request_research(options["representative_id"], options["period"], options["user_id"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(str(run.pk))
