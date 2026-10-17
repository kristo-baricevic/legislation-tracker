from dataclasses import asdict

from django.conf import settings

from .provision_pipeline import BudgetExceeded, digest, encoded, plan_analysis
from .source_first_prompts import PROMPT_VERSION
from .source_first_schema import VERSION
from .source_graph import build_source_graph
from .types import EnhancementPreflight


def build_source_first_preflight(document, text, *, reuse_result=None):
    from .source_packet import PreflightUnavailable

    if not text.strip():
        raise PreflightUnavailable("Source text unavailable")
    graph = build_source_graph(str(document.pk), document.version_label, text)
    try:
        plan = plan_analysis(
            graph,
            {
                "model": settings.LLM_ENHANCEMENT_MODEL,
                "reasoning_effort": settings.LLM_ENHANCEMENT_REASONING_EFFORT,
                "output_tokens": settings.LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS,
                "per_call_input": min(
                    settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES,
                    settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS,
                ),
            },
            reuse_result=reuse_result,
        )
    except BudgetExceeded:
        raise PreflightUnavailable(
            "Analysis exceeds confirmed limits", reason="budget_exceeded"
        ) from None
    budget = {
        "maximum_calls": plan.maximum_calls,
        "maximum_input": plan.maximum_input,
        "maximum_output": plan.maximum_output,
    }
    identity = {
        "plan": plan.fingerprint,
        "provider": settings.LLM_ENHANCEMENT_PROVIDER,
        "reasoning_effort": settings.LLM_ENHANCEMENT_REASONING_EFFORT,
        "output_limit": min(8000, settings.LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS),
    }
    envelope = {"source_first_plan": identity, "budget": budget}
    return EnhancementPreflight(
        provider=settings.LLM_ENHANCEMENT_PROVIDER,
        requested_model=plan.model,
        reasoning_effort=settings.LLM_ENHANCEMENT_REASONING_EFFORT,
        prompt_version=PROMPT_VERSION,
        output_schema_version=VERSION,
        source_packet_version=VERSION,
        source_fingerprint=graph.document_fingerprint,
        request_fingerprint=digest(identity),
        source_manifest={
            "document_id": document.pk,
            "document_version_label": document.version_label,
            "source_kind": "pinned_passages",
            "budget": budget,
            "coverage": graph.coverage,
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
