"""
Management command to run update_topics for all existing bills.

Usage:
    python manage.py backfill_topics              # enqueue as Celery tasks
    python manage.py backfill_topics --sync        # run synchronously (no Celery)
    python manage.py backfill_topics --session 119 # filter by congress session
"""
from django.core.management.base import BaseCommand

from apps.legislation.models import Bill
from apps.legislation.tasks import update_topics


class Command(BaseCommand):
    help = "Run update_topics for all bills (backfill Phase 6). Works with title alone — no contract required."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Run synchronously instead of enqueuing Celery tasks.",
        )
        parser.add_argument(
            "--session",
            type=int,
            default=None,
            help="Limit to bills in this congress session.",
        )

    def handle(self, *args, **options):
        qs = Bill.objects.order_by("id")
        if options["session"]:
            qs = qs.filter(session=options["session"])

        bill_ids = list(qs.values_list("id", flat=True))
        self.stdout.write(f"Found {len(bill_ids)} bills to process.")

        processed = 0
        for bid in bill_ids:
            if options["sync"]:
                result = update_topics(bill_id=bid)
                self.stdout.write(f"  bill_id={bid} -> {result}")
            else:
                update_topics.apply_async(kwargs={"bill_id": bid})
            processed += 1

        mode = "sync" if options["sync"] else "async (Celery)"
        self.stdout.write(
            self.style.SUCCESS(f"Done: {processed} bills processed ({mode}).")
        )
