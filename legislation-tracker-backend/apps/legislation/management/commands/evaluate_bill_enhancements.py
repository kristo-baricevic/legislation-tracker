import hashlib
import json
from pathlib import Path
from time import perf_counter
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
from apps.legislation.evaluation.reader_quality import ai_items, score_reader

from .evaluate_reader_quality import CORPUS_DIR

CORPUS_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "llm_enhancement"
    / "evaluation_cases.json"
)


def _case_preflight(case):
    sources = []
    for index, fixture_source in enumerate(case["sources"], start=1):
        text = fixture_source["quoted_text"]
        sources.append(
            {
                "source_ref": f"src_{index:04d}",
                "kind": fixture_source.get("kind", "document_chunk"),
                "field_path": fixture_source.get("field_path"),
                "section_label": fixture_source["section_label"],
                "quoted_text": text,
                "start_char": 0,
                "end_char": len(text),
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
        )
    bill = SimpleNamespace(
        id=case["id"],
        jurisdiction=case["jurisdiction"],
        session=119,
        bill_number=case["bill_number"],
        title=case["title"],
        status=case["status"],
        introduced_at=None,
    )
    envelope = _request_envelope(bill, sources, truncated=case["truncated"])
    request_bytes = canonical_json_bytes(envelope)
    source_fingerprint = hashlib.sha256(
        canonical_json_bytes(
            {
                "source_packet_version": SOURCE_PACKET_VERSION,
                "source_identity": {"evaluation_case_id": case["id"]},
                "sources": sources,
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
            "total_candidates": case.get("total_candidates", len(sources)),
            "selected_count": len(sources),
            "truncated": case["truncated"],
        },
        source_snapshot=sources,
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
        parser.add_argument(
            "--reader-case",
            help="Run a gold-annotated reader corpus case instead of the legacy corpus",
        )
        parser.add_argument("--fail-on-quality", action="store_true")

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
        if options["reader_case"]:
            gold = next(
                (
                    json.loads(p.read_text())
                    for p in CORPUS_DIR.glob("*.json")
                    if json.loads(p.read_text())["id"] == options["reader_case"]
                ),
                None,
            )
            if gold is None:
                raise CommandError("Unknown reader case")
            cases = [
                {
                    **gold,
                    "jurisdiction": "federal",
                    "bill_number": gold["id"],
                    "status": gold["source_version"],
                    "category": "reader-quality",
                    "truncated": False,
                    "review_labels": {
                        "must_capture": [f["id"] for f in gold["required_facts"]]
                    },
                    "sources": [
                        {
                            "quoted_text": gold["text"],
                            "section_label": gold["source_version"],
                        }
                    ],
                }
            ]
            corpus = {
                "corpus_version": "reader-1",
                "review_rubric": {
                    "automated": "annotated fact regression; not semantic entailment"
                },
            }
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
            prepared = [(case, _case_preflight(case)) for case in cases[:case_limit]]
            # Validate the entire budget before spending on the first case.
            for case, preflight in prepared:
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
            for case, preflight in prepared:
                started = perf_counter()
                try:
                    provider_result = provider.enhance_bill(
                        api_key=api_key,
                        request=preflight,
                        timeout_seconds=settings.LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS,
                    )
                    validated = validate_enhancement_output(
                        provider_result.output,
                        preflight.source_snapshot,
                        expected_version=preflight.output_schema_version,
                    )
                    results.append(
                        {
                            "case_id": case["id"],
                            "category": case["category"],
                            "review_labels": case["review_labels"],
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
                            "quality": score_reader(
                                case,
                                ai_items(validated),
                                sources=preflight.source_snapshot,
                                elapsed_ms=round((perf_counter() - started) * 1000, 2),
                            ),
                            "latency_ms": round((perf_counter() - started) * 1000, 2),
                        }
                    )
                    self.stdout.write(f"case={case['id']} status=succeeded")
                except (ProviderError, ValidationError) as exc:
                    usage = (
                        exc.usage
                        if isinstance(exc, ProviderError)
                        else provider_result.usage
                    )
                    failure_category = (
                        exc.category
                        if isinstance(exc, ProviderError)
                        else "invalid_output"
                    )
                    results.append(
                        {
                            "case_id": case["id"],
                            "category": case["category"],
                            "review_labels": case["review_labels"],
                            "status": "failed",
                            "failure_category": failure_category,
                            "usage": {
                                "input_tokens": usage.input_tokens,
                                "output_tokens": usage.output_tokens,
                                "total_tokens": usage.total_tokens,
                            },
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
                "review_rubric": corpus["review_rubric"],
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
        if options["fail_on_quality"] and any(
            row["status"] != "succeeded" or not row["quality"]["passed"]
            for row in results
        ):
            raise CommandError(
                "Reader quality evaluation failed; inspect the evaluation artifact."
            )
