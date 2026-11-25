"""Reconciliation envelopes must survive the real provider schema boundary."""

import copy
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from apps.legislation.enhancements.providers.anthropic import (
    AnthropicEnhancementProvider,
)
from apps.legislation.enhancements.providers.base import ProviderError
from apps.legislation.enhancements.providers.gemini import GeminiEnhancementProvider
from apps.legislation.enhancements.providers.harness import select_bill_schema
from apps.legislation.enhancements.providers.openai import OpenAIEnhancementProvider
from apps.legislation.enhancements.providers.openai_compatible import (
    OpenAICompatibleEnhancementProvider,
)
from apps.legislation.enhancements.reader_citations import READER_PROMPT_VERSION
from apps.legislation.enhancements.reader_reconciliation import (
    _base_items,
    _request,
    validate_dependency_review,
)

from .test_reader_reconciliation import Provider, _fixture


def dependency_request(settings, provider="openai"):
    preflight, review = _fixture(settings, count=2)
    settings.LLM_READER_MODEL_CAPACITIES[f"{provider}/model"] = (
        settings.LLM_READER_MODEL_CAPACITIES["test/model"]
    )
    envelope = {
        **preflight.request_envelope,
        "bill": {"id": 1, "title": "Hospital Grants Act"},
        "prompt_version": READER_PROMPT_VERSION,
        "output_schema_version": "1.4",
    }
    preflight = replace(
        preflight,
        provider=provider,
        reasoning_effort="none",
        prompt_version=READER_PROMPT_VERSION,
        output_schema_version="1.4",
        request_envelope=envelope,
    )
    records = {record["record_id"]: record for record in review["factual_records"]}
    owner = preflight.source_snapshot[0]["source_ref"]
    items = _base_items(review, {owner})
    return _request(
        preflight,
        records,
        owner,
        list(records)[1:],
        items,
        base_items=items,
    )


def _sdk_provider(provider_name, response, calls):
    def create(**kwargs):
        calls.append(kwargs)
        return response

    def client_factory(**kwargs):
        return SimpleNamespace(
            responses=SimpleNamespace(create=create),
            messages=SimpleNamespace(create=create),
            models=SimpleNamespace(generate_content=create),
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )

    provider_class = {
        "openai": OpenAIEnhancementProvider,
        "anthropic": AnthropicEnhancementProvider,
        "gemini": GeminiEnhancementProvider,
        "openrouter": OpenAICompatibleEnhancementProvider,
    }[provider_name]
    options = (
        {"structured_output_mode": "json_schema"}
        if provider_name == "openrouter"
        else {}
    )
    return provider_class(client_factory=client_factory, **options)


def _sdk_response(output):
    text = json.dumps(output)
    # The four SDKs expose different response/usage fields. Supplying them here
    # keeps every adapter's real response parser in the tested path.
    return SimpleNamespace(
        id="dependency-response",
        response_id="dependency-response",
        status="completed",
        model="model",
        model_version="model",
        output_text=text,
        output=[],
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text, refusal=None),
                finish_reason="stop",
            )
        ],
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[SimpleNamespace(text=text, thought=False)]
                ),
                finish_reason="STOP",
            )
        ],
        prompt_feedback=None,
        usage=SimpleNamespace(
            input_tokens=120,
            output_tokens=45,
            prompt_tokens=120,
            completion_tokens=45,
            total_tokens=165,
        ),
        usage_metadata=SimpleNamespace(
            prompt_token_count=120,
            candidates_token_count=45,
            thoughts_token_count=0,
            total_token_count=165,
        ),
    )


@pytest.mark.parametrize(
    "provider_name", ["openai", "anthropic", "gemini", "openrouter"]
)
def test_dependency_schema_and_result_through_real_adapter(settings, provider_name):
    request = dependency_request(settings, provider_name)
    original_schema = copy.deepcopy(request.request_envelope["output_schema"])
    # This fixture response cites the distant eligibility restriction. Only the
    # upstream SDK is replaced; schema selection, wire conversion, JSON parsing,
    # and dependency validation all use production code.
    output = Provider().enhance_bill(request=request).output
    calls = []
    provider = _sdk_provider(provider_name, _sdk_response(output), calls)

    result = provider.enhance_bill(
        api_key="offline", request=request, timeout_seconds=1
    )

    assert len(calls) == 1
    call = calls[0]
    if provider_name == "openai":
        schema = call["text"]["format"]["schema"]
        payload = json.loads(call["input"])
        output_limit = call["max_output_tokens"]
    elif provider_name == "anthropic":
        schema = call["output_config"]["format"]["schema"]
        payload = json.loads(call["messages"][0]["content"])
        output_limit = call["max_tokens"]
    elif provider_name == "gemini":
        schema = call["config"].response_json_schema
        payload = json.loads(call["contents"])
        output_limit = call["config"].max_output_tokens
    else:
        schema = call["response_format"]["json_schema"]["schema"]
        payload = json.loads(call["messages"][1]["content"])
        output_limit = call["max_tokens"]
    assert set(schema["required"]) == {"page_id", "record_checks", "items"}
    assert schema["properties"]["page_id"]["enum"] == [
        request.request_envelope["dependency_review"]["page_id"]
    ]
    assert payload["source_packet"] == request.request_envelope["source_packet"]
    assert output_limit == request.request_envelope["max_output_tokens"]
    assert request.request_envelope["output_schema"] == original_schema
    Draft202012Validator(schema).validate(result.output)
    valid = validate_dependency_review(result.output, request)
    assert valid["items"]["policy_changes:0"]["text"] == (
        "Public hospitals providing emergency care may apply for grants."
    )
    assert (
        valid["items"]["policy_changes:0"]["source_quotes"][-1]["source_ref"]
        == "src_0003"
    )
    assert result.usage.total_tokens == 165


@pytest.mark.parametrize(
    "field,value",
    [
        ("prompt_version", "an-older-reader-prompt"),
        ("dependency_review", {}),
        ("dependency_review", "not-a-descriptor"),
        ("output_schema", None),
        ("output_schema", {}),
    ],
)
def test_dependency_stage_rejects_incomplete_envelopes_before_dispatch(
    settings, field, value
):
    request = dependency_request(settings)
    request.request_envelope[field] = value
    calls = []
    provider = _sdk_provider("openai", None, calls)

    with pytest.raises(ProviderError) as error:
        provider.enhance_bill(api_key="offline", request=request, timeout_seconds=1)

    assert error.value.validation_code == "source_snapshot_invalid"
    assert error.value.usage.total_tokens == 0
    assert calls == []


def test_legacy_reader_schema_routing_remains_compatible(settings):
    from apps.legislation.enhancements.reader_citations import READER_ID_SCHEMA
    from apps.legislation.enhancements.reader_targets import READER_SCHEMA
    from apps.legislation.enhancements.schema import PROVIDER_OUTPUT_SCHEMA

    request = dependency_request(settings)
    envelope = request.request_envelope
    envelope.pop("dependency_review")
    envelope["output_schema_version"] = "1.4"
    envelope["output_schema"] = READER_ID_SCHEMA
    assert select_bill_schema(request, {}) is READER_ID_SCHEMA

    envelope["prompt_version"] = "an-older-reader-prompt"
    assert select_bill_schema(request, {}) is READER_SCHEMA

    envelope["output_schema_version"] = "1.3"
    assert select_bill_schema(request, {}) is PROVIDER_OUTPUT_SCHEMA
