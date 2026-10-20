import json
import re
from inspect import signature
from pathlib import Path
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


def test_reader_uses_confirmed_per_request_output_budget():
    response = _completed_response()
    response.output_text = json.dumps({'schema_version': '1.4', 'summary': [], 'explanations': []})
    responses = FakeResponses(result=response)
    provider = OpenAIEnhancementProvider(client_factory=FakeClientFactory(responses))
    request = _request()
    request.output_schema_version = '1.4'
    request.prompt_version = 'reader-2'
    request.request_envelope['max_output_tokens'] = 20000
    provider.enhance_bill(api_key='test', request=request, timeout_seconds=30)
    assert responses.calls[0]['max_output_tokens'] == 20000


@pytest.mark.parametrize("text,reason,position", [
    ('{"secret": "private"\n "x": 1}', "missing_comma", 22),
    ("", "empty_text", 0),
    (None, "wrong_text_type", None),
    ('{"x": "unfinished', "unterminated_string", 6),
])
def test_json_parser_diagnostics_preserve_location_not_content(text, reason, position):
    from apps.legislation.enhancements.diagnostics import provider_validation_diagnostic
    response = _completed_response()
    response.output_text = text
    provider = OpenAIEnhancementProvider(
        client_factory=FakeClientFactory(FakeResponses(result=response))
    )
    with pytest.raises(ProviderError) as caught:
        provider.enhance_bill(api_key="secret-key", request=_request(), timeout_seconds=30)
    detail = provider_validation_diagnostic(caught.value)
    assert detail["parser"]["reason"] == reason
    assert detail["parser"].get("position") == position
    assert detail["parser"]["text_length"] == (len(text) if isinstance(text, str) else 0)
    assert detail["parser"]["output_text_parts"] == 0
    assert caught.value.usage.total_tokens == 165
    assert "private" not in json.dumps(detail)
    assert "secret-key" not in json.dumps(detail)


def test_source_first_failure_reports_safe_schema_location():
    response = _completed_response()
    response.output_text = json.dumps(
        {
            "provisions": [
                {
                    "unit_id": "u1",
                    "status": "unresolved",
                    "summary": "x" * 401,
                    "details": [],
                    "claims": [],
                    "unresolved_reason": "missing",
                }
            ]
        }
    )
    provider = OpenAIEnhancementProvider(
        client_factory=FakeClientFactory(FakeResponses(result=response))
    )
    request = _request()
    request.request_envelope["source_first_payload"] = {
        "units": [{"id": "unit"}],
        "passages": {"passage": {"text": "Source."}},
    }
    with pytest.raises(ProviderError) as caught:
        provider.generate_provisions(
            api_key="test", request=request, timeout_seconds=30
        )
    assert caught.value.validation_detail == {
        "rule": "maxLength",
        "path": "provisions/0/summary",
    }
    assert "x" * 20 not in str(caught.value.validation_detail)


def test_source_first_decode_error_diagnostics_are_json_serializable(monkeypatch):
    from jsonschema import ValidationError

    from apps.legislation.enhancements.source_first_transport import Transport

    def reject(self, output):
        raise ValidationError("unrelated_source_item")

    monkeypatch.setattr(Transport, "decode", reject)
    provider = OpenAIEnhancementProvider(
        client_factory=FakeClientFactory(FakeResponses(result=_completed_response()))
    )
    request = _request()
    request.request_envelope["source_first_payload"] = {
        "units": [{"id": "unit"}],
        "passages": {"passage": {"text": "Source."}},
    }
    with pytest.raises(ProviderError) as caught:
        provider.generate_provisions(
            api_key="test", request=request, timeout_seconds=30
        )
    assert (
        json.loads(json.dumps(caught.value.validation_detail))["rule"]
        == "unrelated_source_item"
    )


@pytest.mark.parametrize(
    "method", ["generate_provisions", "repair_provisions", "generate_synopsis"]
)
def test_source_first_transport_uses_server_schema(method):
    response = _completed_response()
    response.output_text = json.dumps(
        {"text": "A rule.", "explanation_ids": ["u1"]}
        if method == "generate_synopsis"
        else {
            "provisions": [
                {
                    "unit_id": "u1",
                    "status": "unresolved",
                    "summary": "",
                    "details": [],
                    "claims": [],
                    "unresolved_reason": "Not enough context",
                }
            ]
        }
    )
    responses = FakeResponses(result=response)
    provider = OpenAIEnhancementProvider(client_factory=FakeClientFactory(responses))
    request = _request()
    request.request_envelope["source_first_payload"] = {
        "units": [{"id": "pinned-unit"}],
        "passages": {"pinned-passage": {"text": "exact source"}},
    }
    if method == "generate_synopsis":
        request.request_envelope["source_first_payload"] = {
            "explanations": [{"unit_id": "pinned-unit", "summary": "A rule."}]
        }
    result = getattr(provider, method)(
        api_key="test", request=request, timeout_seconds=30
    )
    call = responses.calls[0]
    if method != "generate_synopsis":
        assert json.loads(call["input"])["passages"]["p1"]["text"] == "exact source"
        assert result.output["provisions"][0]["unit_id"] == "pinned-unit"
    else:
        assert result.output["explanation_ids"] == ["pinned-unit"]
    assert call["text"]["format"]["name"].startswith("source_first_")
    assert call["store"] is False and call["tools"] == []
    assert call["max_output_tokens"] <= 8000
    # OpenAI rejects this keyword even though our local JSON Schema validator
    # supports it. Keep uniqueness enforcement local, not in the wire schema.
    assert '"uniqueItems"' not in json.dumps(call["text"]["format"]["schema"])
    from jsonschema import Draft202012Validator

    from apps.legislation.enhancements.source_first_schema import IDS

    assert not Draft202012Validator(IDS).is_valid(["same", "same"])


def test_source_first_caps_output_even_if_deployment_limit_is_higher(settings):
    settings.LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS = 16000
    response = _completed_response()
    response.output_text = json.dumps({"provisions": []})
    responses = FakeResponses(result=response)
    provider = OpenAIEnhancementProvider(client_factory=FakeClientFactory(responses))
    request = _request()
    request.request_envelope["source_first_payload"] = {"units": [], "passages": {}}
    provider.generate_provisions(api_key="test", request=request, timeout_seconds=30)
    assert responses.calls[0]["max_output_tokens"] == 8000


@pytest.mark.parametrize("output_limit", [4000, 8000])
def test_citation_repair_is_targeted_bounded_and_nonpersistent(settings, output_limit):
    settings.LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS = output_limit
    response = _completed_response()
    response.output_text = json.dumps({"repairs": []})
    responses = FakeResponses(result=response)
    provider = OpenAIEnhancementProvider(client_factory=FakeClientFactory(responses))
    payload = {
        "citations": [
            {"id": "overview/0/0", "claim": {"text": "Funding"}, "candidates": []}
        ]
    }
    result = provider.repair_citations(
        api_key="test", request=_request(), payload=payload, timeout_seconds=30
    )
    assert result.output == {"repairs": []}
    assert result.usage.total_tokens == 165
    call = responses.calls[0]
    assert json.loads(call["input"]) == payload
    assert call["store"] is False
    assert call["tools"] == []
    assert call["max_output_tokens"] == output_limit
    assert call["text"]["format"]["schema"]["properties"]["repairs"]


def test_citation_repair_rejects_oversize_before_network():
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


def test_provider_derives_reference_ids_from_the_single_quoted_citation_field():
    from .test_enhancement_glossary import output, packet
    from apps.legislation.enhancements.schema import validate_enhancement_output
    wire = output()
    del wire["glossary"][0]["source_refs"]
    response = _completed_response()
    response.output_text = json.dumps(wire)
    responses = FakeResponses(result=response)
    provider = OpenAIEnhancementProvider(client_factory=FakeClientFactory(responses))
    result = provider.enhance_bill(api_key="test", request=_request(), timeout_seconds=30)
    validated = validate_enhancement_output(result.output, packet())
    assert validated["glossary"][0]["source_refs"] == ["src_0001"]
    schema = responses.calls[0]["text"]["format"]["schema"]
    assert "source_refs" not in schema["properties"]["glossary"]["items"]["properties"]
    assert wire["glossary"][0]["source_quotes"] == result.output["glossary"][0]["source_quotes"]


def test_deriving_reference_ids_does_not_accept_a_wrong_source_quote():
    from .test_enhancement_glossary import output, packet
    from apps.legislation.enhancements.schema import validate_enhancement_output
    from jsonschema import ValidationError
    wire = output()
    del wire["glossary"][0]["source_refs"]
    wire["glossary"][0]["source_quotes"][0]["quote"] = "Secretary means the Secretary of Labor."
    response = _completed_response()
    response.output_text = json.dumps(wire)
    provider = OpenAIEnhancementProvider(client_factory=FakeClientFactory(FakeResponses(result=response)))
    result = provider.enhance_bill(api_key="test", request=_request(), timeout_seconds=30)
    with pytest.raises(ValidationError) as error:
        validate_enhancement_output(result.output, packet())
    assert error.value.validator == "glossary_definition_unsupported"


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
    assert call["text"]["format"]["type"] == "json_schema"
    assert call["text"]["format"]["name"] == "bill_enhancement_v1_1"
    assert call["text"]["format"]["strict"] is True
    provider_schema = call["text"]["format"]["schema"]
    assert "uniqueItems" not in json.dumps(provider_schema)
    assert provider_schema["properties"]["schema_version"]["type"] == "string"
    assert (
        provider_schema["properties"]["obligations"]["items"]["properties"]["modality"][
            "type"
        ]
        == "string"
    )
    assert (
        provider_schema["properties"]["funding_and_timing"]["items"]["properties"][
            "kind"
        ]["type"]
        == "string"
    )
    assert "source_refs" not in provider_schema["properties"]["overview"]["items"]["properties"]
    assert "source_quotes" in provider_schema["properties"]["overview"]["items"]["required"]
    assert (
        OUTPUT_SCHEMA["properties"]["overview"]["items"]["properties"]["source_refs"][
            "uniqueItems"
        ]
        is True
    )
    assert "previous_response_id" not in call
    assert "conversation" not in call
    assert result.output == _valid_output()
    assert result.response_id == "resp_test_123"
    assert result.resolved_model == "gpt-5.6-luna-2026-08-01"
    assert result.usage.total_tokens == 165


def test_declared_openai_floor_supports_the_adapter_privacy_argument():
    from openai.resources.responses.responses import Responses

    requirement_path = Path(__file__).resolve().parents[3] / "requirements" / "base.txt"
    requirement = next(
        line
        for line in requirement_path.read_text(encoding="utf-8").splitlines()
        if line.startswith("openai>=")
    )
    minimum = tuple(
        int(part) for part in re.match(r"openai>=(\d+)\.(\d+)", requirement).groups()
    )

    assert minimum >= (2, 54)
    assert "prompt_cache_options" in signature(Responses.create).parameters


def test_explicit_validation_makes_exactly_one_minimal_request():
    class ResponsesRequiringProviderMinimum(FakeResponses):
        def create(self, **kwargs):
            if kwargs["max_output_tokens"] < 16:
                error = type(
                    "FakeBadRequestError",
                    (Exception,),
                    {"status_code": 400, "param": "max_output_tokens"},
                )("max_output_tokens is below the provider minimum")
                raise error
            return super().create(**kwargs)

    response = SimpleNamespace(status="completed", output_text="OK", output=[])
    responses = ResponsesRequiringProviderMinimum(result=response)
    factory = FakeClientFactory(responses)
    provider = OpenAIEnhancementProvider(client_factory=factory)

    check = provider.validate_credential(
        api_key="sk-test-secret",
        requested_model="gpt-5.6-luna",
        timeout_seconds=30,
    )

    assert check.valid is True
    assert len(responses.calls) == 1
    assert responses.calls[0]["max_output_tokens"] == 16
    assert responses.calls[0]["store"] is False
    assert factory.calls[0]["max_retries"] == 0


@pytest.mark.parametrize(
    "status,text,reason,code",
    [
        ("incomplete", "private output", "max_output_tokens", "provider_output_limit"),
        ("incomplete", "private output", "private reason", "provider_incomplete"),
        ("completed", "private non-JSON output", None, "provider_invalid_json"),
        ("completed", "[]", None, "provider_output_not_object"),
    ],
)
def test_invalid_response_retains_sanitized_failure_stage(status, text, reason, code):
    response = SimpleNamespace(
        status=status,
        output_text=text,
        output=[],
        incomplete_details=SimpleNamespace(reason=reason),
    )
    provider = OpenAIEnhancementProvider(
        client_factory=FakeClientFactory(FakeResponses(result=response))
    )
    with pytest.raises(ProviderError) as caught:
        provider.enhance_bill(
            api_key="sk-test-secret", request=_request(), timeout_seconds=90
        )
    assert caught.value.validation_code == code
    assert "private" not in str(caught.value)


@pytest.mark.parametrize(
    ("status_code", "category", "retry_allowed"),
    [
        (400, "provider_request_rejected", True),
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
    assert captured.value.response_id == "resp_refused"
    assert captured.value.resolved_model == "gpt-5.6-luna"

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
    assert captured.value.response_id == "resp_incomplete"
    assert captured.value.resolved_model == "gpt-5.6-luna"


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
    assert captured.value.response_id == "resp_test_123"
    assert captured.value.resolved_model == "gpt-5.6-luna-2026-08-01"


def test_parses_explicit_final_answer_without_concatenating_commentary():
    response = _completed_response()
    final_text = response.output_text
    response.output = [SimpleNamespace(type="message", phase=phase, content=[
        SimpleNamespace(type="output_text", text=text)
    ]) for phase, text in [("commentary", '{"draft":true}'), ("final_answer", final_text)]]
    response.output_text = '{"draft":true}' + final_text
    provider = OpenAIEnhancementProvider(client_factory=FakeClientFactory(FakeResponses(result=response)))
    result = provider.enhance_bill(api_key="test", request=_request(), timeout_seconds=30)
    assert result.output == json.loads(final_text)


def test_does_not_guess_between_multiple_final_json_objects():
    response = _completed_response()
    response.output = [SimpleNamespace(type="message", phase="final_answer", content=[
        SimpleNamespace(type="output_text", text=response.output_text)
    ])] * 2
    response.output_text *= 2
    provider = OpenAIEnhancementProvider(client_factory=FakeClientFactory(FakeResponses(result=response)))
    with pytest.raises(ProviderError) as caught:
        provider.enhance_bill(api_key="test", request=_request(), timeout_seconds=30)
    assert caught.value.category == "invalid_output"
