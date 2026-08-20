from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.legislation.extraction.schema import ContractValidationError
from apps.legislation.extraction.service import extract_contract


def bill(jurisdiction="federal"):
    return SimpleNamespace(
        jurisdiction=jurisdiction,
        title="Test Act",
        summary="Metadata summary.",
    )


def document(text):
    return SimpleNamespace(extracted_text=text, version_label="Introduced")


def test_extract_contract_selects_v2_for_supported_federal_text():
    result = extract_contract(
        document=document("SEC. 2. REPORTS\nThe Secretary shall publish a report."),
        bill=bill(),
    )

    assert result.schema_version == "2.0-legal-nlp"
    assert result.method == "federal-rules"
    assert result.fallback_reason is None


@pytest.mark.parametrize(
    ("jurisdiction", "text", "reason"),
    [
        ("state", "SEC. 2. REPORTS\nThe Secretary shall report.", "unsupported_jurisdiction"),
        ("federal", "  ", "missing_source_text"),
        ("federal", "This bill creates a program.", "unrecognized_federal_structure"),
        ("federal", "SEC. 2. FINDINGS\nCongress finds a need.", "no_supported_claims"),
    ],
)
def test_extract_contract_uses_legacy_for_expected_rejections(
    jurisdiction, text, reason
):
    result = extract_contract(document=document(text), bill=bill(jurisdiction))

    assert result.schema_version == "1.1-deterministic"
    assert result.method == "legacy-deterministic"
    assert result.fallback_reason == reason


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("schema_validation_failed", "schema_validation_failed"),
        ("evidence_validation_failed", "evidence_validation_failed"),
    ],
)
def test_extract_contract_uses_legacy_for_validation_failures(reason, expected):
    with patch(
        "apps.legislation.extraction.renderer.validate_contract",
        side_effect=ContractValidationError(reason, "invalid contract"),
    ):
        result = extract_contract(
            document=document("SEC. 2. REPORTS\nThe Secretary shall report."),
            bill=bill(),
        )

    assert result.fallback_reason == expected
    assert result.method == "legacy-deterministic"


def test_extract_contract_does_not_swallow_unexpected_rule_errors():
    with patch(
        "apps.legislation.extraction.legal_rules.extract_claims",
        side_effect=RuntimeError("rule bug"),
    ), pytest.raises(RuntimeError, match="rule bug"):
        extract_contract(
            document=document("SEC. 2. REPORTS\nThe Secretary shall report."),
            bill=bill(),
        )
