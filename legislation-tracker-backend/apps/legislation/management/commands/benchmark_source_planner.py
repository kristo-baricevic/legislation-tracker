"""Read-only source-first planning benchmark; deliberately no provider or dispatch."""
from collections import Counter
from hashlib import sha256
from pathlib import Path
from time import perf_counter
import json

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from apps.legislation.models import BillDocument
from apps.legislation.enhancements.source_graph import build_source_graph
from apps.legislation.enhancements.xml_sections import stored_xml_sections
from apps.legislation.enhancements.provision_pipeline import BudgetExceeded, _plan_built_graph


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("documents", type=int, nargs="+")
        parser.add_argument("--summary-scenario", action="store_true",
                            help="Size the summary reduction locally with placeholder findings; no AI calls.")
        parser.add_argument("--expected-inventory", type=Path,
                            help="Check one document against a pinned official XML inventory.")
        parser.add_argument("--legacy-small-plan", action="store_true",
                            help="Measure the old bounded provision planner instead of the full XML review.")

    def handle(self, *args, documents, **options):
        reference = options.get("expected_inventory")
        if reference and len(documents) != 1:
            raise CommandError("A pinned inventory applies to one document version")
        for pk in documents:
            doc = BillDocument.objects.get(pk=pk)
            text = doc.extracted_text or doc.raw_text or ""
            if not text:
                raise CommandError(f"Missing source text: {pk}")
            start = perf_counter()
            bounds = stored_xml_sections(doc, text)
            if bounds and len(text) > settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES and not options["legacy_small_plan"]:
                from apps.legislation.enhancements.source_packet import build_document_preflight
                from apps.legislation.enhancements.reader_discovery import xml_batch_coverage
                p = build_document_preflight(doc)
                if reference:
                    stamp = {"source_sha256": doc.content_hash, "sections": len(bounds),
                             "ordered_id_sha256": sha256("\n".join(s[0] for s in bounds).encode()).hexdigest()}
                    if stamp != json.loads(reference.read_text()):
                        raise CommandError("Official XML inventory changed")
                reviews = [r for r in p.reader_batches if r.request_envelope.get("source_review")]
                scans = [s for s in p.source_snapshot if s.get("discovery_source")]
                coverage = xml_batch_coverage(text, bounds, scans)
                reused = bool((p.reader_reuse or {}).get("source_review"))
                if not reused and [s for r in reviews for s in r.source_snapshot] != scans:
                    raise CommandError("A review chunk was omitted or duplicated by the execution plan")
                from apps.legislation.evaluation.xml_batch_estimate import summary_scenario
                elapsed = round(perf_counter()-start, 3)
                self.stdout.write(json.dumps(dict(document=pk, model=p.requested_model, **coverage,
                    review_calls=len(reviews), other_detail_calls=len(p.reader_batches)-len(reviews),
                    reused_review=reused, budget=p.source_manifest["budget"],
                    detail_request_bytes=sum(len(r.request_bytes) for r in p.reader_batches),
                    review_passages=sum(len(r.request_envelope["output_schema"]["properties"]["policy_checks"]["required"])
                                        for r in reviews),
                    max_request_bytes=max((len(r.request_bytes) for r in p.reader_batches), default=0),
                    planner_s=elapsed, scenario=summary_scenario(p) if options["summary_scenario"] else None)))
                continue
            g = build_source_graph(str(pk), doc.version_label, text, xml_sections=bounds)
            built = perf_counter()
            try:
                plan = _plan_built_graph(g, {
                    "output_tokens": settings.LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS,
                    "per_call_input": min(settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES,
                                          settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS)})
                planned = [uid for c in plan.calls for uid in c.unit_ids]
                reasons = dict(plan.unresolved_reasons)
                status = "partial" if reasons else "ready"
            except BudgetExceeded as exc:
                planned, reasons, status = [], exc.reasons, str(exc)
            end = perf_counter()
            ids = [*planned, *reasons]
            account = Counter(ids) == Counter(u.id for u in g.units)
            # Verify the union of stored spans covers the original, including preamble.
            cursor = 0
            for p in sorted(g.passages.values(), key=lambda p: p.start):
                if p.start > cursor or p.text != text[p.start:p.end]:
                    raise CommandError(f"Source range mismatch in {pk}")
                cursor = max(cursor, p.end)
            if not account or cursor != len(text):
                raise CommandError(f"Incomplete accounting for {pk}")
            expected = Counter((row[1], row[2]) for row in bounds)
            actual = Counter((p.start, p.end) for u in g.units
                             for pid in u.own_passage_ids for p in [g.passages[pid]])
            xml = dict(expected=len(bounds), matched=sum((expected & actual).values()),
                       missing=sum((expected-actual).values()), extra=sum((actual-expected).values()),
                       duplicated=sum(n-1 for n in actual.values() if n>1)) if bounds else None
            if xml and (xml["missing"] or xml["extra"] or xml["duplicated"]):
                raise CommandError(f"XML inventory mismatch: {xml}")
            if reference:
                stamp = {"source_sha256": doc.content_hash,
                         "sections": len(bounds),
                         "ordered_id_sha256": sha256("\n".join(row[0] for row in bounds).encode()).hexdigest()}
                if stamp != json.loads(reference.read_text()):
                    raise CommandError("Official XML section inventory differs from pinned reference")
            self.stdout.write(json.dumps(dict(document=pk, version=doc.version_label, xml_sections=xml,
                chars=len(text), units=len(ids), planned=len(planned), status=status,
                unresolved=dict(Counter(reasons.values())), source_chars_accounted=cursor,
                graph_s=round(built-start,3), planner_s=round(end-built,3))))
