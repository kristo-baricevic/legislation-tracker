import json
from types import SimpleNamespace

import pytest

from apps.legislation.enhancements.providers.base import ProviderError
from apps.legislation.enhancements.providers.gemini import GeminiEnhancementProvider
from apps.legislation.enhancements.schema import OUTPUT_SCHEMA

from .test_enhancement_schema import _valid_output


class FakeModels:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


class FakeClientFactory:
    def __init__(self, models):
        self.models = models
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(models=self.models)


def _request():
    return SimpleNamespace(
        requested_model="gemini-2.5-flash",
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
        response_id="resp_test_123",
        model_version="gemini-2.5-flash-2026-08-01",
        usage_metadata=SimpleNamespace(
            prompt_token_count=120,
            candidates_token_count=45,
            total_token_count=172,
            thoughts_token_count=7,
        ),
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[SimpleNamespace(text=json.dumps(_valid_output()), thought=False)]
                ),
                finish_reason="STOP",
            )
        ],
        prompt_feedback=None,
    )


def test_enhancement_uses_one_bounded_non_persistent_structured_request():
    models = FakeModels(result=_completed_response())
    factory = FakeClientFactory(models)
    provider = GeminiEnhancementProvider(client_factory=factory)

    result = provider.enhance_bill(
        api_key="secret-key",
        request=_request(),
        timeout_seconds=90,
    )

    assert len(factory.calls) == 1
    assert factory.calls[0]["api_key"] == "secret-key"
    assert "http_options" in factory.calls[0]
    http_options = factory.calls[0]["http_options"]
    assert http_options.timeout == 90000
    assert http_options.retry_options.attempts == 1

    assert len(models.calls) == 1
    call = models.calls[0]
    assert call["model"] == "gemini-2.5-flash"
    config = call["config"]
    assert config.response_mime_type == "application/json"
    assert config.max_output_tokens == 8000  # settings default? may vary
    assert config.http_options.timeout == 90000
    assert config.http_options.retry_options.attempts == 1
    assert config.tools is None
    assert isinstance(call["contents"], str)
    assert "previous_response_id" not in call
    assert "history" not in call
    assert result.output == _valid_output()
    assert result.response_id == "resp_test_123"
    assert result.resolved_model == "gemini-2.5-flash-2026-08-01"
    assert result.usage.input_tokens == 120
    assert result.usage.output_tokens == 52
    assert result.usage.total_tokens == 172


def test_multi_part_candidate_normalizes_text():
    response = _completed_response()
    response.candidates[0].content.parts = [
        SimpleNamespace(text='{"schema_version": "1.3", ', thought=False),
        SimpleNamespace(text='"overview": [], "key_impacts": [], "obligations": [], "funding_and_timing": [], "uncertain_language": []}', thought=False),
    ]
    response.candidates[0].content.parts[0].text = '{"schema_version": "1.3", '
    # Build valid output split across parts
    import json as _json
    full = _json.dumps(_valid_output())
    half = len(full) // 2
    response.candidates[0].content.parts = [
        SimpleNamespace(text=full[:half], thought=False),
        SimpleNamespace(text=full[half:], thought=False),
    ]
    models = FakeModels(result=response)
    factory = FakeClientFactory(models)
    provider = GeminiEnhancementProvider(client_factory=factory)
    result = provider.enhance_bill(api_key="test", request=_request(), timeout_seconds=30)
    assert result.output == _valid_output()


def test_max_tokens_maps_to_output_limit():
    response = _completed_response()
    response.candidates[0].finish_reason = "MAX_TOKENS"
    response.usage_metadata.thoughts_token_count = 8000
    response.usage_metadata.candidates_token_count = 0
    response.candidates[0].content.parts = [SimpleNamespace(text="{}", thought=False)]
    provider = GeminiEnhancementProvider(client_factory=FakeClientFactory(FakeModels(result=response)))
    with pytest.raises(ProviderError) as caught:
        provider.enhance_bill(api_key="test", request=_request(), timeout_seconds=30)
    assert caught.value.category == "invalid_output"
    assert caught.value.validation_code == "provider_output_limit"
    assert caught.value.usage.output_tokens == caught.value.usage.reasoning_tokens == 8000
    assert caught.value.usage.visible_output_tokens == 0


@pytest.mark.parametrize("candidate", [{}, {"candidatesTokenCount": None}, {"candidatesTokenCount": 0}])
def test_thinking_only_sdk_response_preserves_starvation_signal(candidate):
    from google.genai.types import GenerateContentResponse
    from apps.legislation.enhancements.reader_sizing import reasoning_starved

    response = GenerateContentResponse.model_validate({
        "candidates": [{"finishReason": "MAX_TOKENS"}],
        "usageMetadata": {"promptTokenCount": 12, "thoughtsTokenCount": 8000,
                          "totalTokenCount": 8012, **candidate},
    })
    provider = GeminiEnhancementProvider(client_factory=FakeClientFactory(FakeModels(result=response)))
    with pytest.raises(ProviderError) as caught:
        provider.enhance_bill(api_key="offline", request=_request(), timeout_seconds=1)
    assert caught.value.validation_code == "provider_output_limit"
    assert caught.value.usage.output_tokens == 8000
    assert reasoning_starved(caught.value.usage)


@pytest.mark.parametrize("counts,expected", [
    ({"prompt_token_count": 12, "tool_use_prompt_token_count": 30, "total_token_count": 8044}, 8002),
    ({"prompt_token_count": 12}, None),
    ({"total_token_count": 8012}, None),
    ({"prompt_token_count": 12, "total_token_count": 8011}, None),
])
def test_missing_candidate_count_requires_consistent_totals(counts, expected):
    from apps.legislation.enhancements.providers.gemini import _usage
    usage = _usage({"usage_metadata": {"thoughts_token_count": 8000, **counts}})
    assert usage.output_tokens == expected
    assert usage.visible_output_tokens is None


def test_safety_maps_to_refusal():
    response = _completed_response()
    response.candidates[0].finish_reason = "SAFETY"
    response.candidates[0].content.parts = [SimpleNamespace(text="", thought=False)]
    provider = GeminiEnhancementProvider(client_factory=FakeClientFactory(FakeModels(result=response)))
    with pytest.raises(ProviderError) as caught:
        provider.enhance_bill(api_key="test", request=_request(), timeout_seconds=30)
    assert caught.value.category == "content_refusal"


def test_malformed_json_fails_closed():
    response = _completed_response()
    response.candidates[0].content.parts = [SimpleNamespace(text="not-json", thought=False)]
    provider = GeminiEnhancementProvider(client_factory=FakeClientFactory(FakeModels(result=response)))
    with pytest.raises(ProviderError) as caught:
        provider.enhance_bill(api_key="test", request=_request(), timeout_seconds=30)
    assert caught.value.validation_code == "provider_invalid_json"


def test_non_object_json_fails_closed():
    response = _completed_response()
    response.candidates[0].content.parts = [SimpleNamespace(text="[]", thought=False)]
    provider = GeminiEnhancementProvider(client_factory=FakeClientFactory(FakeModels(result=response)))
    with pytest.raises(ProviderError) as caught:
        provider.enhance_bill(api_key="test", request=_request(), timeout_seconds=30)
    assert caught.value.validation_code == "provider_output_not_object"


def test_fenced_json_fails_closed():
    response = _completed_response()
    response.candidates[0].content.parts = [SimpleNamespace(text="```json\n{}\n```", thought=False)]
    provider = GeminiEnhancementProvider(client_factory=FakeClientFactory(FakeModels(result=response)))
    with pytest.raises(ProviderError) as caught:
        provider.enhance_bill(api_key="test", request=_request(), timeout_seconds=30)
    assert caught.value.validation_code == "provider_invalid_json"


def test_status_errors_are_sanitized():
    for status_code, category, retry_allowed in [
        (401, "invalid_credentials", False),
        (403, "model_access_denied", False),
        (429, "provider_rate_limited", True),
        (500, "provider_unavailable", True),
    ]:
        error = type("FakeStatusError", (Exception,), {"code": status_code})("raw provider secret body")
        models = FakeModels(error=error)
        factory = FakeClientFactory(models)
        provider = GeminiEnhancementProvider(client_factory=factory)
        with pytest.raises(ProviderError) as captured:
            provider.enhance_bill(api_key="sk-test-secret", request=_request(), timeout_seconds=90)
        assert captured.value.category == category
        assert captured.value.retry_allowed is retry_allowed
        assert captured.value.outcome_unknown is False
        assert "raw provider" not in str(captured.value)
        assert len(models.calls) == 1


def test_timeout_is_unknown_outcome():
    error = type("APITimeoutError", (Exception,), {})("raw provider secret body")
    models = FakeModels(error=error)
    factory = FakeClientFactory(models)
    provider = GeminiEnhancementProvider(client_factory=factory)
    with pytest.raises(ProviderError) as captured:
        provider.enhance_bill(api_key="sk-test-secret", request=_request(), timeout_seconds=90)
    assert captured.value.category == "outcome_unknown"
    assert captured.value.outcome_unknown is True
    assert captured.value.retry_allowed is True
    assert captured.value.validation_code == "provider_timeout"
    assert len(models.calls) == 1


def test_connection_lost_is_unknown_outcome():
    error = type("APIConnectionError", (Exception,), {})("raw provider secret body")
    models = FakeModels(error=error)
    factory = FakeClientFactory(models)
    provider = GeminiEnhancementProvider(client_factory=factory)
    with pytest.raises(ProviderError) as captured:
        provider.enhance_bill(api_key="sk-test-secret", request=_request(), timeout_seconds=90)
    assert captured.value.category == "outcome_unknown"
    assert captured.value.outcome_unknown is True
    assert captured.value.validation_code == "provider_connection_lost"
    assert len(models.calls) == 1


@pytest.mark.parametrize("error_name", ["ReadError", "WriteError"])
def test_sdk_transport_failure_after_dispatch_is_unknown(error_name):
    import httpx
    from google import genai

    calls = []
    def respond(request):
        calls.append(request)
        raise getattr(httpx, error_name)("interrupted", request=request)

    def client_factory(*, api_key, http_options):
        http_options.client_args = {"transport": httpx.MockTransport(respond)}
        return genai.Client(api_key=api_key, http_options=http_options)

    with pytest.raises(ProviderError) as caught:
        GeminiEnhancementProvider(client_factory=client_factory).enhance_bill(
            api_key="offline", request=_request(), timeout_seconds=1)
    assert len(calls) == 1
    assert caught.value.category == "outcome_unknown"
    assert caught.value.outcome_unknown


def test_usage_and_resolved_model():
    models = FakeModels(result=_completed_response())
    factory = FakeClientFactory(models)
    provider = GeminiEnhancementProvider(client_factory=factory)
    result = provider.enhance_bill(api_key="test", request=_request(), timeout_seconds=30)
    assert result.usage.total_tokens == 172
    assert result.resolved_model == "gemini-2.5-flash-2026-08-01"


def test_retry_disabled_proven_in_client_and_config():
    models = FakeModels(result=_completed_response())
    factory = FakeClientFactory(models)
    provider = GeminiEnhancementProvider(client_factory=factory)
    provider.enhance_bill(api_key="test", request=_request(), timeout_seconds=30)
    assert factory.calls[0]["http_options"].retry_options.attempts == 1
    assert models.calls[0]["config"].http_options.retry_options.attempts == 1


def test_schema_strips_additional_properties_not_shared():
    from apps.legislation.enhancements.schema import PROVIDER_OUTPUT_SCHEMA
    models = FakeModels(result=_completed_response())
    factory = FakeClientFactory(models)
    provider = GeminiEnhancementProvider(client_factory=factory)
    provider.enhance_bill(api_key="test", request=_request(), timeout_seconds=30)
    wire = models.calls[0]["config"].response_json_schema
    assert "additionalProperties" not in json.dumps(wire)
    assert PROVIDER_OUTPUT_SCHEMA["additionalProperties"] is False


def test_validate_credential():
    models = FakeModels(result=_completed_response())
    factory = FakeClientFactory(models)
    provider = GeminiEnhancementProvider(client_factory=factory)
    check = provider.validate_credential(api_key="k", requested_model="m", timeout_seconds=30)
    assert check.valid is True
    assert len(models.calls) == 1
    assert models.calls[0]["config"].max_output_tokens == 16


def test_gemini_can_repair_citations_without_changing_models():
    models = FakeModels(result=_completed_response())
    provider = GeminiEnhancementProvider(client_factory=FakeClientFactory(models))
    request = _request()
    provider.repair_citations(api_key="test", request=request, payload={"claims": []}, timeout_seconds=30)
    assert models.calls[0]["model"] == request.requested_model
    assert json.loads(models.calls[0]["contents"]) == {"claims": []}
