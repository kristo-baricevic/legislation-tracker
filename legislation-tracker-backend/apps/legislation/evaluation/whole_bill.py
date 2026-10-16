"""Whole-bill review packets. Mechanical checks never certify legal meaning."""

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path

from jsonschema import ValidationError

ROOT = Path(__file__).resolve().parents[4] / "docs/benchmarks/bill-understanding"
CASES = {
    "BILLS-119hr9300ih": "Postsecondary Student Success Act of 2026",
    "BILLS-119hr1589ih": "American Dream and Promise Act of 2025",
    "BILLS-119s5enr": "Laken Riley Act",
}


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalized(value):
    return " ".join(value.split())


class SourceText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.inside = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "pre":
            self.inside = True

    def handle_endtag(self, tag):
        if tag == "pre":
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.parts.append(data)


def expectations(markdown):
    """Import existing independently authored annotations, not generated output."""
    result = []
    for line in markdown.splitlines():
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if line.startswith("|") and re.fullmatch(r"[FM]\d+", cells[0]):
            result.append(
                {
                    "id": cells[0],
                    "financial": cells[0].startswith("M"),
                    "answer": " | ".join(cells[1:-1]),
                    "source_reference": cells[-1],
                }
            )
    # S. 5 uses one source-backed Markdown subsection per expectation.
    for match in re.finditer(
        r"^### (LR-[FM]\d+) — ([^\n]+)\n(.*?)(?=^##|\Z)", markdown, re.M | re.S
    ):
        identifier, heading, body = match.groups()
        answer = "\n".join(
            line for line in body.splitlines() if not line.startswith(">")
        )
        result.append(
            {
                "id": identifier,
                "financial": "-M" in identifier,
                "answer": normalized(answer),
                "source_reference": heading,
                "evidence_quotes": re.findall(r"^> (.+)$", body, re.M),
            }
        )
    if not result or len({row["id"] for row in result}) != len(result):
        raise ValueError("Missing or duplicate answer-key identifiers")
    return result


def load_cases(root=ROOT):
    manifest = {
        row["package_id"]: row
        for row in json.loads((root / "sources/manifest.json").read_text())
    }
    cases = []
    for identifier, title in CASES.items():
        source = manifest[identifier]
        raw = (root / source["raw_file"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise ValueError(f"Raw source drift: {identifier}")
        parser = SourceText()
        parser.feed(raw.decode("utf-8"))
        text = (root / source["decoded_text_file"]).read_text()
        if text != "".join(parser.parts):
            raise ValueError(f"Decoded source drift: {identifier}")
        answer_path = f"answers/{identifier}.md"
        answer = (root / answer_path).read_text()
        quotes = re.findall(r"^> (.+)$", answer, re.M)
        if not quotes or any(
            normalized(quote) not in normalized(text) for quote in quotes
        ):
            raise ValueError(f"Answer evidence not found in source: {identifier}")
        cases.append(
            {
                "id": identifier,
                "title": title,
                "text": text,
                "text_sha256": digest(text),
                "raw_sha256": source["sha256"],
                "answer_sha256": digest(answer),
                "answer_path": answer_path,
                "source_url": source["source_url"],
                "expectations": expectations(answer),
                "answer_key_status": "draft_pending_independent_acceptance",
            }
        )
    return cases


def assess(case, items, *, pipeline, failures=()):
    failures = list(failures)
    words = [len(item.get("text", "").split()) for item in items]
    for index, item in enumerate(items):
        if not item.get("evidence_valid"):
            failures.append(f"invalid_or_missing_evidence:{index}")
    return {
        "pipeline": pipeline,
        "release_gate": "fail" if failures else "blocked",
        "gate_reasons": [
            "answer_key_not_accepted",
            "semantic_and_screen_review_pending",
        ]
        + ([] if items else ["no_output"]),
        "mechanical_failures": failures,
        "dimensions": {
            "coverage": {
                "status": "needs_human_review",
                "annotated_expectations": len(case["expectations"]),
                "annotated_financial_rows": sum(
                    e["financial"] for e in case["expectations"]
                ),
                "note": "Rows include restrictions and nested allocations; do not sum as payments or use as an automatic recall denominator.",
            },
            "accuracy": {"status": "needs_human_review", "critical_errors": None},
            "source_support": {
                "mechanical_status": (
                    "fail" if failures else "checked" if items else "not_run"
                ),
                "semantic_status": "needs_human_review",
                "note": "Exact source linkage does not establish that a citation supports a claim.",
            },
            "readability": {
                "status": "needs_human_review",
                "item_count": len(items),
                "max_item_words": max(words, default=0),
                "items_over_60_words": sum(w > 60 for w in words),
            },
            "honest_uncertainty": {"status": "needs_human_review"},
        },
        "review_rows": [
            {
                **e,
                "verdict": "unreviewed",
                "output_item_ids": [],
                "coverage": None,
                "accuracy": None,
                "source_support": None,
                "material_conditions_preserved": None,
                "accessible_in_screen": None,
                "severity": None,
                "notes": "",
            }
            for e in case["expectations"]
        ],
        "output_items": [
            {**item, "review_item_id": f"{pipeline}-{i:04d}"}
            for i, item in enumerate(items)
        ],
    }


def replay_items(case, row, *, resolution_audit=None, resolved_output=None):
    from apps.legislation.enhancements.citations import resolve_citations
    from apps.legislation.enhancements.providers.base import (
        ProviderResult,
        ProviderUsage,
    )
    from apps.legislation.enhancements.schema import validate_enhancement_output

    from .reader_quality import ai_items

    if (
        row.get("source_text_sha256") != case["text_sha256"]
        or row.get("case_id") != case["id"]
    ):
        raise ValueError("AI replay must identify the exact pinned bill text hash")
    if row.get("status") != "succeeded" and not (
        row.get("status") == "failed"
        and row.get("failure_category") == "invalid_output"
        and isinstance(row.get("output"), dict)
    ):
        raise ValueError("AI replay did not succeed")
    sources = row.get("source_snapshot", [])
    for source in sources:
        quote = source.get("quoted_text", "")
        start, end = source.get("start_char"), source.get("end_char")
        if (
            not quote
            or type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= len(case["text"])
            or case["text"][start:end] != quote
        ):
            raise ValueError("AI replay source is not an exact span of the pinned text")
    saved_usage = row.get("usage") or {}
    result = resolve_citations(
        ProviderResult(
            row["output"],
            ProviderUsage(
                **{
                    key: saved_usage.get(key)
                    for key in ("input_tokens", "output_tokens", "total_tokens")
                }
            ),
            row.get("response_id", ""),
            row.get("resolved_model", ""),
        ),
        sources,
    )
    if resolution_audit is not None:
        resolution_audit.update(result.citation_resolution)
    output = validate_enhancement_output(result.output, sources)
    if resolved_output is not None:
        resolved_output.update(output)
    items = ai_items(output)
    for item in items:
        item["evidence_valid"] = bool(item.get("source_refs"))
    return items


def markdown_report(report):
    lines = [
        "# Whole-bill benchmark: provisional baseline",
        "",
        "No case is release-approved. Draft keys and semantic/UI review remain outstanding.",
        "",
        "| Bill/version | Pipeline | Gate | Items | Mechanical failures | Long items (>60 words) |",
        "|---|---|---|---:|---:|---:|",
    ]
    for case in report["results"]:
        for mode, result in case["pipelines"].items():
            readability = result["dimensions"]["readability"]
            lines.append(
                f"| {case['case_id']} | {mode} | {result['release_gate']} | {readability['item_count']} | {len(result['mechanical_failures'])} | {readability['items_over_60_words']} |"
            )
    lines += ["", "## Current source-policy preflight (not sent to a provider)", ""]
    for case in report["results"]:
        packet = case.get("current_source_packet", {})
        coverage = packet.get("coverage", {})
        omitted = (
            ", ".join(s["label"] for s in coverage.get("omitted_sections", []))
            or "none"
        )
        lines.append(
            f"- {case['case_id']}: {packet.get('status', 'not_run')}; complete document: {coverage.get('complete_document', False)}; omitted: {omitted}."
        )
    lines += [
        "",
        "AI outputs below are historical replays, not new generations using these packets. Passing quote validation does not clear recorded semantic failures.",
        "",
        "## Review procedure",
        "",
        "For each expectation in the JSON report, map the relevant output item IDs and check coverage, actors, legal effect, amounts, denominators, dates, exceptions and uncertainty against the pinned source. Do not credit words merely appearing in an evidence quote.",
        "",
        "Inspect every output claim for unsupported additions, including claims not represented in the answer key. Review readability separately. Confirm all financial provisions are accessible through the actual UI, including pagination and expansion.",
        "",
        "Release requires accepted keys, no critical factual errors, all annotated financial provisions accessible, source support for every material explanation, and no meaning-changing omitted conditions. Unknown or unreviewed is BLOCKED, never PASS.",
        "",
        "AI not_run means no matching saved artifact was supplied. No provider requests were made.",
        "",
    ]
    return "\n".join(lines)


def run_benchmark(*, replay_path=None, selected=None):
    from dataclasses import asdict
    from types import SimpleNamespace

    from django.test import override_settings

    from apps.legislation.enhancements.prompts import (
        PROMPT_VERSION,
        SOURCE_PACKET_VERSION,
    )
    from apps.legislation.enhancements.source_packet import (
        PreflightUnavailable,
        select_document_sources,
    )
    from apps.legislation.extraction.service import extract_contract

    from .reader_quality import nlp_items

    cases = load_cases()
    if selected:
        if set(selected) - CASES.keys():
            raise ValueError("Unknown whole-bill case")
        cases = [case for case in cases if case["id"] in selected]
    replay = {}
    if replay_path:
        rows = json.loads(Path(replay_path).read_text())["results"]
        replay = {row["case_id"]: row for row in rows}
        if len(rows) != len(replay) or set(replay) - CASES.keys():
            raise ValueError("Duplicate or unknown AI replay cases")
    results = []
    for case in cases:
        bill = SimpleNamespace(
            id=case["id"],
            title=case["title"],
            jurisdiction="federal",
            session=119,
            bill_number=case["id"],
            status="pinned benchmark version",
            introduced_at=None,
        )
        try:
            sources, envelope, packet_bytes = select_document_sources(
                bill, case["text"], case["id"]
            )
            current_packet = {
                "provider_calls": 0,
                "status": "prepared_not_sent",
                "source_packet_version": SOURCE_PACKET_VERSION,
                "prompt_version": PROMPT_VERSION,
                "request_sha256": hashlib.sha256(packet_bytes).hexdigest(),
                "request_bytes": len(packet_bytes),
                "sources": sources,
                "coverage": envelope["source_packet"]["coverage"],
            }
        except PreflightUnavailable as exc:
            current_packet = {
                "provider_calls": 0,
                "status": "unavailable",
                "reason": exc.reason,
            }
        with override_settings(LEGAL_NLP_V21_WRITE_ENABLED=True):
            output = extract_contract(
                bill=SimpleNamespace(title=case["title"], jurisdiction="federal"),
                document=SimpleNamespace(
                    extracted_text=case["text"], version_label=case["id"]
                ),
            )
        items = nlp_items(
            output.contract_json, evidence=output.evidence, source_text=case["text"]
        )
        nlp = assess(
            case,
            items,
            pipeline="nlp",
            failures=(
                [f"extractor_fallback:{output.fallback_reason}"]
                if output.fallback_reason
                else []
            ),
        )
        nlp["status"] = "evaluated"
        nlp["contract"] = output.contract_json
        nlp["evidence"] = [asdict(span) for span in output.evidence]
        ai = assess(case, [], pipeline="ai")
        ai["status"] = "not_run"
        if case["id"] in replay:
            row = replay[case["id"]]
            resolution_audit, resolved_output = {}, {}
            try:
                ai = assess(
                    case,
                    replay_items(
                        case,
                        row,
                        resolution_audit=resolution_audit,
                        resolved_output=resolved_output,
                    ),
                    pipeline="ai",
                )
                ai["status"] = "evaluated"
                ai["generation"] = "historical_replay_not_regenerated"
                ai["gate_reasons"].append("current_source_policy_generation_not_run")
                ai["source_snapshot"] = row["source_snapshot"]
                ai["output"] = resolved_output
                ai["original_output"] = row["output"]
                from .coverage_inventory import assess_inventory, build_inventory

                inventory = build_inventory(
                    row["source_snapshot"], document_text=case["text"]
                )
                ai["coverage_candidates"] = inventory
                ai["candidate_coverage"] = assess_inventory(
                    inventory, resolved_output, row["source_snapshot"]
                )
                ai["usage"] = row.get("usage")
                ai["resolved_model"] = row.get("resolved_model")
                ai["truncated"] = row.get("truncated")
                if row.get("truncated") is not False:
                    ai["gate_reasons"].append("partial_or_unknown_ai_input_coverage")
            except (ValueError, TypeError, KeyError, ValidationError) as exc:
                ai = assess(case, [], pipeline="ai", failures=[f"invalid_replay:{exc}"])
                ai["status"] = "invalid_artifact"
            ai["citation_resolution"] = resolution_audit
        results.append(
            {k: v for k, v in case.items() if k not in {"text", "expectations"}}
            | {
                "case_id": case["id"],
                "current_source_packet": current_packet,
                "pipelines": {"nlp": nlp, "ai": ai},
            }
        )
    return {
        "evaluator_version": "whole-bill-review-1",
        "provisional": True,
        "release_gate": (
            "fail"
            if any(
                p["release_gate"] == "fail"
                for r in results
                for p in r["pipelines"].values()
            )
            else "blocked"
        ),
        "provider_calls": 0,
        "results": results,
    }
