"""Offline extractor evaluation and replay of saved provider artifacts."""

import json
import math
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

from django.core.management.base import BaseCommand, CommandError
from django.test import override_settings
from jsonschema import ValidationError

from apps.legislation.enhancements.schema import validate_enhancement_output
from apps.legislation.evaluation.reader_quality import ai_items, nlp_items, score_reader
from apps.legislation.extraction.service import extract_contract

CORPUS_DIR = Path(__file__).resolve().parents[2] / "tests/fixtures/reader_evals"


class Command(BaseCommand):
    help = "Evaluate real NLP output or replay AI artifacts without network calls or database writes."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--case", action="append", dest="cases")
        parser.add_argument(
            "--replay", help="JSON artifact from evaluate_bill_enhancements"
        )
        parser.add_argument(
            "--output", help="Write JSON metrics before returning a failing exit status"
        )
        parser.add_argument("--input-usd-per-million", type=float)
        parser.add_argument("--output-usd-per-million", type=float)
        parser.add_argument(
            "--max-item-words",
            type=int,
            help="Fail the release gate if any displayed item exceeds this word limit",
        )

    def handle(self, *args, **options):
        if options["max_item_words"] is not None and options["max_item_words"] <= 0:
            raise CommandError("--max-item-words must be positive")
        cases = {
            case["id"]: case
            for path in sorted(CORPUS_DIR.glob("*.json"))
            if (case := json.loads(path.read_text()))
        }
        chosen = options["cases"] or list(cases)
        if set(chosen) - cases.keys():
            raise CommandError("Unknown evaluation case.")
        rates = None
        price = [options["input_usd_per_million"], options["output_usd_per_million"]]
        if any(p is not None for p in price):
            if not all(p is not None and math.isfinite(p) and p >= 0 for p in price):
                raise CommandError(
                    "Provide both finite, nonnegative per-million prices."
                )
            rates = dict(
                zip(("input_per_million", "output_per_million"), price, strict=True)
            )
        replay = None
        if options["replay"]:
            try:
                rows = json.loads(Path(options["replay"]).read_text())["results"]
                replay = {row["case_id"]: row for row in rows}
                if len(rows) != len(replay):
                    raise ValueError("Duplicate case IDs")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise CommandError("Invalid replay artifact") from exc
        results = []
        for case_id in chosen:
            case = cases[case_id]
            start = perf_counter()
            if replay is not None:
                row = replay.get(case_id, {})
                output = row.get("output", {})
                schema_valid = True
                try:
                    validate_enhancement_output(output, row.get("source_snapshot", []))
                except (ValidationError, TypeError, KeyError):
                    schema_valid = False
                if not isinstance(output, dict) or not schema_valid:
                    output = {}
                quality = score_reader(
                    {**case, "truncated": row.get("truncated", False)},
                    ai_items(output),
                    sources=row.get("source_snapshot", []),
                    usage=row.get("usage"),
                    rates=rates,
                    elapsed_ms=row.get("latency_ms"),
                )
                if not output or row.get("status") == "failed":
                    quality["passed"] = False
                    quality["failures"].append("missing_or_failed_output")
                quality["metrics"]["schema_valid"] = schema_valid
            else:
                with override_settings(LEGAL_NLP_V21_WRITE_ENABLED=True):
                    result = extract_contract(
                        bill=SimpleNamespace(
                            title=case["title"], jurisdiction="federal"
                        ),
                        document=SimpleNamespace(
                            extracted_text=case["text"],
                            version_label=case["source_version"],
                        ),
                    )
                quality = score_reader(
                    case,
                    nlp_items(result.contract_json),
                    elapsed_ms=round((perf_counter() - start) * 1000, 2),
                )
                exact = all(
                    case["text"][e.start_char : e.end_char] == e.quoted_text
                    for e in result.evidence
                )
                quality["metrics"]["exact_evidence_offsets"] = exact
                if not exact or result.fallback_reason:
                    quality["passed"] = False
                    quality["failures"].append("extraction_or_evidence_failure")
            if (
                options["max_item_words"]
                and quality["metrics"]["max_item_words"] > options["max_item_words"]
            ):
                quality["passed"] = False
                quality["failures"].append("readability_word_limit")
            results.append({"case_id": case_id, "quality": quality})
            self.stdout.write(
                f"{case_id}: {'PASS' if quality['passed'] else 'FAIL'}; missing={quality['missing_facts']}; fragments={quality['metrics']['fragment_count']}; long_items={quality['metrics']['items_over_60_words']}"
            )
        artifact = {
            "corpus_version": "reader-1",
            "mode": "ai-replay" if replay is not None else "nlp",
            "cost_rates": rates,
            "results": results,
        }
        if options["output"]:
            Path(options["output"]).write_text(json.dumps(artifact, indent=2) + "\n")
        if any(not row["quality"]["passed"] for row in results):
            raise CommandError(
                "Reader quality evaluation failed; inspect the recorded failures."
            )
