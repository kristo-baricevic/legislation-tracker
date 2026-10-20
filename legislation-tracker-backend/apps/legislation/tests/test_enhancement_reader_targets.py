import copy
import hashlib
from types import SimpleNamespace

import pytest
from jsonschema import ValidationError

from apps.legislation.enhancements.reader_targets import (
    build_reader_targets, validate_reader_explanations,
)


def packet():
    text = "Employers with at least 15 employees must adopt a policy within one year."
    target = {
        "target_id": "line_item:policy", "kind": "line_item", "item_id": "policy",
        "contract_id": 7, "contract_hash": "contract-a", "document_id": 4,
        "document_content_hash": hashlib.sha256(text.encode()).hexdigest(),
        "original_text": text, "evidence_ranges": [[0, len(text)]],
    }
    source = {
        "source_ref": "src_0001", "quoted_text": text, "start_char": 0,
        "end_char": len(text), "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "reader_targets": [target],
    }
    output = {"schema_version": "1.4", "summary": [], "explanations": [{
        "target_id": target["target_id"], "status": "explained",
        "text": text, "unresolved_reason": None,
        "source_quotes": [{"source_ref": "src_0001", "quote": text}],
    }]}
    return target, source, output


def test_target_validator_preserves_supported_identity_and_does_not_mutate_input():
    target, source, output = packet()
    original = copy.deepcopy(output)
    assert validate_reader_explanations(output, [target], [source]) == original
    assert output == original


@pytest.mark.parametrize("mutation", ["unknown", "duplicate", "missing", "wrong_quote", "other_target"])
def test_target_validator_rejects_unsupported_replacements(mutation):
    target, source, output = packet()
    if mutation == "unknown":
        output["explanations"][0]["target_id"] = "line_item:other"
    elif mutation == "duplicate":
        output["explanations"] *= 2
    elif mutation == "missing":
        output["explanations"] = []
    elif mutation == "wrong_quote":
        output["explanations"][0]["source_quotes"][0]["quote"] = "No threshold applies."
    else:
        source["reader_targets"] = [{**target, "target_id": "line_item:other"}]
    with pytest.raises(ValidationError):
        validate_reader_explanations(output, [target], [source])


def test_unresolved_is_explicit_and_has_no_replacement_prose():
    target, source, output = packet()
    output["explanations"][0].update(status="unresolved", text=None,
                                     unresolved_reason="Needs outside context.", source_quotes=[])
    assert validate_reader_explanations(output, [target], [source])["explanations"][0]["text"] is None
    output["explanations"][0]["text"] = "A guessed explanation."
    with pytest.raises(ValidationError):
        validate_reader_explanations(output, [target], [source])


def test_duplicate_snapshot_identity_cannot_silently_collapse_targets():
    target, source, output = packet()
    with pytest.raises(ValidationError):
        validate_reader_explanations(output, [target, copy.deepcopy(target)], [source])


def test_targets_use_complete_enclosing_section_and_exact_relationships():
    text = "SEC. 101. Policy.\n(a) Employers with at least 15 employees must adopt a policy.\n(b) This section takes effect within one year.\nSEC. 102. Other.\nOther text."
    start, end = text.index("Employers"), text.index("\n(b)")
    item = {"id": "policy", "display_text": text[start:end], "evidence_paths": ["line_items[0].display_text"],
            "timeline_refs": ["deadline"], "exact_financial_refs": []}
    span = SimpleNamespace(field_path="line_items[0].display_text", start_char=start,
                           end_char=end, quoted_text=text[start:end])
    contract = SimpleNamespace(pk=7, document_id=4, contract_hash="contract-a",
        schema_version="2.1-legal-nlp", contract_json={"schema_version": "2.1-legal-nlp",
            "line_items": [item], "financial_items": [], "definitions": [],
            "timeline_items": [{"id": "deadline", "display_text": "Within one year."}]},
        evidence_spans=SimpleNamespace(all=lambda: [span]))
    document = SimpleNamespace(pk=4, extracted_text=text, raw_text="", bill=SimpleNamespace(latest_contract=contract))
    target = build_reader_targets(document)[0]
    assert target["contract_id"] == 7
    assert target["contract_hash"] == "contract-a"
    assert "within one year" in target["context_text"]
    assert "Other text" not in target["context_text"]
    assert target["facts"]["timeline_items"][0]["id"] == "deadline"
    contract.document_id = 99
    assert build_reader_targets(document) == []


def test_hr7583_context_keeps_policy_threshold_and_wage_formula_with_effective_dates():
    """Frozen doc 6346 sections 101/121; expectations read from source, not AI."""
    from pathlib import Path
    text = (Path(__file__).parent / "fixtures/reader_evals/hr7583-policy-wages.txt").read_text()
    items, spans = [], []
    for i, quote in enumerate((
        "each employer who has 15 or more employees shall adopt",
        "$3.60 an hour", "$1.50", "not more than $1,000", "not less than $5,000",
    )):
        start = text.index(quote)
        path = f"line_items[{i}].display_text"
        items.append({"id": str(i), "display_text": quote, "evidence_paths": [path]})
        spans.append(SimpleNamespace(field_path=path, start_char=start, end_char=start + len(quote), quoted_text=quote))
    contract = SimpleNamespace(pk=7896, document_id=6346, contract_hash="frozen-excerpts",
        schema_version="2.1-legal-nlp", contract_json={"schema_version": "2.1-legal-nlp",
            "line_items": items, "financial_items": [], "definitions": []},
        evidence_spans=SimpleNamespace(all=lambda: spans))
    document = SimpleNamespace(pk=6346, extracted_text=text, raw_text="", bill=SimpleNamespace(latest_contract=contract))
    targets = build_reader_targets(document)
    assert len(targets) == 5
    assert all(t["unavailable_reason"] is None for t in targets)
    policy = targets[0]["context_text"]
    assert "15 or more employees" in policy and "1 year after" in policy
    assert "annually" in policy and "not less than $5,000" in policy
    for target in targets[1:3]:
        source = target["context_text"]
        assert "$3.60" in source and "$1.50" in source and "lesser of" in source
        assert "first day of the third month" in source and "one day after" in source
        assert "not less than $5,000" not in source
