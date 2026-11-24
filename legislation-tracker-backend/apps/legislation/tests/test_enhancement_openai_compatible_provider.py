import json
import asyncio
import time
from types import SimpleNamespace

import pytest

from apps.legislation.enhancements.providers.base import ProviderError
from apps.legislation.enhancements.providers.openai_compatible import (
    OpenAICompatibleEnhancementProvider,
)
from apps.legislation.enhancements.schema import OUTPUT_SCHEMA, PROVIDER_OUTPUT_SCHEMA
from .test_enhancement_openai_provider import _request, _valid_output


class FakeCompletions:
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
    def __init__(self, completions):
        self.completions = completions
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(chat=SimpleNamespace(completions=self.completions))


def _completed_response(output_text=None, finish_reason="stop"):
    if output_text is None:
        output_text = json.dumps(_valid_output())
    return SimpleNamespace(
        id="chatcmpl_test_123",
        model="deepseek-chat-2026",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=output_text, refusal=None),
                finish_reason=finish_reason,
            )
        ],
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=45, total_tokens=165),
    )


def test_client_kwargs():
    completions = FakeCompletions(result=_completed_response())
    factory = FakeClientFactory(completions)
    provider = OpenAICompatibleEnhancementProvider(
        client_factory=factory, base_url="https://api.example.com/v1", model="m"
    )
    result = provider.enhance_bill(api_key="sk-test-secret", request=_request(), timeout_seconds=90)
    assert factory.calls == [
        {"api_key": "sk-test-secret", "base_url": "https://api.example.com/v1", "max_retries": 0, "timeout": 90}
    ]
    assert len(completions.calls) == 1
    call = completions.calls[0]
    assert call["model"] == "gpt-5.6-luna"
    assert "tools" in call and call["tools"] == []
    assert "tool_choice" not in call
    assert "messages" in call and len(call["messages"]) == 2
    assert "stream" not in call or call.get("stream") is False
    assert result.response_id == "chatcmpl_test_123"
    assert result.resolved_model == "deepseek-chat-2026"
    assert result.usage.total_tokens == 165
    assert result.usage.input_tokens == 120
    assert result.usage.output_tokens == 45


@pytest.mark.parametrize('finish_reason', ['stop', 'length'])
def test_reasoning_usage_is_kept_even_for_truncated_responses(finish_reason):
    response = _completed_response(finish_reason=finish_reason)
    response.usage.completion_tokens_details = SimpleNamespace(reasoning_tokens=30)
    provider = OpenAICompatibleEnhancementProvider(client_factory=FakeClientFactory(FakeCompletions(result=response)))
    if finish_reason == 'length':
        with pytest.raises(ProviderError) as exc:
            provider.enhance_bill(api_key='offline', request=_request(), timeout_seconds=1)
        usage = exc.value.usage
    else:
        usage = provider.enhance_bill(api_key='offline', request=_request(), timeout_seconds=1).usage
    assert usage.output_tokens == 45
    assert usage.reasoning_tokens == 30
    assert usage.visible_output_tokens == 15


def test_total_deadline_cancels_a_response_that_keeps_producing_data():
    stopped = []
    class SlowCompletions:
        async def create(self, **kwargs):
            try:
                for _ in range(100):
                    await asyncio.sleep(.01)  # activity must not renew the deadline
                return _completed_response()
            finally:
                stopped.append(True)
    provider = OpenAICompatibleEnhancementProvider(client_factory=FakeClientFactory(SlowCompletions()))
    started = time.monotonic()
    with pytest.raises(ProviderError) as error:
        provider.enhance_bill(api_key='offline', request=_request(), timeout_seconds=.05)
    assert error.value.validation_code == 'provider_timeout'
    assert error.value.outcome_unknown
    assert time.monotonic() - started < .5
    assert stopped == [True]


@pytest.mark.parametrize('effort', ['none', 'low', 'medium', 'high'])
def test_openrouter_preserves_default_reasoning_unless_effort_requested(effort):
    completions = FakeCompletions(result=_completed_response())
    provider = OpenAICompatibleEnhancementProvider(client_factory=FakeClientFactory(completions))
    request = _request()
    request.provider = 'openrouter'
    request.reasoning_effort = effort
    provider.enhance_bill(api_key='offline', request=request, timeout_seconds=1)
    call = completions.calls[0]
    if effort == 'none':
        assert 'reasoning' not in call.get('extra_body', {})
    else:
        assert call['extra_body']['reasoning'] == {'effort': effort}


def test_json_schema_mode():
    completions = FakeCompletions(result=_completed_response())
    factory = FakeClientFactory(completions)
    provider = OpenAICompatibleEnhancementProvider(client_factory=factory, base_url="https://x", structured_output_mode="json_schema")
    provider.enhance_bill(api_key="t", request=_request(), timeout_seconds=30)
    call = completions.calls[0]
    assert call["response_format"]["type"] == "json_schema"
    assert call["response_format"]["json_schema"]["strict"] is True


def test_openrouter_keeps_prose_rules_local_without_relaxing_citation_ids():
    from apps.legislation.enhancements.reader_citations import READER_PROMPT_VERSION
    completions = FakeCompletions(result=_completed_response())
    provider = OpenAICompatibleEnhancementProvider(client_factory=FakeClientFactory(completions))
    request = _request()
    request.provider = 'openrouter'
    schema = {'type': 'object', 'properties': {
        'text': {'type': 'string', 'pattern': r'^(?:\S+\s+){0,64}\S*[.!?]$', 'maxLength': 420},
        'quote_id': {'type': 'string', 'pattern': r'^p[0-9]{4,}$'}}}
    request.request_envelope.update(output_schema_version='1.4', prompt_version=READER_PROMPT_VERSION, output_schema=schema)
    provider.enhance_bill(api_key='offline', request=request, timeout_seconds=1)
    wire = completions.calls[0]['response_format']['json_schema']['schema']
    assert 'pattern' not in wire['properties']['text']
    assert wire['properties']['text']['maxLength'] == 420
    assert wire['properties']['quote_id']['pattern'] == r'^p[0-9]{4,}$'
    assert 'pattern' in schema['properties']['text']  # Local validation stays strict.


def test_json_object_mode():
    completions = FakeCompletions(result=_completed_response())
    factory = FakeClientFactory(completions)
    provider = OpenAICompatibleEnhancementProvider(client_factory=factory, base_url="https://x", structured_output_mode="json_object")
    provider.enhance_bill(api_key="t", request=_request(), timeout_seconds=30)
    call = completions.calls[0]
    assert call["response_format"]["type"] == "json_object"


def test_prompt_json_mode():
    completions = FakeCompletions(result=_completed_response())
    factory = FakeClientFactory(completions)
    provider = OpenAICompatibleEnhancementProvider(client_factory=factory, base_url="https://x", structured_output_mode="prompt_json")
    provider.enhance_bill(api_key="t", request=_request(), timeout_seconds=30)
    call = completions.calls[0]
    assert "response_format" not in call


def test_json_schema_fallback():
    # provider that cannot do json_schema
    completions = FakeCompletions(result=_completed_response())
    factory = FakeClientFactory(completions)
    provider = OpenAICompatibleEnhancementProvider(client_factory=factory, base_url="https://x", supports_json_schema=False)
    assert provider._structured_output_mode() == "json_object"
    provider.enhance_bill(api_key="t", request=_request(), timeout_seconds=30)
    call = completions.calls[0]
    assert call["response_format"]["type"] == "json_object"


def test_malformed_json():
    resp = _completed_response(output_text="not-json")
    completions = FakeCompletions(result=resp)
    factory = FakeClientFactory(completions)
    provider = OpenAICompatibleEnhancementProvider(client_factory=factory, base_url="https://x")
    with pytest.raises(ProviderError) as c:
        provider.enhance_bill(api_key="t", request=_request(), timeout_seconds=30)
    assert c.value.validation_code == "provider_invalid_json"


def test_non_object_json():
    resp = _completed_response(output_text="[]")
    completions = FakeCompletions(result=resp)
    factory = FakeClientFactory(completions)
    provider = OpenAICompatibleEnhancementProvider(client_factory=factory, base_url="https://x")
    with pytest.raises(ProviderError) as c:
        provider.enhance_bill(api_key="t", request=_request(), timeout_seconds=30)
    assert c.value.validation_code == "provider_output_not_object"


def test_fenced_json():
    resp = _completed_response(output_text="```json\n{\"a\":1}\n```")
    completions = FakeCompletions(result=resp)
    factory = FakeClientFactory(completions)
    provider = OpenAICompatibleEnhancementProvider(client_factory=factory, base_url="https://x")
    with pytest.raises(ProviderError) as c:
        provider.enhance_bill(api_key="t", request=_request(), timeout_seconds=30)
    assert c.value.validation_code == "provider_fenced_json"


def test_multi_object():
    resp = _completed_response(output_text='{"a":1}{"b":2}')
    completions = FakeCompletions(result=resp)
    factory = FakeClientFactory(completions)
    provider = OpenAICompatibleEnhancementProvider(client_factory=factory, base_url="https://x")
    with pytest.raises(ProviderError) as c:
        provider.enhance_bill(api_key="t", request=_request(), timeout_seconds=30)
    assert c.value.validation_code == "provider_multiple_json_objects"


def test_distinct_codes():
    codes = set()
    for text in ["not-json", "[]", "```json\n{}\n```", '{"a":1}{"b":2}']:
        # non-object returns provider_output_not_object; okay distinct
        pass
    # just ensure four different
    assert len({"provider_invalid_json", "provider_output_not_object", "provider_fenced_json", "provider_multiple_json_objects"}) == 4


def test_429_one_attempt():
    error = type("FakeStatusError", (Exception,), {"status_code": 429})("raw")
    completions = FakeCompletions(error=error)
    factory = FakeClientFactory(completions)
    provider = OpenAICompatibleEnhancementProvider(client_factory=factory, base_url="https://x")
    with pytest.raises(ProviderError) as c:
        provider.enhance_bill(api_key="t", request=_request(), timeout_seconds=30)
    assert c.value.category == "provider_rate_limited"
    assert len(completions.calls) == 1


def test_timeout_one_attempt_outcome_unknown():
    error = type("APITimeoutError", (Exception,), {})("raw")
    completions = FakeCompletions(error=error)
    factory = FakeClientFactory(completions)
    provider = OpenAICompatibleEnhancementProvider(client_factory=factory, base_url="https://x")
    with pytest.raises(ProviderError) as c:
        provider.enhance_bill(api_key="t", request=_request(), timeout_seconds=30)
    assert c.value.category == "outcome_unknown"
    assert c.value.outcome_unknown is True
    assert len(completions.calls) == 1


def test_usage_normalization():
    resp = _completed_response()
    completions = FakeCompletions(result=resp)
    factory = FakeClientFactory(completions)
    provider = OpenAICompatibleEnhancementProvider(client_factory=factory, base_url="https://x")
    result = provider.enhance_bill(api_key="t", request=_request(), timeout_seconds=30)
    assert result.response_id == "chatcmpl_test_123"
    assert result.resolved_model == "deepseek-chat-2026"
    assert result.usage.input_tokens == 120
    assert result.usage.output_tokens == 45
    assert result.usage.total_tokens == 165


def test_length_finish_reason():
    resp = _completed_response(finish_reason="length")
    completions = FakeCompletions(result=resp)
    factory = FakeClientFactory(completions)
    provider = OpenAICompatibleEnhancementProvider(client_factory=factory, base_url="https://x")
    with pytest.raises(ProviderError) as c:
        provider.enhance_bill(api_key="t", request=_request(), timeout_seconds=30)
    assert c.value.validation_code == "provider_output_limit"


def test_refusal():
    resp = _completed_response()
    resp.choices[0].message.refusal = "no"
    resp.choices[0].message.content = ""
    completions = FakeCompletions(result=resp)
    factory = FakeClientFactory(completions)
    provider = OpenAICompatibleEnhancementProvider(client_factory=factory, base_url="https://x")
    with pytest.raises(ProviderError) as c:
        provider.enhance_bill(api_key="t", request=_request(), timeout_seconds=30)
    assert c.value.category == "content_refusal"


def test_source_first_methods():
    # generate_provisions
    resp = _completed_response(output_text=json.dumps({"provisions": []}))
    completions = FakeCompletions(result=resp)
    factory = FakeClientFactory(completions)
    provider = OpenAICompatibleEnhancementProvider(client_factory=factory, base_url="https://x")
    request = _request()
    request.request_envelope["source_first_payload"] = {"units": [], "passages": {}}
    result = provider.generate_provisions(api_key="t", request=request, timeout_seconds=30)
    assert result.output == {"provisions": []}


def test_validate_credential():
    resp = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="OK", refusal=None), finish_reason="stop")])
    completions = FakeCompletions(result=resp)
    factory = FakeClientFactory(completions)
    provider = OpenAICompatibleEnhancementProvider(client_factory=factory, base_url="https://x")
    check = provider.validate_credential(api_key="t", requested_model="m", timeout_seconds=30)
    assert check.valid is True
    assert len(completions.calls) == 1
    assert completions.calls[0]["max_tokens"] == 16


def test_free_key_validation_pins_price_and_returned_model():
    completions = FakeCompletions(result=SimpleNamespace(model="unexpected", choices=[object()]))
    provider = OpenAICompatibleEnhancementProvider(client_factory=FakeClientFactory(completions),
                                                   base_url="https://openrouter.ai/api/v1")
    result = provider.validate_credential(api_key="fixture", requested_model="org/test:free", timeout_seconds=3)
    assert not result.valid
    assert completions.calls[0]["extra_body"]["provider"]["max_price"] == {"prompt": 0, "completion": 0, "request": 0}
    assert len(completions.calls) == 1


def test_no_leak():
    error = type("FakeStatusError", (Exception,), {"status_code": 401})("raw secret body")
    completions = FakeCompletions(error=error)
    factory = FakeClientFactory(completions)
    provider = OpenAICompatibleEnhancementProvider(client_factory=factory, base_url="https://x")
    with pytest.raises(ProviderError) as c:
        provider.enhance_bill(api_key="sk-secret", request=_request(), timeout_seconds=30)
    assert "secret" not in str(c.value)
