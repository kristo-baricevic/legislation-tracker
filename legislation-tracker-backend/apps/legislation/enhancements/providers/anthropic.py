from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from apps.legislation.enhancements.citations import REPAIR_INSTRUCTIONS, REPAIR_SCHEMA
from apps.legislation.enhancements.schema import PROVIDER_OUTPUT_SCHEMA

from .base import CredentialCheck, ProviderCapabilities, ProviderError, ProviderResult, ProviderUsage
from . import harness


def _value(obj: Any, name: str, default=None):
    return harness.value(obj, name, default)


def _usage(response) -> ProviderUsage:
    usage = harness.usage_from_response(response)
    if usage.total_tokens is None and usage.input_tokens is not None and usage.output_tokens is not None:
        return ProviderUsage(usage.input_tokens, usage.output_tokens, usage.input_tokens + usage.output_tokens)
    return usage


def _mapped_error(error: Exception, *, timeout_seconds: int = 0) -> ProviderError:
    class_name = type(error).__name__.lower()
    if "timeout" in class_name or "connection" in class_name:
        return ProviderError(
            "outcome_unknown",
            outcome_unknown=True,
            retry_allowed=True,
            validation_code="provider_timeout" if "timeout" in class_name else "provider_connection_lost",
            validation_detail={"timeout_seconds": timeout_seconds},
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
    from anthropic import transform_schema

    def normalize(schema):
        # The SDK accepts union branches, but not JSON Schema's type-array shorthand.
        out = dict(schema)
        if isinstance(out.get("type"), list):
            variants = out.pop("type")
            return {"anyOf": [normalize({**out, "type": t}) for t in variants]}
        for key in ("properties", "$defs"):
            if key in out:
                out[key] = {k: normalize(v) for k, v in out[key].items()}
        for key in ("anyOf", "oneOf", "allOf"):
            if key in out:
                out[key] = [normalize(v) for v in out[key]]
        if isinstance(out.get("items"), dict):
            out["items"] = normalize(out["items"])
        return out

    return transform_schema(normalize(value))


class AnthropicEnhancementProvider:
    provider_name = "anthropic"
    capabilities = ProviderCapabilities(
        wire_api="anthropic_messages",
        schema_profile="anthropic_json_schema",
        reasoning_mapping={},
        privacy_flags={},
        validation_profile="anthropic_messages",
        usage_shape="anthropic_usage",
        refusal_completion_profile="anthropic_stop_reason",
        error_profile="anthropic_status_code",
        unsupported_schema_keywords=frozenset({"uniqueItems"}),
    )

    def __init__(self, *, client_factory: Callable[..., Any] | None = None):
        if client_factory is None:
            from anthropic import Anthropic

            client_factory = Anthropic
        self._client_factory = client_factory

    def _client(self, *, api_key: str, timeout_seconds: int):
        return self._client_factory(
            api_key=api_key,
            max_retries=0,
            timeout=timeout_seconds,
        )

    def validate_credential(
        self,
        *,
        api_key: str,
        requested_model: str,
        timeout_seconds: int,
    ) -> CredentialCheck:
        client = self._client(api_key=api_key, timeout_seconds=timeout_seconds)
        try:
            response = client.messages.create(
                model=requested_model,
                max_tokens=16,
                messages=[{"role": "user", "content": "Reply with OK."}],
            )
        except Exception as error:  # noqa: BLE001
            mapped = _mapped_error(error, timeout_seconds=timeout_seconds)
            if mapped.category in {"invalid_credentials", "model_access_denied"}:
                return CredentialCheck(valid=False, category=mapped.category)
            raise mapped from None
        stop_reason = _value(response, "stop_reason", None)
        if stop_reason not in (None, "end_turn", "max_tokens", "stop_sequence"):
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
        return result

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
            response = client.messages.create(
                model=request.requested_model,
                max_tokens=max_output_tokens,
                system=instructions,
                messages=[
                    {
                        "role": "user",
                        "content": json.dumps(
                            input_payload,
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=False,
                        ),
                    }
                ],
                output_config={
                    "format": {
                        "type": "json_schema",
                        "schema": _wire_schema(
                            schema,
                            unsupported_keywords=self.capabilities.unsupported_schema_keywords,
                        ),
                    }
                },
            )
        except ProviderError:
            raise
        except Exception as error:  # noqa: BLE001
            mapped = _mapped_error(error, timeout_seconds=timeout_seconds)
            mapped.validation_detail = mapped.validation_detail or {}
            mapped.validation_detail.setdefault("timeout_seconds", timeout_seconds)
            raise mapped from None

        usage = _usage(response)
        response_id = str(_value(response, "id", "") or "")
        resolved_model = str(_value(response, "model", "") or "")

        stop_reason = _value(response, "stop_reason", None)
        if stop_reason == "refusal":
            raise ProviderError(
                "content_refusal",
                usage=usage,
                response_id=response_id,
                resolved_model=resolved_model,
            )
        if stop_reason == "max_tokens":
            raise ProviderError(
                "invalid_output",
                validation_code="provider_output_limit",
                usage=usage,
                response_id=response_id,
                resolved_model=resolved_model,
            )

        if stop_reason not in {"end_turn", "stop_sequence"}:
            raise ProviderError("invalid_output", validation_code="provider_incomplete",
                                usage=usage, response_id=response_id, resolved_model=resolved_model)
        content = _value(response, "content", None)
        parts = []
        if content:
            for block in content:
                if _value(block, "type") == "text":
                    text = _value(block, "text", "")
                    if isinstance(text, str):
                        parts.append(text)
        if parts:
            output_text = "".join(parts)
        else:
            output_text = _value(response, "output_text", "")
            if not isinstance(output_text, str):
                output_text = "" if output_text is None else str(output_text)

        from ..private_diagnostics import capture_visible
        capture_visible([{"instructions": instructions, "input": input_payload}], schema,
                        output_text, stop_reason, response_id, resolved_model, api_key)
        return harness.parse_json_output(
            output_text,
            usage=usage,
            response_id=response_id,
            resolved_model=resolved_model,
            text_parts=parts if parts else None,
        )
