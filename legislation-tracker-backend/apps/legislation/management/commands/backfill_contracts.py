from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from apps.legislation.models import BillDocument
from apps.legislation.tasks import enqueue_document_contract


class Command(BaseCommand):
    help = "Preview or enqueue a bounded deterministic contract backfill."

    def add_arguments(self, parser):
        parser.add_argument("--session", type=int)
        parser.add_argument("--start-id", type=int)
        parser.add_argument("--end-id", type=int)
        parser.add_argument("--limit", type=int)
        parser.add_argument("--all-versions", action="store_true")
        parser.add_argument("--execute", action="store_true")

    def handle(self, *args, **options):
        selectors = (
            options["session"],
            options["start_id"],
            options["end_id"],
            options["limit"],
        )
        if all(value is None for value in selectors):
            raise CommandError(
                "At least one of --session, --start-id, --end-id, or --limit is required."
            )
        if (
            options["start_id"] is not None
            and options["end_id"] is not None
            and options["start_id"] > options["end_id"]
        ):
            raise CommandError("--start-id must be less than or equal to --end-id.")
        if options["limit"] is not None and options["limit"] <= 0:
            raise CommandError("--limit must be positive.")

        documents = BillDocument.objects.select_related("bill").order_by("id")
        if not options["all_versions"]:
            documents = documents.filter(is_active_version=True)
        if options["session"] is not None:
            documents = documents.filter(bill__session=options["session"])
        if options["start_id"] is not None:
            documents = documents.filter(id__gte=options["start_id"])
        if options["end_id"] is not None:
            documents = documents.filter(id__lte=options["end_id"])
        if options["limit"] is not None:
            documents = documents[: options["limit"]]
        selected = list(documents)

        session_counts = Counter(document.bill.session for document in selected)
        sessions = ",".join(
            f"{session}:{count}" for session, count in sorted(session_counts.items())
        )
        active_count = sum(document.is_active_version for document in selected)
        identifiers = [document.id for document in selected]
        minimum_id = min(identifiers) if identifiers else "none"
        maximum_id = max(identifiers) if identifiers else "none"
        self.stdout.write(
            f"selected={len(selected)} min_id={minimum_id} max_id={maximum_id} "
            f"sessions={sessions or 'none'} active={active_count} "
            f"inactive={len(selected) - active_count}"
        )

        if not options["execute"]:
            self.stdout.write("Preview only; pass --execute to enqueue.")
            return

        for document in selected:
            enqueue_document_contract(document)
        self.stdout.write(f"enqueued={len(selected)}")
