from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from django.conf import settings

from apps.legislation.enhancements.citations import REPAIR_INSTRUCTIONS, REPAIR_SCHEMA
from apps.legislation.enhancements.schema import PROVIDER_OUTPUT_SCHEMA

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
        return ProviderError("provider_request_rejected", retry_allowed=True)
    return ProviderError("provider_unavailable", retry_allowed=True)


def _wire_schema(value):
    """Preserve local constraints while omitting unsupported API keywords."""
    if isinstance(value, dict):
        return {
            key: _wire_schema(item)
            for key, item in value.items()
            if key != "uniqueItems"
        }
    if isinstance(value, list):
        return [_wire_schema(item) for item in value]
    return value


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
        schema = PROVIDER_OUTPUT_SCHEMA
        if request.request_envelope.get("coverage_candidate_version") == "2":
            from ..coverage_contract import response_schema

            schema = response_schema(
                input_payload["source_packet"]["coverage_checklist"]
            )
        elif request.request_envelope.get("coverage_candidate_version") == "3":
            from ..coverage_contract import provision_schema

            schema = provision_schema(
                input_payload["source_packet"]["coverage_checklist"]
            )
        return self._generate(
            api_key=api_key,
            request=request,
            timeout_seconds=timeout_seconds,
            input_payload=input_payload,
            instructions=request.request_envelope["instructions"],
            schema=schema,
            schema_name="bill_enhancement_v1_1",
        )

    def repair_citations(self, *, api_key, request, payload, timeout_seconds):
        envelope = dict(
            input=payload, instructions=REPAIR_INSTRUCTIONS, schema=REPAIR_SCHEMA
        )
        size = len(json.dumps(envelope, ensure_ascii=False).encode())
        if size > min(
            settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES,
            settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS,
        ):
            raise ProviderError("request_too_large", usage=ProviderUsage(0, 0, 0))
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
        from jsonschema import ValidationError

        from ..source_first_prompts import PROVISION_INSTRUCTIONS, SYNOPSIS_INSTRUCTIONS
        from ..source_first_prompts import REPAIR_INSTRUCTIONS as REPAIR
        from ..source_first_transport import prepare_transport

        instructions = {
            "generation": PROVISION_INSTRUCTIONS,
            "repair": REPAIR,
            "synopsis": SYNOPSIS_INSTRUCTIONS,
        }[stage]
        transport = prepare_transport(
            stage, request.request_envelope["source_first_payload"]
        )
        payload, schema = transport.payload, transport.schema
        size = len(
            json.dumps(
                {"input": payload, "instructions": instructions, "schema": schema},
                ensure_ascii=False,
            ).encode()
        )
        if size > min(
            120000,
            100000,
            settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES,
            settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS,
        ):
            raise ProviderError("request_too_large", usage=ProviderUsage(0, 0, 0))
        result = self._generate(
            api_key=api_key,
            request=request,
            timeout_seconds=timeout_seconds,
            input_payload=payload,
            instructions=instructions,
            schema=schema,
            schema_name=f"source_first_{stage}",
        )
        try:
            return replace(result, output=transport.decode(result.output))
        except (ValidationError, KeyError, TypeError) as error:
            # Only server-owned schema keys and validator names; never persist
            # arbitrary exception messages or provider-supplied field names.
            fields = {
                "provisions",
                "unit_id",
                "status",
                "summary",
                "details",
                "claims",
                "unresolved_reason",
                "actor",
                "action",
                "modality",
                "money",
                "conditions",
                "exceptions",
                "evidence_ids",
                "amount",
                "currency",
                "measure",
                "comparator",
                "purpose",
                "period",
                "base",
                "operator",
                "children",
                "text",
                "condition_id",
                "source_item_ids",
                "explanations",
                "unresolved_items",
                "item_id",
                "reason",
                "explanation_ids",
                "financial_patches",
                "claim_index",
            }
            path = "/".join(
                str(part) if type(part) is int or part in fields else "unknown"
                for part in getattr(error, "absolute_path", ())
            )
            validator = getattr(error, "validator", None)
            rule = (
                validator
                if isinstance(validator, str)
                else (
                    str(error)
                    if str(error)
                    in {
                        "unrelated_source_item",
                        "source_item_assignment",
                        "condition_depth",
                        "invalid_evidence_ids",
                    }
                    else "decode"
                )
            )
            raise ProviderError(
                "invalid_output",
                validation_code="source_first_wire_schema",
                validation_detail={"rule": rule, "path": path[:256]},
                usage=result.usage,
                response_id=result.response_id,
                resolved_model=result.resolved_model,
            ) from None

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
                max_output_tokens=min(8000, settings.LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS)
                if schema_name.startswith("source_first_")
                else settings.LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS,
                reasoning={"effort": request.reasoning_effort},
                text={
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "schema": _wire_schema(schema),
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
                validation_code="provider_output_limit"
                if _value(_value(response, "incomplete_details"), "reason")
                == "max_output_tokens"
                else "provider_incomplete",
                usage=usage,
                response_id=response_id,
                resolved_model=resolved_model,
            )
        output_text = _value(response, "output_text", "")
        try:
            output = json.loads(output_text)
        except (TypeError, ValueError):
            raise ProviderError(
                "invalid_output",
                validation_code="provider_invalid_json",
                usage=usage,
                response_id=response_id,
                resolved_model=resolved_model,
            ) from None
        if not isinstance(output, dict):
            raise ProviderError(
                "invalid_output",
                validation_code="provider_output_not_object",
                usage=usage,
                response_id=response_id,
                resolved_model=resolved_model,
            )
        return ProviderResult(
            output=output,
            usage=usage,
            response_id=response_id,
            resolved_model=resolved_model,
        )
