import copy

import pytest
from jsonschema import ValidationError
from jsonschema import Draft202012Validator

from apps.legislation.enhancements.reader_citations import READER_ID_SCHEMA, citation_passages, resolve_reader_citations
from apps.legislation.tests.test_enhancement_reader_targets import packet


def test_server_resolves_exact_quote_without_model_transcription():
    target, source, output = packet()
    output["explanations"][0]["source_quotes"] = [{"source_ref": "src_0001", "quote_id": "p0001"}]
    original = copy.deepcopy(output)
    result = resolve_reader_citations(output, [target], [source])
    assert result["explanations"][0]["source_quotes"] == [{
        "source_ref": "src_0001",
        "quote": "Employers with at least 15 employees must adopt a policy within one year.",
    }]
    assert output == original


@pytest.mark.parametrize("mutation", ["unknown_id", "wrong_source", "wrong_target", "invented_quote", "outside_evidence"])
def test_ids_cannot_bypass_source_or_target_validation(mutation):
    target, source, output = packet()
    quote = {"source_ref": "src_0001", "quote_id": "p0001"}
    output["explanations"][0]["source_quotes"] = [quote]
    if mutation == "unknown_id":
        quote["quote_id"] = "p9999"
    elif mutation == "wrong_source":
        quote["source_ref"] = "src_9999"
    elif mutation == "wrong_target":
        source["reader_targets"] = [{**target, "target_id": "other"}]
    elif mutation == "invented_quote":
        quote["quote"] = "No employer has obligations."
    else:
        target["evidence_ranges"] = [[1000, 1100]]
    with pytest.raises(ValidationError):
        resolve_reader_citations(output, [target], [source])


def test_passages_retain_all_whitespace_and_stay_within_quote_limit():
    text = ("The Secretary shall publish a report.\n\n" * 31) + "The amount is $10,000."
    passages = citation_passages({"quoted_text": text})
    assert "".join(p["text"] for p in passages) == text
    assert all(len(p["text"]) <= 800 for p in passages)
    assert any(p["quote_id"] is None for p in passages)  # Repeated text is not guessed.


def test_summary_uses_the_same_id_resolution():
    _, source, output = packet()
    output["explanations"] = []
    output["summary"] = [{"text": "Covered employers must adopt a policy.",
                          "source_quotes": [{"source_ref": "src_0001", "quote_id": "p0001"}]}]
    result = resolve_reader_citations(output, [], [source])
    assert result["summary"][0]["source_quotes"][0]["quote"] == source["quoted_text"]


@pytest.mark.parametrize("mutation", ["explained_with_reason", "unresolved_with_text", "unresolved_with_quotes", "unresolved_without_reason"])
def test_provider_schema_prevents_contradictory_outcomes(mutation):
    _, _, output = packet()
    item = output["explanations"][0]
    item["source_quotes"] = [{"source_ref": "src_0001", "quote_id": "p0001"}]
    if mutation == "explained_with_reason":
        item["unresolved_reason"] = "External context needed."
    else:
        item.update(status="unresolved", text=None, unresolved_reason="External context needed.", source_quotes=[])
        if mutation == "unresolved_with_text":
            item["text"] = "A partial explanation."
        elif mutation == "unresolved_with_quotes":
            item["source_quotes"] = [{"source_ref": "src_0001", "quote_id": "p0001"}]
        else:
            item["unresolved_reason"] = None
    with pytest.raises(ValidationError):
        Draft202012Validator(READER_ID_SCHEMA).validate(output)


def test_valid_unresolved_outcome_preserves_original_fallback():
    target, source, output = packet()
    output["explanations"][0].update(status="unresolved", text=None,
        unresolved_reason="Requires external law.", source_quotes=[])
    assert resolve_reader_citations(output, [target], [source]) == output
