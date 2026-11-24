"""Compare reader preflight ceilings against a pinned official document."""
import hashlib
import json
from pathlib import Path
from time import monotonic

from django.core.management.base import BaseCommand, CommandError
from django.core.files.storage import default_storage
from django.test import override_settings

from apps.legislation.enhancements.model_selection import planning_for
from apps.legislation.enhancements.source_packet import PreflightUnavailable, build_document_preflight
from apps.legislation.models import BillDocument


class Command(BaseCommand):
    help = "Print offline 1000/2000/4000 estimates for a pinned harness manifest."

    def add_arguments(self, parser):
        parser.add_argument("manifest", type=Path)
        parser.add_argument("--provider", required=True)
        parser.add_argument("--model", required=True)
        parser.add_argument("--context-tokens", required=True, type=int)
        parser.add_argument("--output-tokens", required=True, type=int)

    def handle(self, **options):
        manifest = json.loads(options["manifest"].read_text())
        document = BillDocument.objects.select_related("bill").get(pk=manifest["document"])
        provider, model = options["provider"], options["model"]
        limits = {"context_tokens": options["context_tokens"], "output_tokens": options["output_tokens"]}
        if min(limits.values()) <= 0 or limits["output_tokens"] > limits["context_tokens"]:
            raise CommandError("Invalid model limits")
        text = document.extracted_text or document.raw_text or ""
        with default_storage.open(document.object_storage_key, "rb") as raw:
            xml_digest = hashlib.file_digest(raw, "sha256").hexdigest()
        if (xml_digest != manifest["xml_sha256"] or hashlib.sha256(text.encode()).hexdigest() != manifest["text_sha256"]
                or document.bill_id != manifest["bill"]):
            raise CommandError("Stored document does not match the pinned case")
        with override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                                                    "LOCATION": "reader-estimate-only"}},
                               LLM_READER_MODEL_CAPABILITIES={f"{provider}/{model}": limits}), planning_for((provider, model)):
            for target in (1000, 2000, 4000):
                started = monotonic()
                report = {"document": document.pk, "xml_sha256": xml_digest, "target": target, "model": model,
                          "provider": provider, "model_limits": limits}
                with override_settings(LLM_READER_OWNED_TOKEN_TARGET=target):
                    try:
                        plan = build_document_preflight(document)
                    except PreflightUnavailable as exc:
                        report.update(rejected=exc.reason, coverage=exc.coverage)
                    else:
                        report.update(budget=plan.source_manifest["budget"], fingerprint=plan.request_fingerprint)
                report["planning_seconds"] = round(monotonic() - started, 3)
                self.stdout.write(json.dumps(report, sort_keys=True))
