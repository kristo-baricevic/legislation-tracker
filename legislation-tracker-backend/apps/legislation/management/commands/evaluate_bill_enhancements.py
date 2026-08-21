import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from jsonschema import ValidationError

from apps.legislation.enhancements.prompts import PROMPT_VERSION, SOURCE_PACKET_VERSION
from apps.legislation.enhancements.provider_registry import get_provider
from apps.legislation.enhancements.providers.base import ProviderError
from apps.legislation.enhancements.schema import (
    OUTPUT_SCHEMA_VERSION,
    validate_enhancement_output,
)
from apps.legislation.enhancements.source_packet import (
    _request_envelope,
    canonical_json_bytes,
    estimate_input_tokens,
)
from apps.legislation.enhancements.types import EnhancementPreflight

CORPUS_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "llm_enhancement"
    / "evaluation_cases.json"
)


def _case_preflight(case):
    text = case["source_text"]
    source = {
        "source_ref": "src_0001",
        "kind": "document_chunk",
        "field_path": None,
        "section_label": "Evaluation fixture",
        "quoted_text": text,
        "start_char": 0,
        "end_char": len(text),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    bill = SimpleNamespace(
        id=case["id"],
        jurisdiction=case["jurisdiction"],
        session=119,
        bill_number=case["bill_number"],
        title=case["title"],
        status=case["status"],
        introduced_at=None,
    )
    envelope = _request_envelope(bill, [source], truncated=case["truncated"])
    request_bytes = canonical_json_bytes(envelope)
    source_fingerprint = hashlib.sha256(
        canonical_json_bytes(
            {
                "source_packet_version": SOURCE_PACKET_VERSION,
                "source_identity": {"evaluation_case_id": case["id"]},
                "sources": [source],
            }
        )
    ).hexdigest()
    return EnhancementPreflight(
        provider=settings.LLM_ENHANCEMENT_PROVIDER,
        requested_model=settings.LLM_ENHANCEMENT_MODEL,
        reasoning_effort=settings.LLM_ENHANCEMENT_REASONING_EFFORT,
        prompt_version=PROMPT_VERSION,
        output_schema_version=OUTPUT_SCHEMA_VERSION,
        source_packet_version=SOURCE_PACKET_VERSION,
        source_fingerprint=source_fingerprint,
        request_fingerprint=hashlib.sha256(request_bytes).hexdigest(),
        source_manifest={
            "evaluation_case_id": case["id"],
            "source_kind": "document_chunk",
            "total_candidates": 1,
            "selected_count": 1,
            "truncated": case["truncated"],
        },
        source_snapshot=[source],
        request_envelope=envelope,
        request_bytes=request_bytes,
        estimated_input_tokens=estimate_input_tokens(request_bytes),
        truncated=case["truncated"],
    )


class Command(BaseCommand):
    help = "Run a bounded, explicitly authorized provider evaluation corpus."

    def add_arguments(self, parser):
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--case-limit", type=int, required=True)
        parser.add_argument("--max-input-tokens", type=int, required=True)
        parser.add_argument("--max-output-tokens", type=int, required=True)
        parser.add_argument("--output")

    def handle(self, *args, **options):
        if not options["execute"]:
            raise CommandError("Pass --execute to authorize provider requests.")
        case_limit = options["case_limit"]
        max_input_tokens = options["max_input_tokens"]
        max_output_tokens = options["max_output_tokens"]
        if case_limit <= 0:
            raise CommandError("--case-limit must be positive.")
        if max_input_tokens <= 0:
            raise CommandError("--max-input-tokens must be positive.")
        if max_output_tokens <= 0:
            raise CommandError("--max-output-tokens must be positive.")
        if max_input_tokens > settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS:
            raise CommandError("--max-input-tokens exceeds the application safety cap.")
        if max_output_tokens > settings.LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS:
            raise CommandError(
                "--max-output-tokens exceeds the application safety cap."
            )

        corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
        cases = corpus["cases"]
        if case_limit > len(cases):
            raise CommandError("--case-limit exceeds the versioned evaluation corpus.")
        api_key = getattr(settings, "LLM_ENHANCEMENT_EVALUATION_API_KEY", "")
        if not api_key:
            raise CommandError(
                "LLM_ENHANCEMENT_EVALUATION_API_KEY is required for evaluation."
            )

        self.stdout.write(
            "Evaluation budget: "
            f"cases={case_limit} max_input_tokens={max_input_tokens} "
            f"max_output_tokens={max_output_tokens} "
            f"maximum_total_output_tokens={case_limit * max_output_tokens} "
            f"model={settings.LLM_ENHANCEMENT_MODEL} "
            f"reasoning={settings.LLM_ENHANCEMENT_REASONING_EFFORT}"
        )
        provider = get_provider(settings.LLM_ENHANCEMENT_PROVIDER)
        results = []
        original_output_cap = settings.LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS
        settings.LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS = max_output_tokens
        try:
            for case in cases[:case_limit]:
                preflight = _case_preflight(case)
                if preflight.estimated_input_tokens > max_input_tokens:
                    raise CommandError(
                        f"Case {case['id']} exceeds --max-input-tokens before any call."
                    )
                if (
                    len(preflight.request_bytes)
                    > settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES
                ):
                    raise CommandError(
                        f"Case {case['id']} exceeds the request byte safety cap."
                    )
                try:
                    provider_result = provider.enhance_bill(
                        api_key=api_key,
                        request=preflight,
                        timeout_seconds=settings.LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS,
                    )
                    validated = validate_enhancement_output(
                        provider_result.output,
                        preflight.source_snapshot,
                    )
                    results.append(
                        {
                            "case_id": case["id"],
                            "category": case["category"],
                            "source_snapshot": preflight.source_snapshot,
                            "truncated": preflight.truncated,
                            "output": validated,
                            "usage": {
                                "input_tokens": provider_result.usage.input_tokens,
                                "output_tokens": provider_result.usage.output_tokens,
                                "total_tokens": provider_result.usage.total_tokens,
                            },
                            "resolved_model": provider_result.resolved_model,
                            "status": "succeeded",
                        }
                    )
                    self.stdout.write(f"case={case['id']} status=succeeded")
                except (ProviderError, ValidationError) as exc:
                    failure_category = (
                        exc.category
                        if isinstance(exc, ProviderError)
                        else "invalid_output"
                    )
                    results.append(
                        {
                            "case_id": case["id"],
                            "category": case["category"],
                            "status": "failed",
                            "failure_category": failure_category,
                        }
                    )
                    self.stdout.write(
                        f"case={case['id']} status=failed category={failure_category}"
                    )
        finally:
            settings.LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS = original_output_cap

        if options["output"]:
            artifact = {
                "corpus_version": corpus["corpus_version"],
                "provider": settings.LLM_ENHANCEMENT_PROVIDER,
                "requested_model": settings.LLM_ENHANCEMENT_MODEL,
                "reasoning_effort": settings.LLM_ENHANCEMENT_REASONING_EFFORT,
                "max_input_tokens": max_input_tokens,
                "max_output_tokens": max_output_tokens,
                "results": results,
            }
            output_path = Path(options["output"])
            output_path.write_text(
                json.dumps(artifact, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            self.stdout.write(f"Wrote evaluation artifact to {output_path}")
        else:
            self.stdout.write("No artifact written; pass --output with a local path.")
