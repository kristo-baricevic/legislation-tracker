import json
from types import SimpleNamespace

import pytest

from apps.legislation.enhancements.providers.base import ProviderError
from apps.legislation.enhancements.providers.openai import OpenAIEnhancementProvider
from apps.legislation.enhancements.schema import OUTPUT_SCHEMA

from .test_enhancement_schema import _valid_output


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
            },
        },
    )


def _completed_response():
    return SimpleNamespace(
        id="resp_test_123",
        status="completed",
        model="gpt-5.6-luna-2026-08-01",
        output_text=json.dumps(_valid_output()),
        output=[],
        usage=SimpleNamespace(input_tokens=120, output_tokens=45, total_tokens=165),
    )


def test_enhancement_uses_one_bounded_non_persistent_structured_request():
    responses = FakeResponses(result=_completed_response())
    factory = FakeClientFactory(responses)
    provider = OpenAIEnhancementProvider(client_factory=factory)

    result = provider.enhance_bill(
        api_key="sk-test-secret",
        request=_request(),
        timeout_seconds=90,
    )

    assert factory.calls == [
        {"api_key": "sk-test-secret", "max_retries": 0, "timeout": 90}
    ]
    assert len(responses.calls) == 1
    call = responses.calls[0]
    assert call["model"] == "gpt-5.6-luna"
    assert call["store"] is False
    assert call["truncation"] == "disabled"
    assert call["tools"] == []
    assert call["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}
    assert call["reasoning"] == {"effort": "none"}
    assert call["text"]["format"] == {
        "type": "json_schema",
        "name": "bill_enhancement_v1_1",
        "schema": OUTPUT_SCHEMA,
        "strict": True,
    }
    assert "previous_response_id" not in call
    assert "conversation" not in call
    assert result.output == _valid_output()
    assert result.response_id == "resp_test_123"
    assert result.resolved_model == "gpt-5.6-luna-2026-08-01"
    assert result.usage.total_tokens == 165


def test_explicit_validation_makes_exactly_one_minimal_request():
    response = SimpleNamespace(status="completed", output_text="OK", output=[])
    responses = FakeResponses(result=response)
    factory = FakeClientFactory(responses)
    provider = OpenAIEnhancementProvider(client_factory=factory)

    check = provider.validate_credential(
        api_key="sk-test-secret",
        requested_model="gpt-5.6-luna",
        timeout_seconds=30,
    )

    assert check.valid is True
    assert len(responses.calls) == 1
    assert responses.calls[0]["max_output_tokens"] == 8
    assert responses.calls[0]["store"] is False
    assert factory.calls[0]["max_retries"] == 0


@pytest.mark.parametrize(
    ("status_code", "category", "retry_allowed"),
    [
        (401, "invalid_credentials", False),
        (403, "model_access_denied", False),
        (429, "provider_rate_limited", True),
        (500, "provider_unavailable", True),
    ],
)
def test_provider_status_errors_are_sanitized(status_code, category, retry_allowed):
    error = type("FakeStatusError", (Exception,), {"status_code": status_code})(
        "raw provider secret body"
    )
    provider = OpenAIEnhancementProvider(
        client_factory=FakeClientFactory(FakeResponses(error=error))
    )

    with pytest.raises(ProviderError) as captured:
        provider.enhance_bill(
            api_key="sk-test-secret",
            request=_request(),
            timeout_seconds=90,
        )

    assert captured.value.category == category
    assert captured.value.retry_allowed is retry_allowed
    assert captured.value.outcome_unknown is False
    assert "raw provider" not in str(captured.value)


@pytest.mark.parametrize(
    ("status_code", "error_code", "category"),
    [
        (429, "insufficient_quota", "quota_exhausted"),
        (400, "context_length_exceeded", "request_too_large"),
        (404, "model_not_found", "model_access_denied"),
    ],
)
def test_provider_known_error_codes_have_specific_terminal_categories(
    status_code,
    error_code,
    category,
):
    error_type = type("FakeStatusError", (Exception,), {"status_code": status_code})
    error = error_type("raw provider secret body")
    error.body = {"error": {"code": error_code}}
    provider = OpenAIEnhancementProvider(
        client_factory=FakeClientFactory(FakeResponses(error=error))
    )

    with pytest.raises(ProviderError) as captured:
        provider.enhance_bill(
            api_key="sk-test-secret",
            request=_request(),
            timeout_seconds=90,
        )

    assert captured.value.category == category
    assert captured.value.retry_allowed is False
    assert "raw provider" not in str(captured.value)


@pytest.mark.parametrize("error_name", ["APITimeoutError", "APIConnectionError"])
def test_timeout_or_connection_loss_is_an_unknown_outcome(error_name):
    error = type(error_name, (Exception,), {})("raw provider secret body")
    provider = OpenAIEnhancementProvider(
        client_factory=FakeClientFactory(FakeResponses(error=error))
    )

    with pytest.raises(ProviderError) as captured:
        provider.enhance_bill(
            api_key="sk-test-secret",
            request=_request(),
            timeout_seconds=90,
        )

    assert captured.value.category == "outcome_unknown"
    assert captured.value.outcome_unknown is True
    assert captured.value.retry_allowed is True


def test_refusal_and_incomplete_response_fail_without_parsing_output():
    refusal = SimpleNamespace(
        type="message",
        content=[SimpleNamespace(type="refusal", refusal="Cannot comply")],
    )
    refusal_response = SimpleNamespace(
        id="resp_refused",
        status="completed",
        output=[refusal],
        output_text="",
        usage=None,
        model="gpt-5.6-luna",
    )
    provider = OpenAIEnhancementProvider(
        client_factory=FakeClientFactory(FakeResponses(result=refusal_response))
    )
    with pytest.raises(ProviderError) as captured:
        provider.enhance_bill(
            api_key="sk-test-secret",
            request=_request(),
            timeout_seconds=90,
        )
    assert captured.value.category == "content_refusal"

    incomplete = SimpleNamespace(
        id="resp_incomplete",
        status="incomplete",
        output=[],
        output_text='{"partial":',
        usage=None,
        model="gpt-5.6-luna",
    )
    provider = OpenAIEnhancementProvider(
        client_factory=FakeClientFactory(FakeResponses(result=incomplete))
    )
    with pytest.raises(ProviderError) as captured:
        provider.enhance_bill(
            api_key="sk-test-secret",
            request=_request(),
            timeout_seconds=90,
        )
    assert captured.value.category == "invalid_output"


def test_malformed_completed_output_is_invalid_output():
    response = _completed_response()
    response.output_text = "not-json"
    provider = OpenAIEnhancementProvider(
        client_factory=FakeClientFactory(FakeResponses(result=response))
    )

    with pytest.raises(ProviderError) as captured:
        provider.enhance_bill(
            api_key="sk-test-secret",
            request=_request(),
            timeout_seconds=90,
        )

    assert captured.value.category == "invalid_output"
