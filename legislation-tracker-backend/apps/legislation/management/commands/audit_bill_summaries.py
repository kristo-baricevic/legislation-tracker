"""Audit the summary sources actually available to reader surfaces."""
import json
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Prefetch

from apps.legislation.models import Bill, BillDocument
from apps.legislation.serializers import BillDocumentSerializer


class Command(BaseCommand):
    help = "Report reader-visible summary coverage, separately from analysis completion."

    def add_arguments(self, parser):
        parser.add_argument("--require-source-coverage", action="store_true")
        parser.add_argument("--require-analysis", action="store_true")

    def handle(self, *args, **options):
        counts = Counter()
        missing = []
        analysis_missing = []
        bills = Bill.objects.select_related("latest_contract").prefetch_related(
            Prefetch("documents", queryset=BillDocument.objects.filter(is_active_version=True),
                     to_attr="summary_documents")
        ).order_by("pk")
        for bill in bills.iterator(chunk_size=100):
            doc = next(iter(bill.summary_documents), None)
            contract = bill.latest_contract
            data = contract.contract_json if contract else {}
            synopsis = (data.get("orientation") or {}).get("purpose_clause")
            if not (doc and contract and contract.document_id == doc.pk
                    and data.get("line_items")):
                analysis_missing.append({"id": bill.pk, "bill": bill.bill_number})
            if bill.summary and bill.summary.strip():
                status = "official_or_stored"
            elif doc and contract and contract.document_id == doc.pk and synopsis:
                status = "generated_synopsis"
            elif doc and (fallback := BillDocumentSerializer().get_reader_summary(doc)):
                status = "outline_only" if fallback.startswith("Bill-text overview — sections cover:") else "source_fallback"
            elif doc and contract and contract.document_id == doc.pk and data.get("plain_summary"):
                status = "legacy_summary"
            elif not doc or not (doc.extracted_text or doc.raw_text):
                status = "missing_source"
            else:
                status = "unsupported_source"
            counts[status] += 1
            if status in {"missing_source", "unsupported_source", "outline_only"}:
                missing.append({"id": bill.pk, "bill": bill.bill_number, "reason": status})
        self.stdout.write(json.dumps({"total": sum(counts.values()), "counts": counts,
                                      "missing": missing,
                                      "analysis_missing": analysis_missing}, indent=2))
        if options["require_source_coverage"] and missing:
            raise CommandError("Some bills have no substantive reader summary.")
        if options["require_analysis"] and analysis_missing:
            raise CommandError("Some bills have no current document-backed analysis.")
