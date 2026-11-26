from __future__ import annotations

import asyncio
import inspect
import json
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
from .session import delivery_client, in_provider_session, run_async

_MODE_ALIASES = {
    "json_schema": "json_schema",
    "json-schema": "json_schema",
    "jsonschema": "json_schema",
    "structured": "json_schema",
    "json_object": "json_object",
    "json-object": "json_object",
    "jsonobject": "json_object",
    "object": "json_object",
    "prompt_json": "prompt_json",
    "prompt-json": "prompt_json",
    "promptjson": "prompt_json",
    "prompt": "prompt_json",
    "text": "prompt_json",
    "none": "prompt_json",
    "off": "prompt_json",
}


def _value(obj: Any, name: str, default=None):
    return harness.value(obj, name, default)


def _local_prose_patterns(schema):
    """Do not constrain prose token decoding with regexes; validate it locally.

    OpenRouter routes use different grammar engines. Keep prose regex checks
    local rather than relying on decoder-specific regex interpretation.
    Citation ID patterns, shape, enums and length limits remain on the wire.
    The original schema is never mutated.
    """
    if isinstance(schema, dict):
        result = {key: _local_prose_patterns(value) for key, value in schema.items()}
        text = result.get("properties", {}).get("text")
        if isinstance(text, dict):
            text.pop("pattern", None)
        return result
    if isinstance(schema, list):
        return [_local_prose_patterns(value) for value in schema]
    return schema


def _free_routing():
    return {
        "max_price": {"prompt": 0, "completion": 0, "request": 0},
        "require_parameters": True,
    }


def _mapped_error(error: Exception) -> ProviderError:
    class_name = type(error).__name__.lower()
    if "timeout" in class_name:
        return ProviderError(
            "outcome_unknown",
            outcome_unknown=True,
            retry_allowed=True,
            validation_code="provider_timeout",
        )
    if "connection" in class_name:
        return ProviderError(
            "outcome_unknown",
            outcome_unknown=True,
            retry_allowed=True,
            validation_code="provider_connection_lost",
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
    if status_code == 402:
        return ProviderError("quota_exhausted")
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


def _chat_completions(client: Any):
    chat = getattr(client, "chat", None)
    if chat is not None:
        completions = getattr(chat, "completions", None)
        if completions is not None:
            return completions
    completions = getattr(client, "completions", None)
    if completions is not None:
        return completions
    return client


def _complete(client, timeout_seconds, **kwargs):
    async def run():
        try:
            result = _chat_completions(client).create(**kwargs)
            # Production uses AsyncOpenAI: cancellation closes the outstanding
            # HTTP operation even when keepalive bytes reset its read timeout.
            if inspect.isawaitable(result):
                return await asyncio.wait_for(result, timeout=timeout_seconds)
            return result  # synchronous test/client adapters
        finally:
            close = getattr(client, "close", None)
            if close and not in_provider_session():
                result = close()
                if inspect.isawaitable(result):
                    await result

    return run_async(run())


class OpenAICompatibleEnhancementProvider:
    provider_name = "openai_compatible"
    capabilities = ProviderCapabilities(
        wire_api="openai_chat_completions",
        schema_profile="openai_chat_json_schema",
        reasoning_mapping={},
        privacy_flags={},
        validation_profile="openai_chat_completions",
        usage_shape="openai_chat_usage",
        refusal_completion_profile="openai_chat_refusal",
        error_profile="openai_status_code",
        unsupported_schema_keywords=frozenset({"uniqueItems"}),
    )

    def __init__(
        self,
        api_key=None,
        base_url=None,
        model=None,
        *,
        client_factory=None,
        client=None,
        openai_client=None,
        http_client=None,
        factory=None,
        timeout=None,
        structured_output_mode=None,
        structured_output=None,
        output_mode=None,
        response_format_mode=None,
        mode=None,
        supports_json_schema=None,
        json_schema_supported=None,
        can_use_json_schema=None,
        fallback_mode=None,
        fallback=None,
        json_schema_fallback=None,
        capabilities=None,
        **kwargs,
    ):
        factory = client_factory or client or openai_client or http_client or factory
        if factory is None:
            from openai import AsyncOpenAI

            factory = AsyncOpenAI
        self._client_factory = factory
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout = timeout

        # Absorb arbitrary kwargs as attributes for forward-compat.
        for key, val in kwargs.items():
            setattr(self, f"_kw_{key}", val)

        # Resolve structured output mode.
        self.structured_output_mode = None
        self._structured_output_mode_override = self._resolve_mode_hint(
            structured_output_mode,
            structured_output,
            output_mode,
            response_format_mode,
            mode,
            supports_json_schema,
            json_schema_supported,
            can_use_json_schema,
            capabilities,
            kwargs,
        )
        self._fallback_mode = self._normalize_mode(
            fallback_mode or fallback or json_schema_fallback or "json_object"
        )
        self.structured_output_mode = self._structured_output_mode_override
        if capabilities is not None:
            self.capabilities = capabilities
        else:
            mode = self._structured_output_mode_override
            schema_profile = f"openai_chat_{mode}"
            self.capabilities = ProviderCapabilities(
                wire_api="openai_chat_completions",
                schema_profile=schema_profile,
                reasoning_mapping={},
                privacy_flags={},
                validation_profile=schema_profile,
                usage_shape="openai_chat_usage",
                refusal_completion_profile="openai_chat_refusal",
                error_profile="openai_status_code",
                unsupported_schema_keywords=frozenset({"uniqueItems"}),
            )

    def _normalize_mode(self, value: Any) -> str:
        if isinstance(value, bool):
            return "json_schema" if value else self._fallback_or("json_object")
        if isinstance(value, str):
            key = value.strip().lower().replace(" ", "_")
            if key in _MODE_ALIASES:
                return _MODE_ALIASES[key]
            if "json_schema" in key or "jsonschema" in key:
                return "json_schema"
            if "json_object" in key or "jsonobject" in key or "object" in key:
                return "json_object"
            if "prompt" in key or "text" in key or "none" in key or "off" in key:
                return "prompt_json"
        # Capability-based hints.
        if isinstance(value, ProviderCapabilities):
            profile = str(getattr(value, "schema_profile", "") or "").lower()
            if "json_object" in profile or "jsonobject" in profile:
                return "json_object"
            if "prompt" in profile or "text" in profile:
                return "prompt_json"
            if "json_schema" in profile or "jsonschema" in profile:
                return "json_schema"
        return "json_schema"

    def _fallback_or(self, default: str) -> str:
        return default

    def _resolve_mode_hint(self, *hints, capabilities=None, kwargs=None) -> str:
        kwargs = kwargs or {}
        # Direct mode strings / booleans.
        for hint in hints[:5]:
            if hint is None:
                continue
            if isinstance(hint, bool):
                return "json_schema" if hint else "json_object"
            if isinstance(hint, str):
                return self._normalize_mode(hint)
        # Capability-based mode declaration.
        caps = capabilities
        if caps is None:
            # Check class/instance capabilities.
            caps = getattr(self, "capabilities", None)
        # Search kwargs for mode hints.
        for key in (
            "structured_output_mode",
            "structured_output",
            "output_mode",
            "response_format_mode",
            "mode",
        ):
            val = kwargs.get(key)
            if isinstance(val, str):
                return self._normalize_mode(val)
            if isinstance(val, bool):
                return "json_schema" if val else "json_object"
        # supports_json_schema flags.
        for key in (
            "supports_json_schema",
            "json_schema_supported",
            "can_use_json_schema",
        ):
            val = kwargs.get(key)
            if val is False:
                return "json_object"
            if val is True:
                return "json_schema"
        for hint in hints[5:8]:
            if hint is False:
                return "json_object"
            if hint is True:
                return "json_schema"
            if isinstance(hint, ProviderCapabilities):
                return self._normalize_mode(hint)
        # Capabilities schema_profile hint.
        if isinstance(caps, ProviderCapabilities):
            profile = str(getattr(caps, "schema_profile", "") or "").lower()
            if "json_object" in profile:
                return "json_object"
            if "prompt" in profile or "prompt_json" in profile:
                return "prompt_json"
        # Check any _kw_ attributes set from kwargs.
        for attr in list(vars(self)):
            if attr.startswith("_kw_"):
                key = attr[len("_kw_") :]
                val = getattr(self, attr)
                if key in {
                    "structured_output_mode",
                    "structured_output",
                    "output_mode",
                    "response_format_mode",
                    "mode",
                } and isinstance(val, str):
                    return self._normalize_mode(val)
                if (
                    key
                    in {
                        "supports_json_schema",
                        "json_schema_supported",
                        "can_use_json_schema",
                    }
                    and val is False
                ):
                    return "json_object"
        # Default.
        return "json_schema"

    def _structured_output_mode(self) -> str:
        val = getattr(self, "structured_output_mode", None)
        if isinstance(val, str):
            return self._normalize_mode(val)
        return getattr(self, "_structured_output_mode_override", "json_schema")

    @delivery_client
    def _client(self, *, api_key=None, timeout_seconds=None):
        key = api_key if api_key is not None else self.api_key
        timeout = timeout_seconds if timeout_seconds is not None else self.timeout
        return self._client_factory(
            api_key=key,
            base_url=self.base_url,
            max_retries=0,
            timeout=timeout,
        )

    def _model(self, request=None, requested_model=None):
        if requested_model is not None:
            return requested_model
        if request is not None:
            model = getattr(request, "requested_model", None)
            if model is not None:
                return model
        if self.model is not None:
            return self.model
        return None

    def _send(self, *, api_key, timeout_seconds, **kwargs):
        client = self._client(api_key=api_key, timeout_seconds=timeout_seconds)
        return _complete(client, timeout_seconds, **kwargs)

    def validate_credential(
        self,
        *,
        api_key=None,
        requested_model=None,
        timeout_seconds=None,
    ) -> CredentialCheck:
        model = self._model(requested_model=requested_model)
        free_route = self.base_url.rstrip(
            "/"
        ) == "https://openrouter.ai/api/v1" and model.endswith(":free")
        options = (
            {"extra_body": {"provider": _free_routing()}}
            if free_route
            else {"tools": []}
        )
        try:
            response = self._send(
                api_key=api_key,
                timeout_seconds=timeout_seconds,
                model=model,
                messages=[{"role": "user", "content": "Reply with OK."}],
                max_tokens=16,
                **options,
            )
        except Exception as error:  # noqa: BLE001
            mapped = _mapped_error(error)
            if mapped.category in {"invalid_credentials", "model_access_denied"}:
                return CredentialCheck(valid=False, category=mapped.category)
            raise mapped from None
        choices = _value(response, "choices", []) or []
        if not choices:
            raise ProviderError("provider_unavailable", retry_allowed=True)
        if free_route and _value(response, "model") != model:
            return CredentialCheck(valid=False, category="model_access_denied")
        return CredentialCheck(valid=True)

    def enhance_bill(
        self,
        *,
        api_key=None,
        request=None,
        timeout_seconds=None,
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

    def repair_citations(
        self, *, api_key=None, request=None, payload=None, timeout_seconds=None
    ):
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

    def _source_first(
        self, *, api_key=None, request=None, timeout_seconds=None, stage="generation"
    ):
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

    def generate_provisions(self, *, api_key=None, request=None, timeout_seconds=None):
        return self._source_first(
            api_key=api_key,
            request=request,
            timeout_seconds=timeout_seconds,
            stage="generation",
        )

    def repair_provisions(self, *, api_key=None, request=None, timeout_seconds=None):
        return self._source_first(
            api_key=api_key,
            request=request,
            timeout_seconds=timeout_seconds,
            stage="repair",
        )

    def generate_synopsis(self, *, api_key=None, request=None, timeout_seconds=None):
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
        max_output_tokens = harness.resolve_max_output_tokens(request, schema_name)
        model = self._model(request=request)
        wire = harness.wire_schema(
            schema, unsupported_keywords=self.capabilities.unsupported_schema_keywords
        )
        if getattr(request, "provider", "") == "openrouter":
            wire = _local_prose_patterns(wire)
        messages = [
            {"role": "system", "content": instructions},
            {
                "role": "user",
                "content": json.dumps(
                    input_payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ),
            },
        ]
        mode = self._structured_output_mode()
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_output_tokens,
            "tools": [],
        }
        if mode == "json_schema":
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "schema": wire,
                    "strict": True,
                },
            }
        elif mode == "json_object":
            kwargs["response_format"] = {"type": "json_object"}

        if getattr(request, "provider", "") == "openrouter":
            effort = getattr(request, "reasoning_effort", "none")
            # An unspecified effort preserves the model's own reasoning default.
            if effort != "none":
                kwargs["extra_body"] = {"reasoning": {"effort": effort}}

        if getattr(request, "provider", "") == "openrouter" and model.endswith(":free"):
            routing = kwargs.setdefault("extra_body", {})
            routing["provider"] = _free_routing()
        try:
            response = self._send(
                api_key=api_key, timeout_seconds=timeout_seconds, **kwargs
            )
        except ProviderError:
            raise
        except Exception as error:  # noqa: BLE001
            mapped = _mapped_error(error)
            mapped.validation_detail = {"timeout_seconds": timeout_seconds}
            raise mapped from None

        choices = _value(response, "choices", []) or []
        if not choices:
            raise ProviderError(
                "invalid_output",
                validation_code="provider_incomplete",
                usage=ProviderUsage(),
                response_id="",
                resolved_model="",
            )
        choice = choices[0]
        message = _value(choice, "message")
        content = _value(message, "content", "") if message is not None else ""
        refusal = _value(message, "refusal", None) if message is not None else None
        finish_reason = _value(choice, "finish_reason", None)

        usage_obj = _value(response, "usage")
        reasoning_tokens = _value(
            _value(usage_obj, "completion_tokens_details"), "reasoning_tokens"
        )
        completion_tokens = _value(usage_obj, "completion_tokens")
        usage = ProviderUsage(
            input_tokens=_value(usage_obj, "prompt_tokens"),
            output_tokens=_value(usage_obj, "completion_tokens"),
            total_tokens=_value(usage_obj, "total_tokens"),
            reasoning_tokens=reasoning_tokens,
            visible_output_tokens=(
                max(0, completion_tokens - reasoning_tokens)
                if isinstance(completion_tokens, int)
                and isinstance(reasoning_tokens, int)
                else None
            ),
        )
        response_id = str(_value(response, "id", "") or "")
        resolved_model = str(_value(response, "model", "") or "")

        from ..private_diagnostics import capture_visible

        capture_visible(
            messages,
            kwargs.get("response_format"),
            content if isinstance(content, str) else None,
            finish_reason,
            response_id,
            resolved_model,
            api_key,
        )
        if (
            getattr(request, "provider", "") == "openrouter"
            and model.endswith(":free")
            and resolved_model != model
        ):
            raise ProviderError(
                "model_access_denied",
                validation_code="pinned_model_changed",
                usage=usage,
                response_id=response_id,
                resolved_model=resolved_model,
            )
        if refusal:
            raise ProviderError(
                "content_refusal",
                usage=usage,
                response_id=response_id,
                resolved_model=resolved_model,
            )
        if finish_reason == "length":
            raise ProviderError(
                "invalid_output",
                validation_code="provider_output_limit",
                usage=usage,
                response_id=response_id,
                resolved_model=resolved_model,
            )
        if finish_reason == "content_filter":
            raise ProviderError(
                "content_refusal",
                usage=usage,
                response_id=response_id,
                resolved_model=resolved_model,
            )

        if finish_reason != "stop":
            raise ProviderError(
                "invalid_output",
                validation_code="provider_incomplete",
                usage=usage,
                response_id=response_id,
                resolved_model=resolved_model,
            )
        output_text = (
            content
            if isinstance(content, str)
            else ("" if content is None else str(content))
        )

        # Distinct validation codes for fenced / multi-object output.
        stripped = output_text.strip() if isinstance(output_text, str) else ""
        if stripped.startswith("```"):
            raise ProviderError(
                "invalid_output",
                validation_code="provider_fenced_json",
                usage=usage,
                response_id=response_id,
                resolved_model=resolved_model,
            )
        if stripped:
            try:
                _obj, idx = json.JSONDecoder().raw_decode(stripped)
                if idx < len(stripped) and stripped[idx:].strip():
                    raise ProviderError(
                        "invalid_output",
                        validation_code="provider_multiple_json_objects",
                        usage=usage,
                        response_id=response_id,
                        resolved_model=resolved_model,
                    )
            except (ValueError, TypeError):
                pass

        parts = [output_text] if isinstance(output_text, str) else []
        return harness.parse_json_output(
            output_text,
            usage=usage,
            response_id=response_id,
            resolved_model=resolved_model,
            text_parts=parts,
        )
