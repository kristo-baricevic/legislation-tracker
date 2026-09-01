import json
from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

from django.test import override_settings

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
    if isinstance(value, str):
        # Claims are judged on their controlled semantic value. Source newlines
        # remain independently gated by the exact evidence assertions below.
        return " ".join(value.split())
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze(item)) for key, item in value.items()))
    return value


def claim_key(category: str, fields: Mapping[str, object]) -> tuple[object, ...]:
    return (category,) + tuple(
        _freeze(fields.get(name)) for name in CORE_FIELDS[category]
    )


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
        assert (
            occurrence is not None or len(starts) == 1
        ), f"Fixture evidence quote is ambiguous without occurrence: {quote!r}"
        selected = starts[occurrence or 0]
        offsets.append((selected, selected + len(quote)))
    return offsets


def _prepare_fixture(fixture, path: Path):
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


def load_fixtures(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and payload.get("evaluation_kind"):
        return []
    cases = payload.get("cases") if isinstance(payload, dict) else None
    fixtures = cases if isinstance(cases, list) else [payload]
    return [_prepare_fixture(fixture, path) for fixture in fixtures]


def test_legal_nlp_evaluation_corpus_meets_release_gates():
    paths = sorted(FIXTURE_DIR.glob("*.json"))
    assert len(paths) >= 25, "Legal NLP evaluation requires at least 25 fixtures"
    fixtures = [fixture for path in paths for fixture in load_fixtures(path)]
    public_excerpts = [
        fixture
        for fixture in fixtures
        if fixture.get("corpus_kind") == "public_domain_excerpt"
    ]
    assert (
        len(public_excerpts) >= 25
    ), "Legal NLP evaluation requires at least 25 public-domain federal excerpts"
    assert (
        len({fixture["source_reference"] for fixture in public_excerpts}) >= 3
    ), "Public-domain excerpts must cover at least three source documents"
    assert all(fixture.get("source_locator") for fixture in public_excerpts)
    assert any(
        len(fixture["source_text"]) >= 1_000 for fixture in public_excerpts
    ), "Public-domain corpus requires at least one long section"
    assert (
        sum(bool(fixture["forbidden_claims"]) for fixture in fixtures) >= 5
    ), "Legal NLP evaluation requires at least five explicit negative cases"

    totals = Counter()
    by_category = defaultdict(Counter)
    expected_by_category = Counter()
    forbidden_false_positives = []
    missing_expected_evidence = []
    all_contracts_valid = True
    all_evidence_exact = True

    for fixture in fixtures:
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
        all_contracts_valid = (
            all_contracts_valid and result.schema_version == "2.0-legal-nlp"
        )
        if result.schema_version == "2.0-legal-nlp":
            validate_contract(
                result.contract_json, result.evidence, fixture["source_text"]
            )
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
    assert all(
        expected_by_category[category] >= 3 for category in CORE_FIELDS
    ), expected_by_category
    assert precision >= 0.95, f"precision={precision:.3f}; {diagnostics}"
    assert recall >= 0.70, f"recall={recall:.3f}; {diagnostics}"
    assert not forbidden_false_positives, forbidden_false_positives


def _reader_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _extract_v21(fixture: Mapping[str, object]):
    bill = SimpleNamespace(
        jurisdiction="federal",
        title=fixture.get("title", "Reader fixture"),
        summary="",
    )
    document = SimpleNamespace(
        extracted_text=fixture["source_text"],
        version_label=fixture.get("version_label", "Enrolled"),
    )
    with override_settings(LEGAL_NLP_V21_WRITE_ENABLED=True):
        return extract_contract(document=document, bill=bill)


def _assert_exact_v21_evidence(source: str, result) -> None:
    assert result.schema_version == "2.1-legal-nlp", result.fallback_reason
    validate_contract(result.contract_json, result.evidence, source)
    assert all(
        source[span.start_char : span.end_char] == span.quoted_text
        for span in result.evidence
    )


def _financial_projection(item: Mapping[str, object]) -> dict[str, object]:
    return {
        key: item.get(key)
        for key in (
            "financial_action",
            "direction",
            "amount",
            "amount_type",
            "currency",
        )
    }


def test_hr1_reader_fixture_has_clean_controlled_output_and_exact_raw_evidence():
    fixture = _reader_fixture("reader_brief_hr1_excerpt.json")
    source = str(fixture["source_text"])

    result = _extract_v21(fixture)

    _assert_exact_v21_evidence(source, result)
    contract = result.contract_json
    rendered = [
        str(item["display_text"])
        for category in ("line_items", "financial_items")
        for item in contract[category]
    ]
    assert fixture["expected_reader_text"] in rendered
    actual_financial = [
        _financial_projection(item) for item in contract["financial_items"]
    ]
    assert all(item in actual_financial for item in fixture["expected_financial"])
    assert all(
        artifact not in text
        for artifact in fixture["forbidden_display_fragments"]
        for text in rendered
    )
    assert contract["reader_stats"]["financial_item_count"] == len(
        contract["financial_items"]
    )
    assert not result.fallback_reason


def test_financial_fixture_gates_every_supported_action_and_negative_cases():
    fixture = _reader_fixture("reader_brief_financial_actions.json")
    source = str(fixture["source_text"])

    result = _extract_v21(fixture)

    _assert_exact_v21_evidence(source, result)
    actual = [
        _financial_projection(item) for item in result.contract_json["financial_items"]
    ]
    expected = fixture["expected_financial"]
    assert actual == expected
    action_counts = Counter(item["financial_action"] for item in expected)
    assert set(action_counts) == set(fixture["supported_actions"])
    assert min(action_counts.values()) >= 3
    assert not ({item["amount"] for item in actual} & set(fixture["forbidden_amounts"]))


def test_capacity_fixture_preserves_all_101_items_ids_amounts_and_offsets():
    fixture = _reader_fixture("reader_brief_funding_101.json")
    source = str(fixture["source_text"])

    result = _extract_v21(fixture)

    _assert_exact_v21_evidence(source, result)
    items = result.contract_json["financial_items"]
    assert len(items) == 101
    evidence_by_path = defaultdict(list)
    for span in result.evidence:
        evidence_by_path[span.field_path].append(span)
    actual = []
    for index, item in enumerate(items):
        span = evidence_by_path[f"financial_items[{index}].display_text"][0]
        actual.append(
            {
                "id": item["id"],
                "financial_action": item["financial_action"],
                "amount": item["amount"],
                "start_char": span.start_char,
                "end_char": span.end_char,
            }
        )
    assert actual == fixture["expected_items"]


def test_offset_shift_changes_source_ids_but_not_semantic_financial_claims():
    fixture = _reader_fixture("reader_brief_offset_shift.json")
    before = _extract_v21({**fixture, "source_text": fixture["before_source_text"]})
    after = _extract_v21({**fixture, "source_text": fixture["after_source_text"]})

    _assert_exact_v21_evidence(str(fixture["before_source_text"]), before)
    _assert_exact_v21_evidence(str(fixture["after_source_text"]), after)
    before_items = before.contract_json["financial_items"]
    after_items = after.contract_json["financial_items"]
    assert [_financial_projection(item) for item in before_items] == [
        _financial_projection(item) for item in after_items
    ]
    assert [item["id"] for item in before_items] != [item["id"] for item in after_items]
    assert [
        span.start_char
        for span in after.evidence
        if span.field_path.startswith("financial_items[")
        and span.field_path.endswith(".display_text")
    ] == [
        span.start_char + fixture["expected_offset_shift"]
        for span in before.evidence
        if span.field_path.startswith("financial_items[")
        and span.field_path.endswith(".display_text")
    ]
