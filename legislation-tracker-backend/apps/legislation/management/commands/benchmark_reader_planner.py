"""Read-only coverage/capacity audit. Never constructs or calls an AI provider."""

import json
import time
from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from apps.legislation.enhancements.model_selection import planning_for, target
from apps.legislation.enhancements.reader_capacity import fits
from apps.legislation.enhancements.reader_discovery import policy_passages
from apps.legislation.enhancements.source_packet import (
    PreflightUnavailable,
    _marked_active_document,
    _stored_document,
    build_document_preflight,
)
from apps.legislation.models import Bill, BillDocument


class Command(BaseCommand):
    help = "Plan stored documents locally and report exact reader ownership coverage; no AI calls."

    def add_arguments(self, parser):
        parser.add_argument("documents", nargs="+", type=int)
        parser.add_argument("--provider")
        parser.add_argument("--model")
        parser.add_argument(
            "--bills",
            action="store_true",
            help="Treat identifiers as bill IDs, selecting their current stored document",
        )

    def handle(self, *args, **options):
        pair = (options["provider"] or target()[0], options["model"] or target()[1])
        for pk in options["documents"]:
            if options["bills"]:
                bill = Bill.objects.select_related("latest_contract").get(pk=pk)
                document = _marked_active_document(bill) or _stored_document(bill)
            else:
                document = BillDocument.objects.select_related(
                    "bill__latest_contract"
                ).get(pk=pk)
            if document is None:
                raise CommandError(f"No stored document for bill {pk}")
            start = time.monotonic()
            with planning_for(pair):
                try:
                    plan = build_document_preflight(document)
                except PreflightUnavailable as exc:
                    self.stdout.write(
                        json.dumps(
                            {
                                "document": document.pk,
                                "status": "blocked",
                                "reason": exc.reason,
                                "seconds": round(time.monotonic() - start, 3),
                            }
                        )
                    )
                    continue
                if plan.output_schema_version != "1.4":
                    self.stdout.write(
                        json.dumps(
                            {
                                "document": document.pk,
                                "status": "different_pipeline",
                                "schema": plan.output_schema_version,
                                "seconds": round(time.monotonic() - start, 3),
                            }
                        )
                    )
                    continue
                scans = [s for s in plan.source_snapshot if s.get("discovery_source")]
                expected = set(policy_passages(scans))
                counts = Counter(
                    i
                    for r in plan.reader_batches
                    if r.request_envelope.get("source_review")
                    for i in policy_passages(r.source_snapshot)
                )
                reused = (
                    (plan.reader_reuse or {})
                    .get("source_review", {})
                    .get("policy_checks", {})
                )
                counts.update(reused.keys())
                report = {
                    "document": document.pk,
                    "seconds": round(time.monotonic() - start, 3),
                    "planned_calls": plan.source_manifest.get("budget", {}).get(
                        "planned_calls"
                    ),
                    "budget": plan.source_manifest.get("budget"),
                    "owned_passages": len(counts),
                    "expected_passages": len(expected),
                    "missing": len(expected - set(counts)),
                    "unexpected": len(set(counts) - expected),
                    "duplicated": sum(n - 1 for n in counts.values() if n > 1),
                    "oversize_requests": sum(
                        not fits(r.request_envelope, provider=pair[0], model=pair[1])
                        for r in (plan, *plan.reader_batches)
                    ),
                    "coverage": plan.source_manifest.get("coverage"),
                    "incomplete_context_chunks": sum(
                        s.get("section_context_complete") is False for s in scans
                    ),
                }
                # Source IDs can number in the thousands; retain counts here.
                report["coverage"] = {
                    k: v
                    for k, v in (report["coverage"] or {}).items()
                    if not isinstance(v, list)
                }
            self.stdout.write(json.dumps(report))
