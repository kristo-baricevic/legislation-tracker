from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from django.conf import settings

from apps.legislation.enhancements.schema import OUTPUT_SCHEMA

from .base import CredentialCheck, ProviderError, ProviderResult, ProviderUsage


def _value(obj: Any, name: str, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _usage(response) -> ProviderUsage:
    usage = _value(response, "usage")
    if usage is None:
        return ProviderUsage()
    return ProviderUsage(
        input_tokens=_value(usage, "input_tokens"),
        output_tokens=_value(usage, "output_tokens"),
        total_tokens=_value(usage, "total_tokens"),
    )


def _contains_refusal(response) -> bool:
    for output_item in _value(response, "output", []) or []:
        if _value(output_item, "type") != "message":
            continue
        for content in _value(output_item, "content", []) or []:
            if _value(content, "type") == "refusal":
                return True
    return False


def _mapped_error(error: Exception) -> ProviderError:
    class_name = type(error).__name__.lower()
    if "timeout" in class_name or "connection" in class_name:
        return ProviderError(
            "outcome_unknown",
            outcome_unknown=True,
            retry_allowed=True,
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
        return ProviderError("invalid_output")
    return ProviderError("provider_unavailable", retry_allowed=True)


class OpenAIEnhancementProvider:
    provider_name = "openai"

    def __init__(self, *, client_factory: Callable[..., Any] | None = None):
        if client_factory is None:
            from openai import OpenAI

            client_factory = OpenAI
        self._client_factory = client_factory

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
                max_output_tokens=8,
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
        client = self._client(api_key=api_key, timeout_seconds=timeout_seconds)
        input_payload = {
            "bill": request.request_envelope["bill"],
            "source_packet": request.request_envelope["source_packet"],
        }
        try:
            response = client.responses.create(
                model=request.requested_model,
                instructions=request.request_envelope["instructions"],
                input=json.dumps(
                    input_payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ),
                max_output_tokens=settings.LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS,
                reasoning={"effort": request.reasoning_effort},
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "bill_enhancement_v1_1",
                        "schema": OUTPUT_SCHEMA,
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
            raise _mapped_error(error) from None

        usage = _usage(response)
        if _contains_refusal(response):
            raise ProviderError("content_refusal", usage=usage)
        if _value(response, "status") != "completed":
            raise ProviderError("invalid_output", usage=usage)
        output_text = _value(response, "output_text", "")
        try:
            output = json.loads(output_text)
        except (TypeError, ValueError):
            raise ProviderError("invalid_output", usage=usage) from None
        if not isinstance(output, dict):
            raise ProviderError("invalid_output", usage=usage)
        return ProviderResult(
            output=output,
            usage=usage,
            response_id=str(_value(response, "id", "") or ""),
            resolved_model=str(_value(response, "model", "") or ""),
        )
