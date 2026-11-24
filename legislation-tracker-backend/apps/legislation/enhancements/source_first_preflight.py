from dataclasses import asdict

from django.conf import settings
from .model_selection import target as planning_target, reasoning_effort

from collections import Counter

from .provision_pipeline import BudgetExceeded, digest, encoded, _plan_built_graph
from .source_first_prompts import PROMPT_VERSION
from .source_first_schema import VERSION
from .source_graph import build_source_graph
from .types import EnhancementPreflight


def build_source_first_preflight(document, text, *, reuse_result=None):
    from .source_packet import PreflightUnavailable, _text_hash

    if not text.strip():
        raise PreflightUnavailable("Source text unavailable")
    from .xml_sections import stored_xml_sections
    graph = build_source_graph(str(document.pk), document.version_label, text,
                               xml_sections=stored_xml_sections(document, text))
    from .model_capabilities import resolve_capabilities
    limits = resolve_capabilities(*planning_target())
    output_limit = min(8000, settings.LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS, limits.output_tokens)
    try:
        plan = _plan_built_graph(
            graph,
            {
                "model": planning_target()[1],
                "reasoning_effort": reasoning_effort(),
                "output_tokens": output_limit,
                "per_call_input": min(
                    limits.context_tokens - output_limit,
                    settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES,
                    settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS,
                ),
            },
            reuse_result=reuse_result,
        )
    except BudgetExceeded as exc:
        raise PreflightUnavailable(
            "No executable analysis plan", reason=str(exc),
            coverage={"total_units": len(graph.units), "planned_units": 0,
                      "reused_units": len(exc.reused), "unresolved_units": len(exc.reasons),
                      "reasons": dict(Counter(exc.reasons.values()))},
        ) from None
    budget = {
        "maximum_calls": plan.maximum_calls,
        "maximum_input": plan.maximum_input,
        "maximum_output": plan.maximum_output,
    }
    identity = {
        "plan": plan.fingerprint,
        "provider": planning_target()[0],
        "reasoning_effort": reasoning_effort(),
        "output_limit": plan.output_tokens,
    }
    envelope = {"source_first_plan": identity, "budget": budget, "max_output_tokens": plan.output_tokens}
    return EnhancementPreflight(
        provider=planning_target()[0],
        requested_model=plan.model,
        reasoning_effort=reasoning_effort(),
        prompt_version=PROMPT_VERSION,
        output_schema_version=VERSION,
        source_packet_version=VERSION,
        source_fingerprint=graph.document_fingerprint,
        request_fingerprint=digest(identity),
        source_manifest={
            "document_id": document.pk,
            "document_content_hash": _text_hash(text),
            "document_version_label": document.version_label,
            "source_kind": "pinned_passages",
            "budget": budget,
            "coverage": {**graph.coverage, "total_units": len(graph.units),
                         "planned_units": sum(len(c.unit_ids) for c in plan.calls),
                         "reused_units": len(graph.units) - len(plan.unresolved_unit_ids)
                                         - sum(len(c.unit_ids) for c in plan.calls),
                         "unresolved_units": len(plan.unresolved_unit_ids),
                         "reasons": dict(Counter(dict(plan.unresolved_reasons).values()))},
            "unresolved_unit_ids": list(plan.unresolved_unit_ids),
            "truncated": False,
        },
        source_snapshot=[asdict(p) for p in graph.passages.values()],
        request_envelope=envelope,
        request_bytes=encoded(envelope),
        estimated_input_tokens=plan.maximum_input,
        truncated=False,
        analysis_plan=plan,
    )
