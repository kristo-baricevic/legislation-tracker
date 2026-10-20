import hashlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from jsonschema import ValidationError

from apps.legislation.enhancements.schema import validate_enhancement_output
from apps.legislation.enhancements.glossary import attach_targets, definition_targets
from apps.legislation.enhancements.serializers import _expanded_result


def packet():
    text = "Commission means the Equal Employment Opportunity Commission. Secretary means the Secretary of Labor."
    return [{
        "source_ref": "src_0001", "quoted_text": text,
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "start_char": 0, "end_char": len(text),
        "glossary_targets": [{
            "definition_id": "definition-1", "contract_id": 10,
            "term": "Commission", "definition": "the Equal Employment Opportunity Commission",
            "scope": [], "start_char": 0, "end_char": 61,
        }],
    }]


def output():
    return {
        "schema_version": "1.3", "overview": [], "key_impacts": [],
        "obligations": [], "funding_and_timing": [], "uncertain_language": [],
        "glossary": [{
            "definition_id": "definition-1",
            "text": "The Equal Employment Opportunity Commission.",
            "source_refs": ["src_0001"],
            "source_quotes": [{
                "source_ref": "src_0001",
                "quote": "Commission means the Equal Employment Opportunity Commission.",
            }],
        }],
    }


def test_glossary_accepts_an_exact_scoped_definition_citation():
    assert validate_enhancement_output(output(), packet())["glossary"][0]["definition_id"] == "definition-1"


def test_glossary_rejects_unknown_definition_and_neighboring_citation():
    wrong_id = output()
    wrong_id["glossary"][0]["definition_id"] = "definition-2"
    with pytest.raises(ValidationError):
        validate_enhancement_output(wrong_id, packet())
    neighbor = output()
    neighbor["glossary"][0]["source_quotes"][0]["quote"] = "Secretary means the Secretary of Labor."
    with pytest.raises(ValidationError):
        validate_enhancement_output(neighbor, packet())


def test_legacy_analysis_without_glossary_remains_readable():
    old = output()
    old["schema_version"] = "1.2"
    del old["glossary"]
    assert validate_enhancement_output(old, packet()) == old


def test_targets_require_current_document_evidence_and_exclude_external_definitions():
    contract = SimpleNamespace(
        pk=10, document_id=5,
        contract_json={"definitions": [
            {"id": "d1", "term": "Commission", "definition": "the EEOC"},
            {"id": "d2", "term": "college", "definition": "the meaning given in section 101"},
        ]},
        evidence_spans=Mock(),
    )
    contract.evidence_spans.filter.return_value = [
        SimpleNamespace(field_path=f"definitions[{i}].definition", start_char=0, end_char=61)
        for i in range(2)
    ]
    document = SimpleNamespace(pk=5, bill=SimpleNamespace(latest_contract=contract))
    targets = definition_targets(document)
    assert [t["definition_id"] for t in targets] == ["d1"]
    assert attach_targets([{"start_char": 0, "end_char": 61}], targets)[0]["glossary_targets"] == targets
    assert "glossary_targets" not in attach_targets([{"start_char": 1, "end_char": 61}], targets)[0]
    document.pk = 6
    assert definition_targets(document) == []


def test_serialization_binds_server_owned_definition_identity():
    expanded = _expanded_result(SimpleNamespace(result_json=output(), source_snapshot_json=packet()))
    term = expanded["glossary"][0]
    assert (term["contract_id"], term["term"]) == (10, "Commission")
    assert term["cited_sources"][0]["start_char"] == 0
    assert term["cited_sources"][0]["end_char"] == 61


def test_duplicate_glossary_targets_are_rejected():
    duplicate = output()
    duplicate["glossary"] *= 2
    with pytest.raises(ValidationError):
        validate_enhancement_output(duplicate, packet())


def test_batches_cover_every_definition_exactly_once_without_truncation():
    from apps.legislation.enhancements import glossary
    from django.test import override_settings
    bill = SimpleNamespace(id=1, jurisdiction="federal", session=119, bill_number="HR 7583",
                           title="Test", status="Introduced", introduced_at=None)
    text = ""
    targets = []
    for i in range(24):
        passage = f"Term {i} means a worker who meets condition {i}, except seasonal workers.\n"
        targets.append(dict(definition_id=f"d{i}", contract_id=10, term=f"Term {i}",
                            definition=passage, scope=[], start_char=len(text), end_char=len(text)+len(passage)))
        text += passage
    with override_settings(LLM_ENHANCEMENT_MAX_REQUEST_BYTES=50000,
                           LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS=50000):
        batches = glossary.build_glossary_batches(bill, text, "IH", targets)
    ids = [t["definition_id"] for batch in batches for source in batch["sources"]
           for t in source["glossary_targets"]]
    assert ids == [f"d{i}" for i in range(24)]
    assert len(batches) == 6
    assert all(source["quoted_text"] == text[source["start_char"]:source["end_char"]]
               for batch in batches for source in batch["sources"])


def test_batch_cannot_silently_omit_a_definition():
    from apps.legislation.enhancements import glossary
    missing = output()
    missing["glossary"] = []
    with pytest.raises(ValidationError):
        glossary.validate_glossary_batch(missing, packet())


def test_oversized_definition_blocks_preflight_instead_of_disappearing():
    from apps.legislation.enhancements import glossary
    from apps.legislation.enhancements.source_packet import PreflightUnavailable
    from django.test import override_settings
    bill = SimpleNamespace(id=1, jurisdiction="federal", session=119, bill_number="HR 1",
                           title="Test", status="Introduced", introduced_at=None)
    text = "a" * 100000
    target = dict(definition_id="large", contract_id=10, term="large", definition=text,
                  scope=[], start_char=0, end_char=len(text))
    with override_settings(LLM_ENHANCEMENT_MAX_REQUEST_BYTES=20000,
                           LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS=20000):
        with pytest.raises(PreflightUnavailable):
            glossary.build_glossary_batches(bill, text, "IH", [target])


def test_combined_batches_can_exceed_the_single_response_item_limit():
    import copy
    sources, combined = packet(), output()
    target, item = sources[0]["glossary_targets"][0], combined["glossary"][0]
    sources[0]["glossary_targets"] = [
        {**copy.deepcopy(target), "definition_id": f"d{i}"} for i in range(70)
    ]
    combined["glossary"] = [
        {**copy.deepcopy(item), "definition_id": f"d{i}"} for i in range(70)
    ]
    assert len(validate_enhancement_output(combined, sources, aggregate_glossary=True)["glossary"]) == 70
    with pytest.raises(ValidationError):
        validate_enhancement_output(combined, sources)


def test_main_validation_failure_keeps_field_path_and_stage_without_model_text():
    from apps.legislation.enhancements.glossary import execute_glossary_batches
    from apps.legislation.enhancements.providers.base import ProviderError, ProviderResult, ProviderUsage
    invalid = output()
    invalid["glossary"][0]["source_refs"] = ["src_0001", "src_0002"]
    sources = packet()
    sources.append({**sources[0], "source_ref": "src_0002"})
    preflight = SimpleNamespace(source_snapshot=sources, glossary_batches=(),
        output_schema_version="1.3", request_envelope={"source_packet": {"sources": sources}})
    with pytest.raises(ProviderError) as caught:
        execute_glossary_batches(
            ProviderResult(invalid, ProviderUsage(10, 5, 15), "r1", "test"),
            preflight, None, "test", lambda *_: None,
        )
    assert caught.value.validation_detail["path"] == "/glossary/0/source_quotes"
    assert caught.value.validation_detail["stage"] == "main_analysis"
    assert caught.value.citation_resolution["failed_stage"] == "main_analysis"
    assert caught.value.usage.total_tokens == 15
    assert "Commission" not in str(caught.value.validation_detail)
