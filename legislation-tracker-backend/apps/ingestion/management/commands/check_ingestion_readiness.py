import json
import time

from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.discoverable_readiness import observe_discoverable
from apps.ingestion.source_inventory import (
    MAX_PAGES,
    MAX_SECONDS,
    scan_inventory,
    snapshot_key,
)


class Command(BaseCommand):
    help = "Read-only Congress.gov bill inventory; never enqueue ingestion."

    def add_arguments(self, parser):
        parser.add_argument("--congress", type=int, required=True)
        parser.add_argument("--jurisdiction", default="federal")
        parser.add_argument("--bill-types", nargs="+", default=["hr", "s"])
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        scope = (
            options["jurisdiction"],
            options["congress"],
            tuple(options["bill_types"]),
        )
        key = snapshot_key(*scope)
        if not cache.add(key + ":scan", True, timeout=180):
            raise CommandError("A source check is already active")
        try:
            deadline = time.monotonic() + MAX_SECONDS
            snapshot = scan_inventory(scope[1], scope[0], scope[2])
            if snapshot["complete"]:
                snapshot.update(
                    observe_discoverable(
                        scope[1],
                        scope[0],
                        deadline=deadline,
                        page_budget=MAX_PAGES - snapshot["pages_examined"],
                    )
                )
            if snapshot.get("retry_after_seconds"):
                cache.set(key + ":scan", True, timeout=snapshot["retry_after_seconds"])
            cache.set(key, snapshot, timeout=3600)
            self.stdout.write(json.dumps(snapshot))
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        finally:
            # No deletion race: expiry is the bound for coalescing subsequent checks.
            pass
