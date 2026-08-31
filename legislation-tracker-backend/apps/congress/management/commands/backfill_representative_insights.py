from django.core.management.base import BaseCommand, CommandError

from apps.congress.current import current_congress
from apps.ingestion.tasks import _queue_bill_relationships
from apps.legislation.models import Bill


class Command(BaseCommand):
    help = "Preview or enqueue representative relationship work for one Congress."

    def add_arguments(self, parser):
        parser.add_argument("--congress", required=True, type=int)
        parser.add_argument("--limit", type=int)
        parser.add_argument("--execute", action="store_true")

    def handle(self, *args, **options):
        congress = options["congress"]
        if congress < 1 or congress > current_congress():
            raise CommandError("--congress must be a positive current or historical Congress")
        limit = options.get("limit")
        if limit is not None and limit < 1:
            raise CommandError("--limit must be positive")
        bills = Bill.objects.filter(session=congress).order_by("id")
        if limit:
            bills = bills[:limit]
        count = bills.count()
        mode = "current" if congress == current_congress() else "historical"
        self.stdout.write(f"{mode} Congress {congress}: {count} bill relationship candidates")
        self.stdout.write("Historical committee-roster completeness is not guaranteed.")
        if not options["execute"]:
            self.stdout.write("Preview only; pass --execute to enqueue durable work.")
            return
        for bill in bills:
            _queue_bill_relationships(bill)
        self.stdout.write(f"Queued {count} durable bill_relationships items.")
