"""Explicitly budgeted experiment; never writes application records."""

import getpass
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.legislation.enhancements.provider_registry import get_provider
from apps.legislation.enhancements.providers.base import ProviderError
from apps.legislation.enhancements.source_packet import PreflightUnavailable
from apps.legislation.evaluation.coverage_candidate import prepare, run
from apps.legislation.evaluation.whole_bill import CASES, ROOT, SourceText


class Command(BaseCommand):
    help = "Dry-run or execute the source-checklist evaluation candidate (at most two calls)."

    def add_arguments(self, parser):
        parser.add_argument("--case", required=True, choices=list(CASES))
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--prompt-key", action="store_true")
        parser.add_argument("--output")
        parser.add_argument("--provision-first", action="store_true")

    def handle(self, *args, **options):
        identifier = options["case"]
        manifest = json.loads((ROOT / "sources/manifest.json").read_text())
        source = next(row for row in manifest if row["package_id"] == identifier)
        raw = (ROOT / source["raw_file"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise CommandError("Pinned source hash mismatch")
        parser = SourceText()
        parser.feed(raw.decode("utf-8"))
        text = "".join(parser.parts)
        if text != (ROOT / source["decoded_text_file"]).read_text():
            raise CommandError("Pinned decoded text mismatch")
        # No answer key is loaded by this command or the candidate generator.
        bill = SimpleNamespace(
            id=identifier,
            title=CASES[identifier],
            jurisdiction="federal",
            session=119,
            bill_number=identifier,
            status="enrolled" if identifier.endswith("enr") else "introduced",
            introduced_at=None,
        )
        try:
            request, inventory = prepare(bill, text, identifier)
            batches = None
            if options["provision_first"]:
                from apps.legislation.evaluation.provision_generation import requests

                batches = requests(request, inventory)
        except PreflightUnavailable as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(
            json.dumps(
                {
                    "case": identifier,
                    "request_bytes": len(request.request_bytes),
                    "inventory_candidates": len(inventory),
                    "maximum_calls": len(batches) if batches is not None else 2,
                    "max_output_per_call": settings.LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS,
                    "model": request.requested_model,
                    "execute": options["execute"],
                    "provision_first": options["provision_first"],
                    "batch_request_bytes": [
                        len(req.request_bytes) for req, _ in batches
                    ]
                    if batches is not None
                    else None,
                }
            )
        )
        if not options["execute"]:
            return
        if not options["output"]:
            raise CommandError("--output is required for an executed run")
        path = Path(options["output"])
        if path.exists():
            raise CommandError("Output exists; refusing overwrite or duplicate charges")
        key = getattr(settings, "LLM_ENHANCEMENT_EVALUATION_API_KEY", "")
        if options["prompt_key"]:
            key = getpass.getpass("Evaluation key (hidden): ")
        if not key:
            raise CommandError("Configure evaluation key or pass --prompt-key")
        artifact = {
            "pipeline": "provision-first-v1"
            if options["provision_first"]
            else "coverage-mapping-v2",
            "case_id": identifier,
            "source_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "source_snapshot": request.source_snapshot,
            "source_manifest": request.source_manifest,
            "source_fingerprint": request.source_fingerprint,
            "request_fingerprint": request.request_fingerprint,
            "model": request.requested_model,
            "status": "running",
            "dispatches": [],
        }
        # Exclusive reservation before the first request also protects concurrent runs.
        try:
            with path.open("x") as output:
                json.dump(artifact, output)
        except OSError:
            raise CommandError(
                "Cannot reserve output artifact; no requests sent"
            ) from None

        def save():
            path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n")

        provider = get_provider(request.provider)

        def generate(preflight):
            dispatch = {
                "request_fingerprint": preflight.request_fingerprint,
                "status": "in_flight",
            }
            artifact["dispatches"].append(dispatch)
            save()
            try:
                result = provider.enhance_bill(
                    api_key=key,
                    request=preflight,
                    timeout_seconds=settings.LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS,
                )
            except ProviderError as exc:
                dispatch.update(
                    status="failed",
                    failure_category=exc.category,
                    validation_code=exc.validation_code,
                    outcome_unknown=exc.outcome_unknown,
                    usage=asdict(exc.usage),
                )
                save()
                raise

            dispatch.update(status="returned", result=asdict(result))
            save()
            return result

        try:
            runner = run
            if options["provision_first"]:
                from apps.legislation.evaluation.provision_generation import (
                    run as runner,
                )
            artifact["evaluation"] = runner(request, inventory, generate)
            artifact["status"] = "evaluated"
        finally:
            key = None
            save()
        self.stdout.write(
            json.dumps(
                {
                    "provider_calls": artifact["evaluation"]["provider_calls"],
                    "release_gate": artifact["evaluation"]["release_gate"],
                    "output": str(path),
                }
            )
        )
        if artifact["evaluation"]["release_gate"] != "pass":
            raise CommandError(
                "Not release-approved; inspect coverage and complete semantic review"
            )
