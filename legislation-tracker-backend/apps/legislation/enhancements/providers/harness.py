from __future__ import annotations

import copy
import json
from dataclasses import replace
from typing import Any

from django.conf import settings

from apps.legislation.enhancements.citations import REPAIR_INSTRUCTIONS, REPAIR_SCHEMA
from apps.legislation.enhancements.schema import PROVIDER_OUTPUT_SCHEMA

from .base import ProviderError, ProviderResult, ProviderUsage


def value(obj: Any, name: str, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def usage_from_response(response) -> ProviderUsage:
    usage = value(response, "usage")
    if usage is None:
        return ProviderUsage()
    output = value(usage, "output_tokens")
    reasoning = value(value(usage, "output_tokens_details"), "reasoning_tokens")
    return ProviderUsage(
        input_tokens=value(usage, "input_tokens"),
        output_tokens=output,
        reasoning_tokens=reasoning,
        visible_output_tokens=(
            max(0, output - reasoning)
            if output is not None and reasoning is not None
            else None
        ),
        total_tokens=value(usage, "total_tokens"),
    )


def contains_refusal(response) -> bool:
    for output_item in value(response, "output", []) or []:
        if value(output_item, "type") != "message":
            continue
        for content in value(output_item, "content", []) or []:
            if value(content, "type") == "refusal":
                return True
    return False


def wire_schema(value_, *, unsupported_keywords=()):
    """Preserve local constraints while omitting provider-unsupported keywords."""
    unsupported = frozenset(unsupported_keywords)
    if isinstance(value_, dict):
        return {
            key: wire_schema(item, unsupported_keywords=unsupported)
            for key, item in value_.items()
            if key not in unsupported
        }
    if isinstance(value_, list):
        return [wire_schema(item, unsupported_keywords=unsupported) for item in value_]
    return value_


def select_bill_schema(request, input_payload) -> Any:
    schema = PROVIDER_OUTPUT_SCHEMA
    envelope = getattr(request, "request_envelope", None) or {}
    if envelope.get("output_schema_version") == "reader-dependency-1":
        from ..reader_citations import READER_PROMPT_VERSION

        # Reconciliation has its own page/check/item contract. Falling back to
        # the legacy overview schema makes a conforming provider response fail
        # dependency validation, even when the preflight request fits.
        if (
            envelope.get("prompt_version") != READER_PROMPT_VERSION
            or not isinstance(envelope.get("dependency_review"), dict)
            or not envelope["dependency_review"]
            or not isinstance(envelope.get("output_schema"), dict)
            or not envelope["output_schema"]
        ):
            raise ProviderError(
                "invalid_output",
                validation_code="source_snapshot_invalid",
                usage=ProviderUsage(0, 0, 0),
            )
        schema = envelope["output_schema"]
    elif envelope.get("output_schema_version") == "1.4":
        from ..reader_citations import READER_ID_SCHEMA, READER_PROMPT_VERSION
        from ..reader_targets import READER_SCHEMA

        if envelope.get("prompt_version") == READER_PROMPT_VERSION:
            schema = envelope.get("output_schema", READER_ID_SCHEMA)
        else:
            schema = READER_SCHEMA
    elif envelope.get("coverage_candidate_version") == "2":
        from ..coverage_contract import response_schema

        schema = response_schema(input_payload["source_packet"]["coverage_checklist"])
    elif envelope.get("coverage_candidate_version") == "3":
        from ..coverage_contract import provision_schema

        schema = provision_schema(input_payload["source_packet"]["coverage_checklist"])
    return staged_wire_schema(schema)


def staged_wire_schema(schema):
    if "condition" in schema.get("$defs", {}) and "factual_records" in schema.get(
        "properties", {}
    ):
        schema = copy.deepcopy(schema)
        del schema["$defs"]["condition"]
        if not schema["$defs"]:
            del schema["$defs"]
        fields = schema["properties"]["factual_records"]["items"]["properties"][
            "claims"
        ]["items"]["properties"]
        tree = 'A leaf is {"operator":"leaf","text":"...","evidence_ids":["source_ref:quote_id"]}. A group has operator all or any and children containing nodes.'
        fields["conditions"] = {
            "type": "string",
            "description": "JSON-encoded condition node or null. " + tree,
        }
        fields["exceptions"] = {
            "type": "string",
            "description": "JSON-encoded array of exception nodes. Use [] for none. "
            + tree,
        }
    return schema


def decode_bill_result(result, schema):
    if "factual_records" not in schema.get("properties", {}):
        return result
    try:
        for record in result.output["factual_records"]:
            for claim in record["claims"]:
                for field in ("conditions", "exceptions"):
                    claim[field] = json.loads(claim[field])
    except (KeyError, ValueError, TypeError, RecursionError) as error:
        raise ProviderError(
            "invalid_output",
            validation_code="reader_target_invalid",
            usage=result.usage,
            response_id=result.response_id,
            resolved_model=result.resolved_model,
        ) from error
    return result


def resolve_max_output_tokens(request, schema_name: str) -> int:
    envelope = getattr(request, "request_envelope", None) or {}
    if getattr(request, "output_schema_version", None) == "1.4":
        return envelope["max_output_tokens"]
    if str(schema_name).startswith("source_first_"):
        return min(
            envelope.get("max_output_tokens", 8000),
            8000,
            settings.LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS,
        )
    return min(
        envelope.get("max_output_tokens", settings.LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS),
        settings.LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS,
    )


def ensure_request_fits(envelope: dict, *, max_bytes: int) -> None:
    size = len(json.dumps(envelope, ensure_ascii=False).encode())
    if size > max_bytes:
        raise ProviderError("request_too_large", usage=ProviderUsage(0, 0, 0))


def ensure_citation_repair_fits(payload, request=None) -> None:
    envelope = dict(
        input=payload, instructions=REPAIR_INSTRUCTIONS, schema=REPAIR_SCHEMA
    )
    max_bytes = min(
        settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES,
        settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS,
    )
    if request is not None:
        from ..model_capabilities import resolve_capabilities

        cap = resolve_capabilities(
            getattr(request, "provider", ""), request.requested_model
        )
        max_bytes = min(
            max_bytes,
            cap.context_tokens
            - resolve_max_output_tokens(request, "citation_repair")
            - 1024,
        )
    ensure_request_fits(envelope, max_bytes=max_bytes)


def prepare_source_first(stage: str, source_first_payload) -> tuple[str, Any]:
    from ..source_first_prompts import PROVISION_INSTRUCTIONS, SYNOPSIS_INSTRUCTIONS
    from ..source_first_prompts import REPAIR_INSTRUCTIONS as REPAIR
    from ..source_first_transport import prepare_transport

    instructions = {
        "generation": PROVISION_INSTRUCTIONS,
        "repair": REPAIR,
        "synopsis": SYNOPSIS_INSTRUCTIONS,
    }[stage]
    transport = prepare_transport(stage, source_first_payload)
    return instructions, transport


def ensure_source_first_fits(instructions, payload, schema) -> None:
    envelope = {"input": payload, "instructions": instructions, "schema": schema}
    max_bytes = min(
        120000,
        100000,
        settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES,
        settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS,
    )
    ensure_request_fits(envelope, max_bytes=max_bytes)


def decode_source_first_output(transport, result: ProviderResult) -> ProviderResult:
    from jsonschema import ValidationError

    try:
        return replace(result, output=transport.decode(result.output))
    except (ValidationError, KeyError, TypeError) as error:
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


def apply_derived_source_refs(result: ProviderResult) -> ProviderResult:
    from ..schema import add_derived_source_refs

    return replace(result, output=add_derived_source_refs(result.output))


def parse_json_output(
    output_text,
    *,
    usage: ProviderUsage | None = None,
    response_id: str = "",
    resolved_model: str = "",
    text_parts: list[str] | None = None,
) -> ProviderResult:
    usage = usage or ProviderUsage()
    try:
        output = json.loads(output_text)
    except (TypeError, ValueError) as error:
        from ..diagnostics import json_parse_diagnostic

        parser = json_parse_diagnostic(error, output_text)
        if text_parts is not None:
            parser.update(
                output_text_parts=len(text_parts),
                output_text_part_length=sum(map(len, text_parts)),
            )
        raise ProviderError(
            "invalid_output",
            validation_code="provider_invalid_json",
            validation_detail={"parser": parser},
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
