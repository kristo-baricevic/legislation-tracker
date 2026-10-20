"""Restore document-form purpose statements without regenerating source offsets."""
import json
from collections import Counter

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from apps.ingestion.document_download import extract_document_purpose
from apps.legislation.models import BillDocument


class Command(BaseCommand):
    help = "Backfill exact version-specific purposes from stored XML; no API or AI calls."

    def add_arguments(self, parser):
        parser.add_argument("--execute", action="store_true")

    def handle(self, *args, **options):
        counts = Counter(updated=0)
        failures = []
        for doc in BillDocument.objects.filter(source_purpose="").iterator(chunk_size=100):
            purpose = ""
            if not doc.object_storage_key:
                counts["no_stored_object"] += 1
                continue
            try:
                with default_storage.open(doc.object_storage_key, "rb") as stream:
                    purpose = extract_document_purpose(stream, doc.content_type, doc.source_url)
                if not purpose:
                    counts["no_purpose"] += 1
                    continue
                if options["execute"]:
                    # Do not overwrite a concurrent download or change evidence offsets.
                    changed = BillDocument.objects.filter(
                        pk=doc.pk, content_hash=doc.content_hash,
                        object_storage_key=doc.object_storage_key, source_purpose="",
                    ).update(source_purpose=purpose)
                    counts["updated"] += changed
                else:
                    counts["would_update"] += 1
            except (OSError, ValueError) as exc:
                failures.append({"document_id": doc.pk, "error": type(exc).__name__})
            if (counts["updated"] + counts["would_update"]) % 500 == 0 and purpose:
                self.stderr.write(f"Processed {counts['updated'] + counts['would_update']} purposes")
        self.stdout.write(json.dumps({**counts, "failures": failures}))
