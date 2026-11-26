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


@pytest.mark.parametrize(
    "provider_name,stage,mode",
    [
        (provider, stage, "json_schema")
        for provider in ("openai", "anthropic", "gemini", "openrouter", "langchain")
        for stage in ("map", "dependency", "summary")
    ]
    + [
        (adapter, "map", mode)
        for adapter in ("openrouter", "langchain")
        for mode in ("json_object", "prompt_json")
    ],
)
def test_staged_http_wire_contract(settings, monkeypatch, provider_name, stage, mode):
    import socket

    import httpx
    import httpx2

    from apps.legislation.enhancements.provider_registry import get_provider

    adapter = "langchain" if provider_name == "langchain" else "existing"
    provider_name = "openrouter" if adapter == "langchain" else provider_name
    from apps.legislation.enhancements.reader_discovery import (
        INSTRUCTIONS,
        POLICY_INSTRUCTIONS,
        discovery_schema,
        resolve_discovery,
    )
    from apps.legislation.enhancements.reader_facts import FACTUAL_MAP_INSTRUCTIONS

    from .test_dependency_cache_migration import _stage_request
    from .test_reader_facts import _output, _sources

    base = dependency_request(settings, provider_name)
    env = dict(base.request_envelope)
    env.pop("dependency_review")
    env.update(prompt_version=READER_PROMPT_VERSION, output_schema_version="1.4")
    if stage == "map":
        sources = _sources(
            "The agency must publish an annual report while the program operates unless the agency closes."
        )
        output = _output(sources)
        record = output["factual_records"][0]
        claim = record["claims"][0]
        leaf = {
            "operator": "leaf",
            "text": "The program operates.",
            "evidence_ids": [record["record_id"]],
        }
        claim.update(
            conditions={
                "operator": "all",
                "children": [{"operator": "any", "children": [leaf]}],
            },
            exceptions=[{**leaf, "text": "The agency closes."}],
        )
        wire_output = copy.deepcopy(output)
        wire_claim = wire_output["factual_records"][0]["claims"][0]
        if mode == "json_schema":
            for field in ("conditions", "exceptions"):
                wire_claim[field] = json.dumps(wire_claim[field])
        env.update(
            source_review=True,
            instructions=INSTRUCTIONS
            + POLICY_INSTRUCTIONS
            + "\n"
            + FACTUAL_MAP_INSTRUCTIONS,
            output_schema=discovery_schema(sources),
            source_packet={"sources": sources},
        )
    elif stage == "dependency":
        env = base.request_envelope
        sources = base.source_snapshot
        wire_output = output = Provider().enhance_bill(request=base).output
    else:
        summary = _stage_request(settings, "summary")
        env.update(summary.request_envelope)
        sources = summary.source_snapshot
        source = env["source_packet"]["sources"][0]
        quote = {
            "source_ref": source["source_ref"],
            "quote_id": source["citation_passages"][0]["quote_id"],
        }
        wire_output = output = {
            "schema_version": "1.4",
            "explanations": [],
            "summary": [
                {"text": "Public hospitals qualify.", "source_quotes": [quote]}
            ],
        }
    request = replace(base, source_snapshot=sources, request_envelope=env)
    calls = []
    provider = get_provider(provider_name, adapter=adapter)

    if provider_name == "openrouter":
        provider.structured_output_mode = mode

    def respond(http_request):
        call = json.loads(http_request.content)
        calls.append(call)
        content = json.dumps(wire_output)
        if provider_name == "openai":
            body = {
                "id": "resp_123",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": "model",
                "output": [
                    {
                        "type": "message",
                        "id": "msg_123",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": content, "annotations": []}
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 120,
                    "output_tokens": 45,
                    "total_tokens": 165,
                },
            }
        elif provider_name == "anthropic":
            body = {
                "id": "msg_123",
                "role": "assistant",
                "type": "message",
                "model": "model",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": content}],
                "usage": {"input_tokens": 120, "output_tokens": 45},
            }
        elif provider_name == "gemini":
            body = {
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": content}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 120,
                    "candidatesTokenCount": 45,
                    "totalTokenCount": 165,
                },
            }
        else:
            body = {
                "id": "chatcmpl-123",
                "model": "model",
                "object": "chat.completion",
                "created": 1,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ],
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 45,
                    "total_tokens": 165,
                },
            }
        transport = httpx2 if isinstance(http_request, httpx2.Request) else httpx
        return transport.Response(200, json=body, request=http_request)

    async def async_send(client, http_request, **kwargs):
        return respond(http_request)

    for transport in (httpx, httpx2):
        monkeypatch.setattr(
            transport.Client, "send", lambda client, request, **kwargs: respond(request)
        )
        monkeypatch.setattr(transport.AsyncClient, "send", async_send)
    monkeypatch.setattr(
        socket.socket,
        "connect",
        lambda *args: pytest.fail("Offline contract attempted a network connection"),
    )
    result = provider.enhance_bill(
        api_key="offline", request=request, timeout_seconds=5
    )
    (call,) = calls
    if mode != "json_schema":
        assert call.get("response_format") == (
            {"type": "json_object"} if mode == "json_object" else None
        )
        assert call["messages"][0]["content"] == env["instructions"]
    else:
        if provider_name == "openai":
            schema = call["text"]["format"]["schema"]
        elif provider_name == "anthropic":
            schema = call["output_config"]["format"]["schema"]
        elif provider_name == "gemini":
            schema = call["generationConfig"]["responseJsonSchema"]
        else:
            schema = call["response_format"]["json_schema"]["schema"]
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(wire_output)

        def inspect(node):
            if isinstance(node, list):
                for child in node:
                    inspect(child)
            elif isinstance(node, dict):
                assert not (
                    set(node) & provider.capabilities.unsupported_schema_keywords
                )
                if (
                    provider_name in {"openai", "openrouter", "anthropic"}
                    and node.get("type") == "object"
                ):
                    assert node["additionalProperties"] is False
                    assert set(node["required"]) == set(node["properties"])
                for child in node.values():
                    inspect(child)

        inspect(schema)
        from apps.legislation.enhancements.reader_capacity import schema_fits

        assert schema_fits(schema, provider_name)
        assert "#/$defs/condition" not in json.dumps(schema)
    assert result.output == output
    assert result.usage.total_tokens == 165
    if stage == "map":
        assert (
            resolve_discovery(result.output, sources)["factual_records"]
            == output["factual_records"]
        )


def test_anthropic_pages_split_before_union_limit(settings):
    from apps.legislation.enhancements.reader_capacity import schema_fits
    from apps.legislation.enhancements.reader_reconciliation import reconcile_review

    base, review = _fixture(settings, count=40)
    settings.LLM_READER_MODEL_CAPACITIES["anthropic/model"] = {
        "context_tokens": 300000,
        "output_tokens": 100000,
        "visible_fraction": 1,
    }
    settings.LLM_READER_MAX_OUTPUT_TOKENS = 100000
    settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES = (
        settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS
    ) = 200000
    provider = Provider()
    result, _, count = reconcile_review(
        replace(base, provider="anthropic"),
        review,
        provider,
        "offline",
        lambda: None,
        100,
    )
    assert count >= 3
    assert all(
        schema_fits(r.request_envelope["output_schema"], "anthropic")
        for r in provider.requests
    )
    assert (
        sum(
            len(p["descriptor"]["record_ids"])
            for p in result["dependency_review"]["pages"]
        )
        == 40
    )


@pytest.mark.parametrize("mode", ["json_object", "prompt_json"])
@pytest.mark.parametrize("payload_kind", ["native", "stringified", "invalid_tree"])
def test_fallback_map_uses_native_condition_contract(settings, mode, payload_kind):
    from jsonschema import ValidationError

    from apps.legislation.enhancements.reader_discovery import (
        INSTRUCTIONS,
        POLICY_INSTRUCTIONS,
        discovery_schema,
        resolve_discovery,
    )
    from apps.legislation.enhancements.reader_facts import FACTUAL_MAP_INSTRUCTIONS

    from .test_reader_facts import _output, _sources

    base = dependency_request(settings, "openrouter")
    sources = _sources(
        "The agency must report while the program operates unless the agency closes."
    )
    env = dict(base.request_envelope)
    env.pop("dependency_review")
    env.update(
        output_schema_version="1.4",
        source_review=True,
        output_schema=discovery_schema(sources),
        source_packet={"sources": sources},
        instructions=INSTRUCTIONS
        + POLICY_INSTRUCTIONS
        + "\n"
        + FACTUAL_MAP_INSTRUCTIONS,
    )
    request = replace(base, source_snapshot=sources, request_envelope=env)
    output = _output(sources)
    record = output["factual_records"][0]
    leaf = {
        "operator": "leaf",
        "text": "The program operates.",
        "evidence_ids": [record["record_id"]],
    }
    claim = record["claims"][0]
    claim.update(
        conditions={"operator": "all", "children": [leaf]},
        exceptions=[{**leaf, "text": "The agency closes."}],
    )
    wire = copy.deepcopy(output)
    wire_claim = wire["factual_records"][0]["claims"][0]
    if payload_kind == "invalid_tree":
        wire_claim["conditions"] = {"operator": "all", "children": []}
    elif payload_kind == "stringified":
        for field in ("conditions", "exceptions"):
            wire_claim[field] = json.dumps(wire_claim[field])
    calls = []
    provider = _sdk_provider("openrouter", _sdk_response(wire), calls)
    provider.structured_output_mode = mode
    result = provider.enhance_bill(
        api_key="offline", request=request, timeout_seconds=1
    )
    (call,) = calls
    assert call.get("response_format") == (
        {"type": "json_object"} if mode == "json_object" else None
    )
    assert call["messages"][0]["content"] == env["instructions"]
    assert (
        "factual_records" in call["messages"][0]["content"]
        and "JSON" in call["messages"][0]["content"]
    )
    if payload_kind == "invalid_tree":
        with pytest.raises(ValidationError):
            resolve_discovery(result.output, sources)
    else:
        assert (
            resolve_discovery(result.output, sources)["factual_records"]
            == output["factual_records"]
        )


def test_completed_fallback_keeps_usage_if_json_decoder_reaches_depth_limit(
    settings, monkeypatch
):
    request = dependency_request(settings, "openrouter")
    calls = []
    provider = _sdk_provider("openrouter", _sdk_response({}), calls)
    provider.structured_output_mode = "prompt_json"

    def depth_limit(*args):
        raise RecursionError("decoder depth limit")

    monkeypatch.setattr(json.JSONDecoder, "raw_decode", depth_limit)
    with pytest.raises(ProviderError) as failure:
        provider.enhance_bill(api_key="offline", request=request, timeout_seconds=1)
    assert len(calls) == 1
    assert failure.value.validation_code == "provider_invalid_json"
    assert failure.value.response_id == "dependency-response"
    assert failure.value.usage.total_tokens == 165
    assert not failure.value.outcome_unknown
