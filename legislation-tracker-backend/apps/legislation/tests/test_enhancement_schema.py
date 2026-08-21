import hashlib

import pytest
from jsonschema import ValidationError

from apps.legislation.enhancements.schema import validate_enhancement_output


def _source_snapshot():
    text = "The Secretary shall issue a rule within 180 days."
    return [
        {
            "source_ref": "src_0001",
            "kind": "document_chunk",
            "field_path": None,
            "section_label": "SEC. 2",
            "quoted_text": text,
            "start_char": 0,
            "end_char": len(text),
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        }
    ]


def _valid_output():
    return {
        "schema_version": "1.1",
        "overview": [
            {
                "text": "The bill directs the Secretary to issue a rule.",
                "source_refs": ["src_0001"],
            }
        ],
        "key_impacts": [],
        "obligations": [
            {
                "actor": "Secretary",
                "modality": "required",
                "action": "Issue a rule.",
                "conditions": None,
                "source_refs": ["src_0001"],
            }
        ],
        "funding_and_timing": [
            {
                "kind": "timing",
                "text": "The rule is due within 180 days.",
                "source_refs": ["src_0001"],
            }
        ],
        "uncertain_language": [],
    }


def test_valid_output_returns_a_detached_validated_value():
    payload = _valid_output()

    validated = validate_enhancement_output(payload, _source_snapshot())
    payload["overview"][0]["text"] = "mutated"

    assert validated["overview"][0]["text"] == (
        "The bill directs the Secretary to issue a rule."
    )


def test_unknown_or_missing_citations_reject_the_complete_output():
    unknown = _valid_output()
    unknown["overview"][0]["source_refs"] = ["src_9999"]
    with pytest.raises(ValidationError, match="Unknown source reference"):
        validate_enhancement_output(unknown, _source_snapshot())

    missing = _valid_output()
    missing["overview"][0]["source_refs"] = []
    with pytest.raises(ValidationError):
        validate_enhancement_output(missing, _source_snapshot())


def test_duplicate_citations_are_rejected_by_server_validation():
    duplicate = _valid_output()
    duplicate["overview"][0]["source_refs"] = ["src_0001", "src_0001"]

    with pytest.raises(ValidationError):
        validate_enhancement_output(duplicate, _source_snapshot())


def test_corrupted_server_source_hash_rejects_the_output():
    snapshot = _source_snapshot()
    snapshot[0]["text_sha256"] = "0" * 64

    with pytest.raises(ValidationError, match="source text hash"):
        validate_enhancement_output(_valid_output(), snapshot)


@pytest.mark.parametrize("extra_field", ["coverage_notes", "ambiguities"])
def test_provider_cannot_add_coverage_or_absence_escape_hatches(extra_field):
    payload = _valid_output()
    payload[extra_field] = []

    with pytest.raises(ValidationError):
        validate_enhancement_output(payload, _source_snapshot())
