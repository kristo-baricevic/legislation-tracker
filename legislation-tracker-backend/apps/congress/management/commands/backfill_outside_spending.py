"""Queue only missing outside-spending aggregates; preserve saved donations."""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.campaign_finance.outside_backfill import queue_outside_period
from apps.campaign_finance.periods import discover_periods
from apps.congress.models import Representative


class Command(BaseCommand):
    help = "Queue missing outside spending for verified candidates. Requires the research worker."

    def add_arguments(self, parser):
        targets = parser.add_mutually_exclusive_group(required=True)
        targets.add_argument("--representative-id", type=int)
        targets.add_argument("--all-researched", action="store_true")
        parser.add_argument(
            "--scope", choices=["all_years", "last_ten_years"], default="all_years"
        )

    def handle(self, *args, **options):
        reps = Representative.objects.filter(
            representativecandidate__verified=True,
            representativecandidate__evidence_url__gt="",
        ).distinct()
        if options["representative_id"] is not None:
            reps = reps.filter(pk=options["representative_id"])
        if not reps.exists():
            raise CommandError(
                "No representatives with verified FEC identities matched."
            )
        queued, failures = set(), []
        for rep in reps.iterator():
            try:
                periods = discover_periods(rep, strict=True)
                if not periods:
                    raise ValueError("No verified reporting periods discovered")
                year = timezone.now().year
                for period in periods:
                    if options["scope"] == "last_ten_years" and period < year - 9:
                        continue
                    work = queue_outside_period(rep.pk, period, None)
                    if work:
                        queued.add(work.pk)
            except Exception as error:
                # Do not log provider exceptions: URLs may contain credentials.
                failures.append(rep.pk)
                self.stderr.write(
                    f"Representative {rep.pk}: {type(error).__name__}; retry this representative."
                )
        self.stdout.write(
            f"{len(queued)} outside-spending jobs queued or already active. Saved donations unchanged."
        )
        if failures:
            raise CommandError(
                f"Could not queue all periods for representatives: {failures}"
            )
