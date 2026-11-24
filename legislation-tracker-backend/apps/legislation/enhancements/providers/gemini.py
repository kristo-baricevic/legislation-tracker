from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import httpx
from django.conf import settings

from apps.legislation.enhancements.citations import REPAIR_INSTRUCTIONS, REPAIR_SCHEMA
from apps.legislation.enhancements.schema import PROVIDER_OUTPUT_SCHEMA

from .base import CredentialCheck, ProviderCapabilities, ProviderError, ProviderResult, ProviderUsage
from . import harness


def _value(obj: Any, name: str, default=None):
    return harness.value(obj, name, default)


def _usage(response) -> ProviderUsage:
    usage = _value(response, "usage_metadata")
    if usage is None:
        return ProviderUsage()
    thoughts = _value(usage, "thoughts_token_count")
    visible = _value(usage, "candidates_token_count")
    prompt = _value(usage, "prompt_token_count")
    total = _value(usage, "total_token_count")
    output = None if visible is None else visible + (thoughts or 0)
    if visible is None and prompt is not None and total is not None:
        # Gemini includes tool inputs in the total and cached inputs in the prompt.
        tool_input = _value(usage, "tool_use_prompt_token_count") or 0
        generated = total - prompt - tool_input
        if min(prompt, tool_input, thoughts or 0) >= 0 and generated >= (thoughts or 0):
            output = generated
    return ProviderUsage(
        input_tokens=prompt,
        output_tokens=output,
        total_tokens=total,
        reasoning_tokens=thoughts,
        visible_output_tokens=visible,
    )


def _mapped_error(error: Exception) -> ProviderError:
    class_name = type(error).__name__.lower()
    if isinstance(error, httpx.TimeoutException) or "timeout" in class_name:
        return ProviderError(
            "outcome_unknown",
            outcome_unknown=True,
            retry_allowed=True,
            validation_code="provider_timeout",
        )
    if (isinstance(error, (httpx.ReadError, httpx.WriteError, httpx.CloseError, httpx.RemoteProtocolError))
            or "connection" in class_name or "protocol" in class_name):
        return ProviderError(
            "outcome_unknown",
            outcome_unknown=True,
            retry_allowed=True,
            validation_code="provider_connection_lost",
        )

    status_code = getattr(error, "code", None)
    if status_code is None:
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


def _thinking_config(effort: str):
    from google.genai import types

    normalized = (effort or "").strip().lower()
    if normalized == "none":
        return types.ThinkingConfig(thinking_budget=0)
    levels = {
        "minimal": types.ThinkingLevel.MINIMAL,
        "low": types.ThinkingLevel.LOW,
        "medium": types.ThinkingLevel.MEDIUM,
        "high": types.ThinkingLevel.HIGH,
        "xhigh": types.ThinkingLevel.XHIGH,
        "max": types.ThinkingLevel.XHIGH,
    }
    level = levels.get(normalized)
    if level is None:
        return None
    return types.ThinkingConfig(thinking_level=level)


class GeminiEnhancementProvider:
    provider_name = "gemini"
    capabilities = ProviderCapabilities(
        wire_api="gemini_generate_content",
        schema_profile="gemini_json_schema",
        reasoning_mapping={
            "none": "thinking_budget:0",
            "minimal": "MINIMAL",
            "low": "LOW",
            "medium": "MEDIUM",
            "high": "HIGH",
            "xhigh": "XHIGH",
            "max": "XHIGH",
        },
        privacy_flags={
            "tools": [],
            "cached_content": None,
        },
        validation_profile="gemini_generate_content",
        usage_shape="gemini_usage",
        refusal_completion_profile="gemini_finish_reason",
        error_profile="gemini_status_code",
        unsupported_schema_keywords=frozenset({"additionalProperties"}),
    )

    def __init__(self, *, client_factory: Callable[..., Any] | None = None):
        if client_factory is None:
            from google import genai

            client_factory = genai.Client
        self._client_factory = client_factory

    def _http_options(self, *, timeout_seconds: int):
        from google.genai import types

        return types.HttpOptions(
            timeout=timeout_seconds * 1000,
            retry_options=types.HttpRetryOptions(attempts=1),
        )

    def _client(self, *, api_key: str, timeout_seconds: int):
        return self._client_factory(
            api_key=api_key,
            http_options=self._http_options(timeout_seconds=timeout_seconds),
        )

    def validate_credential(
        self,
        *,
        api_key: str,
        requested_model: str,
        timeout_seconds: int,
    ) -> CredentialCheck:
        from google.genai import types

        client = self._client(api_key=api_key, timeout_seconds=timeout_seconds)
        http_options = self._http_options(timeout_seconds=timeout_seconds)
        try:
            models = getattr(client, "models", client)
            response = models.generate_content(
                model=requested_model,
                contents="Reply with OK.",
                config=types.GenerateContentConfig(
                    max_output_tokens=16,
                    http_options=http_options,
                ),
            )
        except Exception as error:  # noqa: BLE001
            mapped = _mapped_error(error)
            if mapped.category in {"invalid_credentials", "model_access_denied"}:
                return CredentialCheck(valid=False, category=mapped.category)
            raise mapped from None
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
        return result

    def repair_citations(self, *, api_key, request, payload, timeout_seconds):
        harness.ensure_citation_repair_fits(payload, request)
        return self._generate(
            api_key=api_key, request=request, timeout_seconds=timeout_seconds,
            input_payload=payload, instructions=REPAIR_INSTRUCTIONS, schema=REPAIR_SCHEMA,
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
        from google.genai import types

        client = self._client(api_key=api_key, timeout_seconds=timeout_seconds)
        max_output_tokens = harness.resolve_max_output_tokens(request, schema_name)
        http_options = self._http_options(timeout_seconds=timeout_seconds)
        wire_schema = _wire_schema(
            schema,
            unsupported_keywords=self.capabilities.unsupported_schema_keywords,
        )
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=wire_schema,
            max_output_tokens=max_output_tokens,
            http_options=http_options,
            tools=None,
            cached_content=None,
            system_instruction=instructions,
        )
        thinking = _thinking_config(getattr(request, "reasoning_effort", "none"))
        if thinking is not None:
            config.thinking_config = thinking

        input_text = json.dumps(
            input_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        try:
            models = getattr(client, "models", client)
            response = models.generate_content(
                model=request.requested_model,
                contents=input_text,
                config=config,
            )
        except ProviderError:
            raise
        except Exception as error:  # noqa: BLE001
            mapped = _mapped_error(error)
            mapped.validation_detail = {"timeout_seconds": timeout_seconds}
            raise mapped from None

        usage = _usage(response)
        response_id = str(_value(response, "response_id", "") or "")
        resolved_model = str(
            _value(response, "model_version", "")
            or _value(response, "model", "")
            or ""
        )

        candidates = _value(response, "candidates", []) or []
        candidate = candidates[0] if candidates else None
        finish_reason = _value(candidate, "finish_reason") if candidate is not None else None
        finish_reason_str = ""
        if finish_reason is not None:
            finish_reason_str = str(finish_reason).split(".")[-1].upper()

        prompt_feedback = _value(response, "prompt_feedback")
        block_reason = _value(prompt_feedback, "block_reason") if prompt_feedback is not None else None

        if block_reason not in (None, "", "BLOCK_REASON_UNSPECIFIED"):
            raise ProviderError(
                "content_refusal",
                usage=usage,
                response_id=response_id,
                resolved_model=resolved_model,
            )
        if finish_reason_str in {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "LANGUAGE"}:
            raise ProviderError(
                "content_refusal",
                usage=usage,
                response_id=response_id,
                resolved_model=resolved_model,
            )
        if finish_reason_str == "MAX_TOKENS":
            raise ProviderError(
                "invalid_output",
                validation_code="provider_output_limit",
                usage=usage,
                response_id=response_id,
                resolved_model=resolved_model,
            )
        if finish_reason_str != "STOP":
            raise ProviderError(
                "invalid_output",
                validation_code="provider_incomplete",
                usage=usage,
                response_id=response_id,
                resolved_model=resolved_model,
            )

        parts = []
        if candidate is not None:
            content = _value(candidate, "content")
            for part in (_value(content, "parts", []) or []):
                text = _value(part, "text")
                if isinstance(text, str) and not bool(_value(part, "thought", False)):
                    parts.append(text)
        output_text = "".join(parts)
        if not parts:
            fallback = _value(response, "text")
            if isinstance(fallback, str):
                output_text = fallback

        from ..private_diagnostics import capture_visible
        capture_visible([{"instructions": instructions, "input": input_payload}], wire_schema,
                        output_text, finish_reason_str, response_id, resolved_model, api_key)
        return harness.parse_json_output(
            output_text,
            usage=usage,
            response_id=response_id,
            resolved_model=resolved_model,
            text_parts=parts,
        )
