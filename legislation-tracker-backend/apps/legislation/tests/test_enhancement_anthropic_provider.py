import json
from types import SimpleNamespace

import pytest

from apps.legislation.enhancements.providers.anthropic import (
    AnthropicEnhancementProvider,
)
from apps.legislation.enhancements.providers.base import ProviderError
from apps.legislation.enhancements.schema import OUTPUT_SCHEMA

from .test_enhancement_schema import _valid_output


class FakeMessages:
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
    def __init__(self, messages):
        self.messages = messages
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(messages=self.messages)


def _request():
    return SimpleNamespace(
        requested_model="claude-test-model",
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


def _completed_response():
    return SimpleNamespace(
        id="msg_test_123",
        type="message",
        role="assistant",
        model="claude-test-model-2026-08-01",
        content=[SimpleNamespace(type="text", text=json.dumps(_valid_output()))],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=120, output_tokens=45),
    )


def test_one_bounded_structured_request():
    messages = FakeMessages(result=_completed_response())
    factory = FakeClientFactory(messages)
    provider = AnthropicEnhancementProvider(client_factory=factory)

    result = provider.enhance_bill(
        api_key="sk-test-secret",
        request=_request(),
        timeout_seconds=90,
    )

    assert factory.calls == [
        {"api_key": "sk-test-secret", "max_retries": 0, "timeout": 90}
    ]
    assert len(messages.calls) == 1
    call = messages.calls[0]
    assert call["model"] == "claude-test-model"
    assert call["max_tokens"] == 8000  # LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS default-ish
    assert "system" in call
    assert call["messages"] == [
        {
            "role": "user",
            "content": json.dumps(
                {
                    "bill": {"id": 4, "title": "Test Act"},
                    "source_packet": _request().request_envelope["source_packet"],
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
        }
    ]
    assert "tools" not in call
    assert "output_config" in call
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "previous_response_id" not in call
    assert "conversation" not in call
    assert result.output == _valid_output()
    assert result.response_id == "msg_test_123"
    assert result.resolved_model == "claude-test-model-2026-08-01"
    assert result.usage.input_tokens == 120
    assert result.usage.output_tokens == 45
    assert result.usage.total_tokens == 165
    conditions = call["output_config"]["format"]["schema"]["properties"]["obligations"][
        "items"
    ]["properties"]["conditions"]
    assert {branch["type"] for branch in conditions["anyOf"]} == {"string", "null"}
    assert all("maxLength" not in branch for branch in conditions["anyOf"])


def test_multiple_text_blocks_concatenated():
    full = json.dumps(_valid_output())
    response = _completed_response()
    response.content = [
        SimpleNamespace(type="text", text=full[: len(full) // 2]),
        SimpleNamespace(type="text", text=full[len(full) // 2 :]),
    ]
    messages = FakeMessages(result=response)
    provider = AnthropicEnhancementProvider(client_factory=FakeClientFactory(messages))
    result = provider.enhance_bill(
        api_key="test", request=_request(), timeout_seconds=30
    )
    assert result.output == _valid_output()


def test_output_limit_stop_reason():
    response = _completed_response()
    response.stop_reason = "max_tokens"
    response.content = [SimpleNamespace(type="text", text="partial")]
    messages = FakeMessages(result=response)
    provider = AnthropicEnhancementProvider(client_factory=FakeClientFactory(messages))
    with pytest.raises(ProviderError) as caught:
        provider.enhance_bill(api_key="test", request=_request(), timeout_seconds=30)
    assert caught.value.validation_code == "provider_output_limit"


def test_malformed_json():
    response = _completed_response()
    response.content = [SimpleNamespace(type="text", text="not-json")]
    messages = FakeMessages(result=response)
    provider = AnthropicEnhancementProvider(client_factory=FakeClientFactory(messages))
    with pytest.raises(ProviderError) as caught:
        provider.enhance_bill(api_key="test", request=_request(), timeout_seconds=30)
    assert caught.value.validation_code == "provider_invalid_json"


def test_non_object_json():
    response = _completed_response()
    response.content = [SimpleNamespace(type="text", text="[]")]
    messages = FakeMessages(result=response)
    provider = AnthropicEnhancementProvider(client_factory=FakeClientFactory(messages))
    with pytest.raises(ProviderError) as caught:
        provider.enhance_bill(api_key="test", request=_request(), timeout_seconds=30)
    assert caught.value.validation_code == "provider_output_not_object"


def test_fenced_json():
    response = _completed_response()
    response.content = [SimpleNamespace(type="text", text="```json\n{}\n```")]
    messages = FakeMessages(result=response)
    provider = AnthropicEnhancementProvider(client_factory=FakeClientFactory(messages))
    with pytest.raises(ProviderError) as caught:
        provider.enhance_bill(api_key="test", request=_request(), timeout_seconds=30)
    assert caught.value.validation_code == "provider_invalid_json"


def test_status_429_one_attempt():
    err = type("FakeStatusError", (Exception,), {"status_code": 429})("raw")
    messages = FakeMessages(error=err)
    factory = FakeClientFactory(messages)
    provider = AnthropicEnhancementProvider(client_factory=factory)
    with pytest.raises(ProviderError) as caught:
        provider.enhance_bill(api_key="test", request=_request(), timeout_seconds=30)
    assert caught.value.category == "provider_rate_limited"
    assert caught.value.retry_allowed is True
    assert len(messages.calls) == 1


def test_timeout_one_attempt_outcome_unknown():
    err = type("APITimeoutError", (Exception,), {})("raw")
    messages = FakeMessages(error=err)
    factory = FakeClientFactory(messages)
    provider = AnthropicEnhancementProvider(client_factory=factory)
    with pytest.raises(ProviderError) as caught:
        provider.enhance_bill(api_key="test", request=_request(), timeout_seconds=30)
    assert caught.value.category == "outcome_unknown"
    assert caught.value.outcome_unknown is True
    assert len(messages.calls) == 1


def test_usage_and_resolved_model():
    messages = FakeMessages(result=_completed_response())
    provider = AnthropicEnhancementProvider(client_factory=FakeClientFactory(messages))
    result = provider.enhance_bill(
        api_key="test", request=_request(), timeout_seconds=30
    )
    assert result.usage.input_tokens == 120
    assert result.usage.output_tokens == 45
    assert result.resolved_model == "claude-test-model-2026-08-01"


def test_validate_credential():
    response = SimpleNamespace(stop_reason="end_turn")
    messages = FakeMessages(result=response)
    factory = FakeClientFactory(messages)
    provider = AnthropicEnhancementProvider(client_factory=factory)
    check = provider.validate_credential(
        api_key="test", requested_model="m", timeout_seconds=30
    )
    assert check.valid is True
    assert factory.calls[0]["max_retries"] == 0
    assert messages.calls[0]["max_tokens"] == 16
