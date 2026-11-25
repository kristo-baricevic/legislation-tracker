from types import SimpleNamespace

import httpx
import pytest
from langchain_openai import ChatOpenAI

from apps.legislation.enhancements.providers.base import ProviderError
from apps.legislation.enhancements.providers.langchain_adapter import (
    LangChainOpenRouterProvider,
)


@pytest.mark.parametrize(
    "finish,content,expected",
    [
        ("stop", '{"ok":true}', None),
        ("length", "", "provider_output_limit"),
        ("stop", "{", "provider_invalid_json"),
        ("content_filter", "", "content_refusal"),
    ],
)
def test_real_langchain_serialization_one_transport_request(finish, content, expected):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "id": "provider-id",
                "object": "chat.completion",
                "created": 1,
                "model": "actual:free",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": finish,
                        "message": {"role": "assistant", "content": content},
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 10,
                    "total_tokens": 22,
                    "completion_tokens_details": {"reasoning_tokens": 8},
                },
            },
        )

    def factory(**kwargs):
        assert kwargs["max_retries"] == 0
        return ChatOpenAI(**kwargs)

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    adapter = LangChainOpenRouterProvider(
        model_factory=factory, http_client_factory=lambda: client
    )
    request = SimpleNamespace(
        provider="openrouter",
        requested_model="actual:free",
        request_envelope={"max_output_tokens": 80},
        reasoning_effort="low",
    )

    def generate():
        return adapter._generate(
            api_key="test",
            request=request,
            timeout_seconds=2,
            input_payload={},
            instructions="Return JSON",
            schema={"type": "object"},
            schema_name="test",
        )

    if expected:
        with pytest.raises(ProviderError) as error:
            generate()
        assert expected in (error.value.validation_code, error.value.category)
        assert error.value.usage.reasoning_tokens == 8
    else:
        result = generate()
        assert result.output == {"ok": True}
        assert (
            result.resolved_model == "actual:free"
            and result.response_id == "provider-id"
        )
        assert result.usage.visible_output_tokens == 2
    assert len(calls) == 1
    assert client.is_closed


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, "invalid_credentials"),
        (429, "provider_rate_limited"),
        (503, "provider_unavailable"),
        (None, "outcome_unknown"),
    ],
)
def test_transport_errors_do_not_retry(status, expected):
    calls = []

    def respond(request):
        calls.append(request)
        if status is None:
            raise httpx.ReadTimeout("test timeout", request=request)
        return httpx.Response(status, json={"error": {"message": "rejected"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    adapter = LangChainOpenRouterProvider(http_client_factory=lambda: client)
    request = SimpleNamespace(
        provider="openrouter",
        requested_model="model:free",
        request_envelope={"max_output_tokens": 80},
        reasoning_effort="low",
    )
    with pytest.raises(ProviderError) as error:
        adapter._generate(
            api_key="test",
            request=request,
            timeout_seconds=2,
            input_payload={},
            instructions="Return JSON",
            schema={"type": "object"},
            schema_name="test",
        )
    assert client.is_closed
    assert len(calls) == 1 and error.value.category == expected
    assert error.value.outcome_unknown == (status is None)
