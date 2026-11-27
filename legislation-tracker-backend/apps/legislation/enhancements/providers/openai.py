from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from apps.legislation.enhancements.citations import REPAIR_INSTRUCTIONS, REPAIR_SCHEMA
from apps.legislation.enhancements.schema import PROVIDER_OUTPUT_SCHEMA

from . import harness
from .base import (
    CredentialCheck,
    ProviderCapabilities,
    ProviderError,
    ProviderResult,
    ProviderUsage,
)
from .session import delivery_client


def _value(obj: Any, name: str, default=None):
    return harness.value(obj, name, default)


def _usage(response) -> ProviderUsage:
    return harness.usage_from_response(response)


def _contains_refusal(response) -> bool:
    return harness.contains_refusal(response)


def _mapped_error(error: Exception) -> ProviderError:
    class_name = type(error).__name__.lower()
    if "timeout" in class_name or "connection" in class_name:
        return ProviderError(
            "outcome_unknown",
            outcome_unknown=True,
            retry_allowed=True,
            validation_code=(
                "provider_timeout"
                if "timeout" in class_name
                else "provider_connection_lost"
            ),
        )
    body = getattr(error, "body", None)
    error_code = getattr(error, "code", None)
    if isinstance(body, dict):
        error_code = body.get("code", error_code)
        nested_error = body.get("error")
        if isinstance(nested_error, dict):
            error_code = nested_error.get("code", error_code)
    if error_code in {"insufficient_quota", "billing_hard_limit_reached"}:
        return ProviderError("quota_exhausted")
    if error_code in {"context_length_exceeded", "max_tokens_exceeded"}:
        return ProviderError("request_too_large")
    if error_code == "model_not_found":
        return ProviderError("model_access_denied")

    status_code = getattr(error, "status_code", None)
    if status_code == 401:
        return ProviderError("invalid_credentials")
    if status_code == 403:
        return ProviderError("model_access_denied")
    if status_code == 429:
        return ProviderError("provider_rate_limited", retry_allowed=True)
    if isinstance(status_code, int) and status_code >= 500:
        return ProviderError("provider_unavailable", retry_allowed=True)
    if status_code == 400:
        return ProviderError("provider_request_rejected", retry_allowed=True)
    return ProviderError("provider_unavailable", retry_allowed=True)


def _wire_schema(value, *, unsupported_keywords=()):
    return harness.wire_schema(value, unsupported_keywords=unsupported_keywords)


class OpenAIEnhancementProvider:
    provider_name = "openai"
    capabilities = ProviderCapabilities(
        wire_api="openai_responses",
        schema_profile="openai_json_schema_strict",
        reasoning_mapping={
            "none": "none",
            "minimal": "minimal",
            "low": "low",
            "medium": "medium",
            "high": "high",
            "xhigh": "xhigh",
        },
        privacy_flags={
            "store": False,
            "truncation": "disabled",
            "tools": [],
            "prompt_cache_options": {"mode": "explicit", "ttl": "30m"},
        },
        validation_profile="openai_responses",
        usage_shape="openai_usage",
        refusal_completion_profile="openai_refusal_incomplete",
        error_profile="openai_status_code",
        unsupported_schema_keywords=frozenset({"uniqueItems"}),
    )

    def __init__(self, *, client_factory: Callable[..., Any] | None = None):
        if client_factory is None:
            from openai import OpenAI

            client_factory = OpenAI
        self._client_factory = client_factory

    @delivery_client
    def _client(self, *, api_key: str, timeout_seconds: int):
        return self._client_factory(
            api_key=api_key,
            max_retries=0,
            timeout=timeout_seconds,
        )

    @staticmethod
    def _privacy_controls() -> dict[str, Any]:
        return {
            "store": False,
            "truncation": "disabled",
            "tools": [],
            # Explicit mode disables the implicit cache breakpoint. No content
            # block sent by this adapter includes a prompt_cache_breakpoint.
            "prompt_cache_options": {"mode": "explicit", "ttl": "30m"},
        }

    def validate_credential(
        self,
        *,
        api_key: str,
        requested_model: str,
        timeout_seconds: int,
    ) -> CredentialCheck:
        client = self._client(api_key=api_key, timeout_seconds=timeout_seconds)
        try:
            response = client.responses.create(
                model=requested_model,
                input="Reply with OK.",
                max_output_tokens=16,
                reasoning={"effort": "none"},
                **self._privacy_controls(),
            )
        # Normalize all SDK/transport exception types at this adapter boundary;
        # no raw provider message is allowed to cross into API or persistence.
        except Exception as error:  # noqa: BLE001
            mapped = _mapped_error(error)
            if mapped.category in {"invalid_credentials", "model_access_denied"}:
                return CredentialCheck(valid=False, category=mapped.category)
            raise mapped from None
        if _value(response, "status") != "completed":
            raise ProviderError("provider_unavailable", retry_allowed=True)
        return CredentialCheck(valid=True)

    def enhance_bill(
        self,
        *,
        api_key: str,
        request,
        timeout_seconds: int,
    ) -> ProviderResult:
        input_payload = {
            "bill": request.request_envelope["bill"],
            "source_packet": request.request_envelope["source_packet"],
        }
        schema = harness.select_bill_schema(request, input_payload)
        result = self._generate(
            api_key=api_key,
            request=request,
            timeout_seconds=timeout_seconds,
            input_payload=input_payload,
            instructions=request.request_envelope["instructions"],
            schema=schema,
            schema_name="bill_enhancement_v1_1",
        )
        if schema is PROVIDER_OUTPUT_SCHEMA:
            result = harness.apply_derived_source_refs(result)
        return harness.decode_bill_result(result, schema)

    def repair_citations(self, *, api_key, request, payload, timeout_seconds):
        harness.ensure_citation_repair_fits(payload, request)
        return self._generate(
            api_key=api_key,
            request=request,
            timeout_seconds=timeout_seconds,
            input_payload=payload,
            instructions=REPAIR_INSTRUCTIONS,
            schema=REPAIR_SCHEMA,
            schema_name="citation_repair_v1",
        )

    def _source_first(self, *, api_key, request, timeout_seconds, stage):
        instructions, transport = harness.prepare_source_first(
            stage, request.request_envelope["source_first_payload"]
        )
        payload, schema = transport.payload, transport.schema
        harness.ensure_source_first_fits(instructions, payload, schema)
        result = self._generate(
            api_key=api_key,
            request=request,
            timeout_seconds=timeout_seconds,
            input_payload=payload,
            instructions=instructions,
            schema=schema,
            schema_name=f"source_first_{stage}",
        )
        return harness.decode_source_first_output(transport, result)

    def generate_provisions(self, *, api_key, request, timeout_seconds):
        return self._source_first(
            api_key=api_key,
            request=request,
            timeout_seconds=timeout_seconds,
            stage="generation",
        )

    def repair_provisions(self, *, api_key, request, timeout_seconds):
        return self._source_first(
            api_key=api_key,
            request=request,
            timeout_seconds=timeout_seconds,
            stage="repair",
        )

    def generate_synopsis(self, *, api_key, request, timeout_seconds):
        return self._source_first(
            api_key=api_key,
            request=request,
            timeout_seconds=timeout_seconds,
            stage="synopsis",
        )

    def _generate(
        self,
        *,
        api_key,
        request,
        timeout_seconds,
        input_payload,
        instructions,
        schema,
        schema_name,
    ):
        client = self._client(api_key=api_key, timeout_seconds=timeout_seconds)
        max_output_tokens = harness.resolve_max_output_tokens(request, schema_name)
        try:
            response = client.responses.create(
                model=request.requested_model,
                instructions=instructions,
                input=json.dumps(
                    input_payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ),
                max_output_tokens=max_output_tokens,
                reasoning={"effort": request.reasoning_effort},
                text={
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "schema": _wire_schema(
                            schema,
                            unsupported_keywords=self.capabilities.unsupported_schema_keywords,
                        ),
                        "strict": True,
                    }
                },
                **self._privacy_controls(),
            )
        except ProviderError:
            raise
        # See validate_credential: the adapter owns sanitization for every SDK
        # exception, including version-specific subclasses.
        except Exception as error:  # noqa: BLE001
            mapped = _mapped_error(error)
            mapped.validation_detail = {"timeout_seconds": timeout_seconds}
            raise mapped from None

        usage = _usage(response)
        response_id = str(_value(response, "id", "") or "")
        resolved_model = str(_value(response, "model", "") or "")
        if _contains_refusal(response):
            raise ProviderError(
                "content_refusal",
                usage=usage,
                response_id=response_id,
                resolved_model=resolved_model,
            )
        if _value(response, "status") != "completed":
            raise ProviderError(
                "invalid_output",
                validation_code=(
                    "provider_output_limit"
                    if _value(_value(response, "incomplete_details"), "reason")
                    == "max_output_tokens"
                    else "provider_incomplete"
                ),
                usage=usage,
                response_id=response_id,
                resolved_model=resolved_model,
            )
        output_text = _value(response, "output_text", "")
        # The SDK convenience property concatenates commentary and final text.
        # Only an explicitly marked final answer can disambiguate those phases;
        # never salvage an arbitrary JSON object from malformed model output.
        final_messages = [
            item
            for item in (_value(response, "output", []) or [])
            if _value(item, "type") == "message"
            and _value(item, "phase") == "final_answer"
        ]
        if final_messages:
            output_text = "".join(
                _value(content, "text", "")
                for item in final_messages
                for content in (_value(item, "content", []) or [])
                if _value(content, "type") == "output_text"
                and isinstance(_value(content, "text"), str)
            )
        parts = [
            _value(content, "text", "")
            for item in (_value(response, "output", []) or [])
            for content in (_value(item, "content", []) or [])
            if _value(content, "type") == "output_text"
            and isinstance(_value(content, "text"), str)
        ]
        from ..private_diagnostics import capture_visible

        capture_visible(
            [{"instructions": instructions, "input": input_payload}],
            schema,
            output_text,
            _value(response, "status", ""),
            response_id,
            resolved_model,
            api_key,
        )
        return harness.parse_json_output(
            output_text,
            usage=usage,
            response_id=response_id,
            resolved_model=resolved_model,
            text_parts=parts,
        )
