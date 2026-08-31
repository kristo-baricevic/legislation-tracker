"""Preview or enqueue durable bill-search projection work."""

from django.core.management.base import BaseCommand, CommandError

from apps.legislation.models import Bill, BillSearchChunk
from apps.legislation.tasks import enqueue_search_index


class Command(BaseCommand):
    help = "Preview or enqueue durable search indexing for one Congress."

    def add_arguments(self, parser):
        parser.add_argument("--congress", type=int, required=True)
        parser.add_argument("--limit", type=int, default=None)
        parser.add_argument("--execute", action="store_true")

    def handle(self, *args, **options):
        congress = options["congress"]
        limit = options["limit"]
        if limit is not None and limit < 1:
            raise CommandError("--limit must be positive")
        bills = Bill.objects.filter(session=congress).order_by("id")
        if limit is not None:
            bills = bills[:limit]
        candidates = list(bills)
        current_bill_ids = set(
            BillSearchChunk.objects.filter(bill__in=candidates)
            .values_list("bill_id", flat=True)
            .distinct()
        )
        self.stdout.write(
            f"congress={congress} candidate={len(candidates)} "
            f"already_current={len(current_bill_ids)}"
        )
        if not options["execute"]:
            self.stdout.write("Preview only. Re-run with --execute to enqueue work.")
            return
        for bill in candidates:
            enqueue_search_index(bill)
        self.stdout.write(self.style.SUCCESS(f"Enqueued {len(candidates)} search jobs."))
