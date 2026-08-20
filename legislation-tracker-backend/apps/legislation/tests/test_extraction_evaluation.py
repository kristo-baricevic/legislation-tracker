import json
from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

from apps.legislation.extraction.schema import validate_contract
from apps.legislation.extraction.service import extract_contract

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "legal_nlp"
CORE_FIELDS = {
    "requirements": ("modality", "actor", "action", "object", "conditions"),
    "funding_items": (
        "amount",
        "amount_type",
        "currency",
        "fiscal_years",
        "purpose",
    ),
    "timeline_items": (
        "timeline_type",
        "date",
        "relative_value",
        "relative_unit",
        "trigger",
    ),
    "definitions": ("term", "definition", "definition_type"),
    "applicability": ("subject", "scope", "applicability_type"),
    "amendment_operations": (
        "target",
        "operation",
        "removed_text",
        "inserted_text",
    ),
}


def _freeze(value):
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze(item)) for key, item in value.items()))
    return value


def claim_key(category: str, fields: Mapping[str, object]) -> tuple[object, ...]:
    return (category,) + tuple(_freeze(fields.get(name)) for name in CORE_FIELDS[category])


def _evidence_offsets(source_text, evidence):
    offsets = []
    for entry in evidence:
        quote = entry["quote"]
        starts = []
        cursor = 0
        while True:
            start = source_text.find(quote, cursor)
            if start < 0:
                break
            starts.append(start)
            cursor = start + 1
        assert starts, f"Fixture evidence quote is absent: {quote!r}"
        occurrence = entry.get("occurrence")
        assert occurrence is not None or len(starts) == 1, (
            f"Fixture evidence quote is ambiguous without occurrence: {quote!r}"
        )
        selected = starts[occurrence or 0]
        offsets.append((selected, selected + len(quote)))
    return offsets


def load_fixture(path: Path):
    fixture = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "name",
        "title",
        "version_label",
        "source_text",
        "source_reference",
        "expected_claims",
        "forbidden_claims",
    }
    assert required <= fixture.keys(), f"Missing fixture keys in {path.name}"
    for claim in fixture["expected_claims"] + fixture["forbidden_claims"]:
        claim["offsets"] = _evidence_offsets(fixture["source_text"], claim["evidence"])
    return fixture


def test_legal_nlp_evaluation_corpus_meets_release_gates():
    paths = sorted(FIXTURE_DIR.glob("*.json"))
    assert len(paths) >= 25, "Legal NLP evaluation requires at least 25 fixtures"

    totals = Counter()
    by_category = defaultdict(Counter)
    expected_by_category = Counter()
    forbidden_false_positives = []
    missing_expected_evidence = []
    all_contracts_valid = True
    all_evidence_exact = True

    for path in paths:
        fixture = load_fixture(path)
        bill = SimpleNamespace(
            jurisdiction="federal",
            title=fixture["title"],
            summary="",
        )
        document = SimpleNamespace(
            extracted_text=fixture["source_text"],
            version_label=fixture["version_label"],
        )
        result = extract_contract(document=document, bill=bill)
        all_contracts_valid = all_contracts_valid and result.schema_version == "2.0-legal-nlp"
        if result.schema_version == "2.0-legal-nlp":
            validate_contract(result.contract_json, result.evidence, fixture["source_text"])
        all_evidence_exact = all_evidence_exact and all(
            fixture["source_text"][span.start_char : span.end_char] == span.quoted_text
            for span in result.evidence
        )

        actual = Counter()
        for category in CORE_FIELDS:
            for item in result.contract_json.get(category, []):
                actual[claim_key(category, item)] += 1
        expected = Counter(
            claim_key(claim["category"], claim["fields"])
            for claim in fixture["expected_claims"]
        )
        expected_by_category.update(
            claim["category"] for claim in fixture["expected_claims"]
        )
        forbidden = {
            claim_key(claim["category"], claim["fields"])
            for claim in fixture["forbidden_claims"]
        }
        evidence_by_path = defaultdict(list)
        for span in result.evidence:
            evidence_by_path[span.field_path].append((span.start_char, span.end_char))
        actual_evidence = Counter()
        for category in CORE_FIELDS:
            for index, item in enumerate(result.contract_json.get(category, [])):
                key = claim_key(category, item)
                for offsets in evidence_by_path[f"{category}[{index}].display_text"]:
                    actual_evidence[(key, offsets)] += 1
        expected_evidence = Counter(
            (claim_key(claim["category"], claim["fields"]), offsets)
            for claim in fixture["expected_claims"]
            for offsets in claim["offsets"]
        )
        if not expected_evidence <= actual_evidence:
            missing_expected_evidence.append(
                (fixture["name"], expected_evidence - actual_evidence)
            )

        for key in actual.keys() | expected.keys():
            true_positive = min(actual[key], expected[key])
            false_positive = max(actual[key] - expected[key], 0)
            false_negative = max(expected[key] - actual[key], 0)
            category = key[0]
            totals.update(tp=true_positive, fp=false_positive, fn=false_negative)
            by_category[category].update(
                tp=true_positive, fp=false_positive, fn=false_negative
            )
        forbidden_false_positives.extend(
            (fixture["name"], key) for key in forbidden if actual[key]
        )

    precision = totals["tp"] / max(totals["tp"] + totals["fp"], 1)
    recall = totals["tp"] / max(totals["tp"] + totals["fn"], 1)
    diagnostics = {
        category: dict(counts) for category, counts in sorted(by_category.items())
    }
    assert all_contracts_valid, diagnostics
    assert all_evidence_exact, diagnostics
    assert not missing_expected_evidence, missing_expected_evidence
    assert all(expected_by_category[category] >= 3 for category in CORE_FIELDS), (
        expected_by_category
    )
    assert precision >= 0.95, f"precision={precision:.3f}; {diagnostics}"
    assert recall >= 0.70, f"recall={recall:.3f}; {diagnostics}"
    assert not forbidden_false_positives, forbidden_false_positives
