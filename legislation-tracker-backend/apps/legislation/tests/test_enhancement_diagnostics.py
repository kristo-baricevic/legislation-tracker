import json

import pytest
from jsonschema import ValidationError

from apps.legislation.enhancements.schema import validate_enhancement_output

from .test_enhancement_schema import _precise_output, _source_snapshot


def test_quote_failure_has_safe_specific_reason_and_location():
    from apps.legislation.enhancements.diagnostics import validation_diagnostic

    value = _precise_output()
    value["overview"][0]["source_quotes"][0]["quote"] = "private-provider-text"
    with pytest.raises(ValidationError) as caught:
        validate_enhancement_output(value, _source_snapshot())
    detail = validation_diagnostic(caught.value)
    assert detail["code"] == "citation_quote_not_found"
    assert detail["path"] == "/overview/0/source_quotes/0/quote"
    assert "private-provider-text" not in json.dumps(detail)


def test_schema_failure_does_not_persist_untrusted_error_messages():
    from apps.legislation.enhancements.diagnostics import validation_diagnostic

    value = _precise_output()
    value["overview"][0]["text"] = {"sk-secret-key": "private-output"}
    with pytest.raises(ValidationError) as caught:
        validate_enhancement_output(value, _source_snapshot())
    detail = validation_diagnostic(caught.value)
    assert detail["code"] == "schema_type"
    assert detail["path"] == "/overview/0/text"
    assert "sk-secret" not in json.dumps(detail)
    assert "private-output" not in json.dumps(detail)
