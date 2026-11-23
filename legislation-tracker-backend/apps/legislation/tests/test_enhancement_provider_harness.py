import json
from types import SimpleNamespace

import pytest

from apps.legislation.enhancements.providers.base import ProviderError, ProviderUsage
from apps.legislation.enhancements.providers.harness import (
    ensure_citation_repair_fits,
    ensure_request_fits,
    parse_json_output,
    select_bill_schema,
    wire_schema,
)
from apps.legislation.enhancements.providers.openai import OpenAIEnhancementProvider


class FakeResponses:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


class FakeClientFactory:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(responses=self.responses)


def _request():
    return SimpleNamespace(
        requested_model="gpt-5.6-luna",
        reasoning_effort="none",
        output_schema_version=None,
        request_envelope={
            "instructions": "Analyze only supplied text.",
            "bill": {"id": 4, "title": "Test Act"},
            "source_packet": {
                "truncated": False,
                "sources": [
                    {
                        "source_ref": "src_0001",
                        "quoted_text": "The Secretary shall issue a rule.",
                    }
                ],
                "coverage_checklist": [],
            },
        },
    )


def _completed_response(output_text=None):
    if output_text is None:
        output_text = json.dumps({"ok": True})
    return SimpleNamespace(
        id="resp_test_123",
        status="completed",
        model="gpt-5.6-luna-2026-08-01",
        output_text=output_text,
        output=[],
        usage=SimpleNamespace(input_tokens=120, output_tokens=45, total_tokens=165),
    )


# ---------------------------------------------------------------------------
# wire_schema / unsupported keyword contract
# ---------------------------------------------------------------------------


def test_wire_schema_strips_declared_unsupported_keywords():
    schema = {"type": "array", "uniqueItems": True, "items": {"type": "string", "uniqueItems": True}}
    stripped = wire_schema(schema, unsupported_keywords=frozenset({"uniqueItems"}))
    assert "uniqueItems" not in json.dumps(stripped)
    assert stripped == {"type": "array", "items": {"type": "string"}}


def test_wire_schema_keeps_unique_items_when_no_unsupported_keywords():
    schema = {"type": "array", "uniqueItems": True}
    kept = wire_schema(schema, unsupported_keywords=frozenset())
    assert kept == schema


def test_wire_schema_default_keeps_all_keywords():
    schema = {"type": "array", "uniqueItems": True}
    assert wire_schema(schema) == schema


# ---------------------------------------------------------------------------
# schema selection
# ---------------------------------------------------------------------------


def test_select_bill_schema_default_provider_output():
    request = _request()
    input_payload = {
        "bill": request.request_envelope["bill"],
        "source_packet": request.request_envelope["source_packet"],
    }
    from apps.legislation.enhancements.schema import PROVIDER_OUTPUT_SCHEMA

    assert select_bill_schema(request, input_payload) is PROVIDER_OUTPUT_SCHEMA


# ---------------------------------------------------------------------------
# parse_json_output failing closed
# ---------------------------------------------------------------------------


def test_parse_json_malformed_fails_closed():
    with pytest.raises(ProviderError) as caught:
        parse_json_output("not-json", usage=ProviderUsage(1, 2, 3), response_id="r", resolved_model="m")
    assert caught.value.validation_code == "provider_invalid_json"


def test_parse_json_non_object_fails_closed():
    with pytest.raises(ProviderError) as caught:
        parse_json_output("[]", usage=ProviderUsage(1, 2, 3), response_id="r", resolved_model="m")
    assert caught.value.validation_code == "provider_output_not_object"


def test_parse_json_fenced_fails_closed():
    with pytest.raises(ProviderError) as caught:
        parse_json_output("```json\n{\"a\": 1}\n```", usage=ProviderUsage(1, 2, 3), response_id="r", resolved_model="m")
    assert caught.value.validation_code == "provider_invalid_json"


def test_parse_json_multi_object_fails_closed():
    with pytest.raises(ProviderError) as caught:
        parse_json_output('{"a": 1}{"b": 2}', usage=ProviderUsage(1, 2, 3), response_id="r", resolved_model="m")
    assert caught.value.validation_code == "provider_invalid_json"


def test_parse_json_valid_returns_result():
    result = parse_json_output('{"ok": true}', usage=ProviderUsage(1, 2, 3), response_id="r", resolved_model="m")
    assert result.output == {"ok": True}
    assert result.response_id == "r"


# ---------------------------------------------------------------------------
# oversize rejection before network
# ---------------------------------------------------------------------------


def test_oversize_rejection_before_network():
    responses = FakeResponses(result=_completed_response())
    provider = OpenAIEnhancementProvider(client_factory=FakeClientFactory(responses))
    with pytest.raises(ProviderError) as error:
        provider.repair_citations(
            api_key="test",
            request=_request(),
            payload={"citations": ["x" * 120001]},
            timeout_seconds=30,
        )
    assert error.value.category == "request_too_large"
    assert responses.calls == []


def test_ensure_request_fits_helper():
    with pytest.raises(ProviderError):
        ensure_request_fits({"x": "y" * 10}, max_bytes=1)
    ensure_request_fits({"x": "y"}, max_bytes=1000)


def test_ensure_citation_repair_fits_helper():
    with pytest.raises(ProviderError):
        ensure_citation_repair_fits({"citations": ["x" * 120001]})


# ---------------------------------------------------------------------------
# four provider methods routing
# ---------------------------------------------------------------------------


def test_enhance_bill_routes_to_bill_enhancement_schema():
    response = _completed_response(json.dumps({
        "schema_version": "1.0", "overview": [], "key_impacts": [], "obligations": [],
        "funding_and_timing": [], "uncertain_language": [], "glossary": [],
    }))
    responses = FakeResponses(result=response)
    provider = OpenAIEnhancementProvider(client_factory=FakeClientFactory(responses))
    result = provider.enhance_bill(api_key="test", request=_request(), timeout_seconds=30)
    assert isinstance(result.output, dict)
    assert responses.calls[0]["text"]["format"]["name"] == "bill_enhancement_v1_1"


def test_generate_provisions_routes_source_first():
    response = _completed_response(json.dumps({"provisions": []}))
    responses = FakeResponses(result=response)
    provider = OpenAIEnhancementProvider(client_factory=FakeClientFactory(responses))
    request = _request()
    request.request_envelope["source_first_payload"] = {"units": [], "passages": {}}
    result = provider.generate_provisions(api_key="test", request=request, timeout_seconds=30)
    assert "provisions" in result.output
    assert responses.calls[0]["text"]["format"]["name"].startswith("source_first_")


def test_repair_provisions_routes_source_first():
    response = _completed_response(json.dumps({"provisions": []}))
    responses = FakeResponses(result=response)
    provider = OpenAIEnhancementProvider(client_factory=FakeClientFactory(responses))
    request = _request()
    request.request_envelope["source_first_payload"] = {"units": [], "passages": {}}
    result = provider.repair_provisions(api_key="test", request=request, timeout_seconds=30)
    assert "provisions" in result.output
    assert responses.calls[0]["text"]["format"]["name"].startswith("source_first_")


def test_generate_synopsis_routes_source_first():
    response = _completed_response(json.dumps({"text": "A.", "explanation_ids": []}))
    responses = FakeResponses(result=response)
    provider = OpenAIEnhancementProvider(client_factory=FakeClientFactory(responses))
    request = _request()
    request.request_envelope["source_first_payload"] = {"explanations": []}
    result = provider.generate_synopsis(api_key="test", request=request, timeout_seconds=30)
    assert "explanation_ids" in result.output
    assert responses.calls[0]["text"]["format"]["name"].startswith("source_first_")
