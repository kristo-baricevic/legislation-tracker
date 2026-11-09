from django.core.management.base import BaseCommand
from apps.legislation.models import BillContract
from apps.legislation.extraction.reader_language import build_reader_copy, bill_brief


class Command(BaseCommand):
    help = "Rebuild reader wording for all saved 2.1 analyses without changing sources or AI identities."

    def add_arguments(self, parser):
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--summaries-only", action="store_true")

    def handle(self, *args, **options):
        records = BillContract.objects.filter(schema_version="2.1-legal-nlp").select_related("document").only(
            "id", "contract_json", "contract_hash", "reader_copy", "document__source_purpose").order_by("id")
        if options["summaries_only"]:
            records = records.filter(reader_copy__brief__summary="").defer("contract_json")
        changed = unchanged = 0
        for record in records.iterator(chunk_size=20):
            purpose = record.document.source_purpose if record.document else ""
            if options["summaries_only"]:
                copy = {**record.reader_copy, "brief": {**record.reader_copy["brief"], "summary": bill_brief({}, purpose)["summary"]}}
            else:
                copy = build_reader_copy(record.contract_json, record.contract_hash, purpose)
            if copy == record.reader_copy:
                unchanged += 1
                continue
            if options["execute"]:
                BillContract.objects.filter(pk=record.pk, contract_hash=record.contract_hash).update(reader_copy=copy)
            changed += 1
            if changed % 1000 == 0:
                self.stdout.write(f"processed={changed + unchanged} changed={changed}")
        self.stdout.write(f"changed={changed} unchanged={unchanged} executed={options['execute']}")
