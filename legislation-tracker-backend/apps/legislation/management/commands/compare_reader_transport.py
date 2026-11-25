"""One explicitly bounded free-model probe for an existing reader work unit."""

import json
import os
from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import requests
from django.core.management.base import BaseCommand, CommandError
from jsonschema import ValidationError

from apps.accounts.llm_credentials import decrypt_credential
from apps.legislation.enhancements.private_diagnostics import capture_transport
from apps.legislation.enhancements.provider_registry import get_provider
from apps.legislation.enhancements.providers.base import ProviderError
from apps.legislation.enhancements.reader_steps import _validate_response
from apps.legislation.enhancements.source_packet import canonical_json_bytes
from apps.legislation.models import BillEnhancementWorkUnit


def verified_free_model(model):
    response = requests.get("https://openrouter.ai/api/v1/models", timeout=15)
    response.raise_for_status()
    row = next((r for r in response.json()["data"] if r["id"] == model), None)
    prices = row.get("pricing", {}) if row else {}
    if (
        not model.endswith(":free")
        or not {"completion", "prompt"}.issubset(prices)
        or any(Decimal(str(v)) != 0 for v in prices.values())
    ):
        raise CommandError(
            "A directly selectable model with verified zero pricing is required"
        )
    return row


class Command(BaseCommand):
    help = "Replay the recorded reader request; --live requires explicit free model, owner and ceilings."

    def add_arguments(self, parser):
        parser.add_argument("--attempt", required=True, type=int)
        parser.add_argument("--unit", required=True)
        parser.add_argument("--live", action="store_true")
        parser.add_argument("--owner", type=int)
        parser.add_argument("--model")
        parser.add_argument("--max-calls", type=int)
        parser.add_argument("--max-tokens", type=int)
        parser.add_argument("--max-usd", type=Decimal)
        parser.add_argument("--evidence-dir", type=Path)

    def handle(self, **options):
        work = (
            BillEnhancementWorkUnit.objects.select_related(
                "attempt__enhancement", "attempt__credential"
            )
            .defer("attempt__execution_config")
            .get(attempt_id=options["attempt"], node_key=options["unit"])
        )
        attempt = work.attempt
        envelope = work.request_json["envelope"]
        sources = work.request_json["sources"]
        maximum = envelope["max_output_tokens"]
        # Includes source, instructions and schema plus the adapter framing allowance.
        estimate = len(canonical_json_bytes(envelope)) + 1024
        digest = sha256(canonical_json_bytes(work.request_json)).hexdigest()
        self.stdout.write(
            json.dumps(
                {
                    "request_hash": digest,
                    "reserved_input": estimate,
                    "reserved_output": maximum,
                }
            )
        )
        if not options["live"]:
            return
        model, directory = options["model"], options["evidence_dir"]
        if (
            not model
            or not directory
            or options["max_calls"] != 2
            or options["max_usd"] != 0
            or not options["max_tokens"]
            or 2 * (estimate + maximum) > options["max_tokens"]
        ):
            raise CommandError(
                "The two-call experiment requires explicit and sufficient token and zero-dollar ceilings"
            )
        credential = attempt.credential
        if (
            not options["owner"]
            or attempt.enhancement.user_id != options["owner"]
            or credential is None
            or credential.user_id != options["owner"]
            or credential.revision != attempt.credential_revision
            or credential.provider != "openrouter"
            or not credential.enabled
        ):
            raise CommandError(
                "The authorized payer and enabled original credential revision must match"
            )
        metadata = verified_free_model(model)
        limits = metadata["top_provider"]
        required = {"structured_outputs", "max_tokens"}
        if attempt.enhancement.reasoning_effort != "none":
            required.add("reasoning")
        if (
            not required.issubset(metadata["supported_parameters"])
            or maximum > (limits.get("max_completion_tokens") or 0)
            or estimate + maximum > (limits.get("context_length") or 0)
        ):
            raise CommandError(
                "The model does not establish the necessary request capabilities"
            )
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.stat().st_mode & 0o077:
            raise CommandError("Evidence directory must be private")
        key = decrypt_credential(credential)
        request = SimpleNamespace(
            provider="openrouter",
            requested_model=model,
            request_envelope=envelope,
            source_snapshot=sources,
            output_schema_version=envelope["output_schema_version"],
            reasoning_effort=attempt.enhancement.reasoning_effort,
        )
        for adapter in ("existing", "langchain"):
            path = directory / f"{attempt.pk}-{digest}-{adapter}.json"
            # An ambiguous dispatch continues to consume its entire reservation after a crash.
            with os.fdopen(
                os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
            ) as evidence:
                row = {
                    "adapter": adapter,
                    "model": model,
                    "hash": digest,
                    "reserved_tokens": estimate + maximum,
                    "price_usd": "0",
                    "pricing": metadata["pricing"],
                    "state": "reserved",
                }
                evidence.write(json.dumps(row) + "\n")
                evidence.flush()
                os.fsync(evidence.fileno())
                started = monotonic()
                try:

                    def capture(payload):
                        evidence.write(json.dumps({"transport": payload}) + "\n")
                        evidence.flush()

                    with capture_transport(capture):
                        result = get_provider(
                            "openrouter", adapter=adapter
                        ).enhance_bill(
                            api_key=key, request=request, timeout_seconds=120
                        )
                except ProviderError as error:
                    row.update(
                        state=error.validation_code or error.category,
                        resolved=error.resolved_model,
                        usage=asdict(error.usage),
                        response_id=error.response_id,
                    )
                else:
                    row.update(
                        resolved=result.resolved_model,
                        usage=asdict(result.usage),
                        response_id=result.response_id,
                        state="passed",
                    )
                    if result.resolved_model != model:
                        row["state"] = "model_mismatch"
                    else:
                        try:
                            _validate_response(result.output, request)
                        except ValidationError as error:
                            row["state"] = "rejected"
                            row["validation_path"] = list(error.absolute_path)
                row["elapsed_seconds"] = round(monotonic() - started, 3)
                evidence.write(json.dumps(row) + "\n")
                self.stdout.write(
                    json.dumps({k: v for k, v in row.items() if k != "response_id"})
                )
