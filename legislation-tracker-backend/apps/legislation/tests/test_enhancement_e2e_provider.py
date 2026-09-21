import hashlib
from types import SimpleNamespace

import pytest

from apps.legislation.enhancements.providers.e2e import E2EEnhancementProvider
from apps.legislation.enhancements.schema import (
    OUTPUT_SCHEMA_VERSION,
    validate_enhancement_output,
)


@pytest.mark.parametrize(
    "text",
    [
        "The Secretary shall award grants to rural hospitals.",
        "SEC. 1. Grants. " + "Additional program terms. " * 100,
    ],
)
def test_e2e_provider_output_passes_the_worker_schema(text):
    sources = [
        {
            "source_ref": "src_0001",
            "quoted_text": text,
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        }
    ]
    result = E2EEnhancementProvider().enhance_bill(
        api_key="e2e-test-key",
        request=SimpleNamespace(source_snapshot=sources, estimated_input_tokens=100),
        timeout_seconds=90,
    )
    output = validate_enhancement_output(
        result.output, sources, expected_version=OUTPUT_SCHEMA_VERSION
    )
    assert output["overview"][0]["source_quotes"][0]["quote"] in text
