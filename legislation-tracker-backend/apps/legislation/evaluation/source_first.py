"""Offline replay and independent review packets for the production orchestrator."""

import copy
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from apps.legislation.enhancements.provision_pipeline import (
    BudgetExceeded,
    digest,
    plan_analysis,
    run_analysis,
)
from apps.legislation.enhancements.source_graph import build_source_graph

from .whole_bill import assess, load_cases


def evaluation_limits():
    from django.conf import settings

    return {
        "model": settings.LLM_ENHANCEMENT_MODEL,
        "reasoning_effort": settings.LLM_ENHANCEMENT_REASONING_EFFORT,
        "output_tokens": settings.LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS,
        "per_call_input": min(
            settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES,
            settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS,
        ),
    }


def execute_recorded(
    plan, invoke, path, *, generation_recording=None, use_completed_output=False
):
    """Reserve one immutable run identity and checkpoint before every paid call.

    Never resumes an existing path: after a crash its last dispatch could have
    charged. A new run requires new explicit confirmation and a new artifact.
    """
    from apps.legislation.enhancements.providers.base import (
        ProviderError,
        ProviderUsage,
    )

    path = Path(path)
    from apps.legislation.enhancements.source_first_schema import (
        VERSION,
        hydrate_evidence,
    )

    # Revalidate saved generation through the current orchestrator. This is an
    # explicit retry experiment, not fresh generation or a historical replay.
    # Fail before dispatch when provenance or assignment is incomplete.
    recorded_rows = {}
    if use_completed_output and generation_recording is None:
        raise ValueError("missing_recorded_output")
    if generation_recording is not None:
        if (
            generation_recording.get("document_fingerprint")
            != plan.graph.document_fingerprint
        ):
            raise ValueError("artifact_identity")
        for call in generation_recording.get("calls", []):
            if call["stage"] != "generation" or "response" not in call:
                continue
            if call.get("response_sha256") != digest(call["response"]):
                raise ValueError("recorded_call_identity")
            for row in call["response"].get("provisions", []):
                if row["unit_id"] in recorded_rows:
                    raise ValueError("recorded_call_identity")
                recorded_rows[row["unit_id"]] = copy.deepcopy(row)
        if use_completed_output:
            if generation_recording.get("status") != "completed":
                raise ValueError("incomplete_recorded_output")
            recorded_rows = {}
            for row in (
                generation_recording.get("result", {})
                .get("output", {})
                .get("provisions", [])
            ):
                if row["status"] != "explained":
                    continue
                uid = row["unit_id"]
                if uid in recorded_rows:
                    raise ValueError("recorded_call_identity")
                recorded_rows[uid] = {
                    k: copy.deepcopy(v)
                    for k, v in row.items()
                    if k not in {"id", "evidence", "source_limitations"}
                }
        if any(
            uid not in recorded_rows for call in plan.calls for uid in call.unit_ids
        ):
            raise ValueError("missing_recorded_call")

    artifact = {
        "plan_fingerprint": plan.fingerprint,
        "model": plan.model,
        "limits": {
            "model": plan.model,
            "reasoning_effort": plan.reasoning_effort,
            "output_tokens": plan.output_tokens,
            "per_call_input": plan.per_call_input,
        },
        "document_fingerprint": plan.graph.document_fingerprint,
        "mode": "saved_output_live_retry"
        if use_completed_output
        else "saved_generation_live_retry"
        if generation_recording is not None
        else "fresh_generation",
        "generation_recording_sha256": digest(generation_recording)
        if generation_recording is not None
        else None,
        "status": "running",
        "maximum_calls": plan.maximum_calls,
        "maximum_input": plan.maximum_input,
        "maximum_output": plan.maximum_output,
        "network_calls": 0,
        "calls": [],
        "reuse_result": {
            "schema_version": VERSION,
            "document_fingerprint": plan.graph.document_fingerprint,
            "provisions": [
                hydrate_evidence(row, plan.graph)
                for row in json.loads(plan.reused_json)
            ],
        }
        if json.loads(plan.reused_json)
        else None,
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(artifact, output)
        output.flush()
        os.fsync(output.fileno())

    def save():
        fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as output:
                json.dump(artifact, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def checkpoint(state, index, call, response):
        if state == "dispatching":
            recorded = generation_recording is not None and call.stage == "generation"
            artifact["calls"].append(
                {
                    "request_fingerprint": call.request_fingerprint,
                    "stage": call.stage,
                    "unit_ids": list(call.unit_ids),
                    "status": state,
                    "origin": (
                        "recorded_output"
                        if use_completed_output
                        else "recorded_generation"
                    )
                    if recorded
                    else "provider",
                }
            )
            artifact["network_calls"] += int(not recorded)
        else:
            row = artifact["calls"][index]
            row.update(
                status=state, usage=asdict(getattr(response, "usage", ProviderUsage()))
            )
            if isinstance(response, ProviderError):
                row["error"] = {
                    "category": response.category,
                    "validation_code": response.validation_code,
                    "validation_detail": response.validation_detail,
                    "outcome_unknown": response.outcome_unknown,
                }
            else:
                raw = response.output if hasattr(response, "output") else response
                row.update(
                    response=raw,
                    response_sha256=digest(raw),
                    response_id=getattr(response, "response_id", ""),
                    resolved_model=getattr(response, "resolved_model", ""),
                )
        save()

    def dispatch(call):
        if generation_recording is not None and call.stage == "generation":
            return {
                "provisions": [
                    copy.deepcopy(recorded_rows[uid]) for uid in call.unit_ids
                ]
            }
        return invoke(call)

    try:
        result = run_analysis(plan, dispatch, checkpoint)
        artifact.update(status="completed", result=asdict(result))
        return result
    except Exception:
        # Do not serialize arbitrary provider/transport exception messages.
        artifact["status"] = "failed"
        raise
    finally:
        save()


def preflight_benchmarks():
    rows = []
    for case in load_cases():
        graph = build_source_graph(case["id"], case["id"], case["text"])
        row = {
            "id": case["id"],
            "source_sha256": case["text_sha256"],
            "answer_sha256": case["answer_sha256"],
            "graph_fingerprint": graph.document_fingerprint,
            "units": len(graph.units),
        }
        try:
            plan = plan_analysis(graph, evaluation_limits())
        except BudgetExceeded:
            row["status"] = "budget_exceeded"
        else:
            row.update(
                status="ready",
                maximum_calls=plan.maximum_calls,
                maximum_input=plan.maximum_input,
                maximum_output=plan.maximum_output,
                unresolved_units=len(plan.unresolved_unit_ids),
                plan_fingerprint=plan.fingerprint,
            )
        rows.append(row)
    return {
        "cases": rows,
        "network_calls": 0,
        "release_gate": "blocked",
        "reason": "fresh_generation_and_independent_semantic_review_required",
    }


def replay(plan, artifact):
    """No provider dependency or network fallback. Raw responses are never edited."""
    identity = {
        "plan_fingerprint": plan.fingerprint,
        "model": plan.model,
        "document_fingerprint": plan.graph.document_fingerprint,
    }
    if any(artifact.get(k) != v for k, v in identity.items()):
        raise ValueError("artifact_identity")
    calls = iter(artifact["calls"])

    def invoke(call):
        try:
            recorded = next(calls)
        except StopIteration:
            raise ValueError("missing_recorded_call") from None
        if recorded["request_fingerprint"] != call.request_fingerprint:
            raise ValueError("recorded_call_identity")
        if recorded.get("error"):
            from apps.legislation.enhancements.providers.base import ProviderError

            raise ProviderError(**recorded["error"])
        if recorded.get("response_sha256") != digest(recorded.get("response")):
            raise ValueError("recorded_call_identity")
        return recorded["response"]

    result = run_analysis(plan, invoke, lambda *args: None)
    if next(calls, None) is not None:
        raise ValueError("unused_recorded_call")
    return {
        "mode": "historical_replay",
        "network_calls": 0,
        "raw_artifact_sha256": digest(artifact),
        "result": asdict(result),
        "release_gate": "blocked",
        "semantic_review_status": "unreviewed",
    }


def review_packet(case, result):
    items = [
        {**row, "text": row["summary"], "evidence_valid": bool(row["evidence"])}
        for row in result.output["provisions"]
        if row["status"] == "explained"
    ]
    report = assess(
        case,
        items,
        pipeline="source-first",
        failures=[
            f"unresolved:{row['unit_id']}:{row.get('unresolved_reason', '')}"
            for row in result.output["provisions"]
            if row["status"] != "explained"
        ],
    )
    report.update(
        artifact_sha256=digest(result.output),
        source_sha256=case["text_sha256"],
        answer_sha256=case["answer_sha256"],
        reviewer=None,
        source_accounting=result.output["coverage"].get("source_items", []),
        unresolved_unit_ids=result.output["coverage"]["unresolved_unit_ids"],
        repair_history=list(result.findings),
        context_limited_unit_ids=result.output["coverage"].get(
            "context_limited_unit_ids", []
        ),
    )
    statements = [text for row in items for text in [row["summary"], *row["details"]]]
    report["dimensions"]["readability"].update(
        statement_count=len(statements),
        max_statement_words=max((len(text.split()) for text in statements), default=0),
    )
    return report
