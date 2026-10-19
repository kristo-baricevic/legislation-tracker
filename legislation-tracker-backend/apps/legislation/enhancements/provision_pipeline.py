"""Bounded source-first generation, with an injected durable dispatch boundary."""

import copy
import hashlib
import json
from dataclasses import asdict, dataclass

from jsonschema import Draft202012Validator, ValidationError

from .claim_repair import merge_repair, narrow_assignment, repair_items
from .providers.base import ProviderError
from .provision_validation import (
    required_conditions,
    validate_combined,
    validate_provision,
)
from .source_checklist import source_checklist
from .source_first_prompts import (
    PROMPT_VERSION,
    PROVISION_INSTRUCTIONS,
    REPAIR_INSTRUCTIONS,
    SYNOPSIS_INSTRUCTIONS,
)
from .source_first_schema import (
    SYNOPSIS_SCHEMA,
    VERSION,
    hydrate_evidence,
)
from .source_first_transport import prepare_transport
from .source_graph import audit_graph, has_explainable_text


class BudgetExceeded(ValueError):
    pass


def encoded(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


@dataclass(frozen=True)
class PlannedCall:
    stage: str
    unit_ids: tuple[str, ...]
    payload_json: str
    request_fingerprint: str
    estimated_input: int

    @property
    def payload(self):
        return json.loads(self.payload_json)


@dataclass(frozen=True)
class AnalysisPlan:
    graph: object
    calls: tuple[PlannedCall, ...]
    fingerprint: str
    model: str
    maximum_calls: int
    maximum_input: int
    maximum_output: int
    per_call_input: int
    unresolved_unit_ids: tuple[str, ...]
    reused_json: str = "[]"
    reasoning_effort: str = "none"
    output_tokens: int = 8000


@dataclass(frozen=True)
class AnalysisResult:
    output: dict
    completeness: str
    call_count: int
    findings: tuple[dict, ...]


def _call(stage, ids, payload, model, reasoning_effort="none", output_tokens=8000):
    transport = prepare_transport(stage, payload)
    instructions = {
        "generation": PROVISION_INSTRUCTIONS,
        "repair": REPAIR_INSTRUCTIONS,
        "synopsis": SYNOPSIS_INSTRUCTIONS,
    }[stage]
    envelope = {
        "input": transport.payload,
        "instructions": instructions,
        "schema": transport.schema,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "output_tokens": output_tokens,
        "prompt_version": PROMPT_VERSION,
        "output_schema": VERSION,
        "canonical_payload_fingerprint": digest(payload),
    }
    # Match provider's non-compact serialization too; a conservative bound.
    size = len(json.dumps(envelope, ensure_ascii=False).encode())
    return PlannedCall(
        stage, tuple(ids), encoded(payload).decode(), digest(envelope), size
    )


def _payload(graph, ids):
    units = [u for u in graph.units if u.id in ids]
    passage_ids = {p for u in units for p in u.own_passage_ids + u.context_passage_ids}
    return {
        "document_fingerprint": graph.document_fingerprint,
        "units": [
            {
                **asdict(u),
                "required_conditions": required_conditions(u, graph),
                "source_checklist": [
                    {**item, "text": graph.source_text[item["start"] : item["end"]]}
                    for item in source_checklist(u, graph)
                ],
            }
            for u in units
        ],
        "passages": {
            pid: asdict(p) for pid, p in graph.passages.items() if pid in passage_ids
        },
    }


def plan_analysis(graph, limits=None, reuse_result=None):
    limits = limits or {}
    if audit_graph(graph, graph.source_text):
        raise ValueError("source_identity")
    model = limits.get("model", "gpt-6-luna")
    reasoning_effort = limits.get("reasoning_effort", "none")
    output_tokens = min(8000, limits.get("output_tokens", 8000))
    per_call = min(100000, 120000, limits.get("per_call_input", 100000))
    max_generation = min(4, limits.get("generation_calls", 4))
    batch_size = min(8, limits.get("batch_size", 8))
    if per_call <= 0 or output_tokens <= 0 or max_generation < 1 or batch_size < 1:
        raise BudgetExceeded("budget_exceeded")
    reused = []
    if reuse_result:
        if (
            reuse_result.get("document_fingerprint") != graph.document_fingerprint
            or reuse_result.get("schema_version") != VERSION
        ):
            raise ValueError("source_identity")
        for row in reuse_result["provisions"]:
            if row["status"] != "explained":
                continue
            clean = {
                k: v
                for k, v in row.items()
                if k not in {"id", "evidence", "source_limitations"}
            }
            unit = next((u for u in graph.units if u.id == row["unit_id"]), None)
            if unit is None or validate_provision(
                clean, unit, graph, require_coverage=True
            ):
                raise ValueError("reused_output_invalid")
            if hydrate_evidence(clean, graph) != row:
                raise ValueError("reused_evidence_invalid")
            reused.append(clean)
    reused_ids = {r["unit_id"] for r in reused}
    calls, batches, unresolved = [], [], []
    # Planning estimate reserves room for mappings plus explanatory prose.
    # The provider's hard output cap still applies; this is not a guarantee.
    item_counts = {u.id: len(source_checklist(u, graph)) for u in graph.units}

    def output_fits(ids):
        return sum(item_counts[uid] for uid in ids) * 80 <= output_tokens

    def make(ids):
        return _call(
            "generation",
            ids,
            _payload(graph, ids),
            model,
            reasoning_effort,
            output_tokens,
        )

    # Place the largest complete units first, then fill remaining capacity.
    singles = {
        unit.id: make([unit.id]) for unit in graph.units if unit.id not in reused_ids
    }
    for unit in sorted(
        graph.units,
        key=lambda unit: singles[unit.id].estimated_input if unit.id in singles else 0,
        reverse=True,
    ):
        if unit.id in reused_ids:
            continue
        if (
            not has_explainable_text(unit, graph)
            or make([unit.id]).estimated_input > per_call
            or not output_fits([unit.id])
        ):
            unresolved.append(unit.id)
            continue
        # Reuse spare capacity in earlier batches. Each unit carries its own
        # complete context, and final presentation remains in source order.
        # Consecutive-only packing can needlessly exceed the paid-call ceiling.
        for batch in batches:
            candidate = batch + [unit.id]
            if (
                len(candidate) <= batch_size
                and output_fits(candidate)
                and make(candidate).estimated_input <= per_call
            ):
                batch.append(unit.id)
                break
        else:
            batches.append([unit.id])
    calls = [make(batch) for batch in batches]
    if len(calls) > max_generation:
        raise BudgetExceeded("budget_exceeded")
    maximum_calls = len(calls) + (2 if calls else 0)
    maximum_input = sum(c.estimated_input for c in calls) + (
        2 * per_call if calls else 0
    )
    maximum_output = maximum_calls * output_tokens
    if maximum_input > limits.get("max_input", 600000) or maximum_output > limits.get(
        "max_output", 48000
    ):
        raise BudgetExceeded("budget_exceeded")
    identity = {
        "graph": graph.document_fingerprint,
        "calls": [asdict(c) for c in calls],
        "unresolved": unresolved,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "output_tokens": output_tokens,
        "maximum_input": maximum_input,
        "maximum_output": maximum_output,
        "per_call": per_call,
        "reused": reused,
    }
    return AnalysisPlan(
        graph,
        tuple(calls),
        digest(identity),
        model,
        maximum_calls,
        maximum_input,
        maximum_output,
        per_call,
        tuple(unresolved),
        encoded(reused).decode(),
        reasoning_effort,
        output_tokens,
    )


def run_analysis(plan, invoke, checkpoint):
    graph = plan.graph
    if audit_graph(graph, graph.source_text):
        raise ValueError("source_identity")
    units = {u.id: u for u in graph.units}
    accepted = {row["unit_id"]: row for row in json.loads(plan.reused_json)}
    failed, findings = {}, []
    candidates, targeted = {}, {}
    preserved_summaries = {}
    financial_candidates = {}
    financial_indexes = {}
    call_count = 0

    def dispatch(call):
        nonlocal call_count
        if (
            call.estimated_input > plan.per_call_input
            or call_count >= plan.maximum_calls
        ):
            raise BudgetExceeded("budget_exceeded")
        index = call_count
        checkpoint("dispatching", index, call, None)
        call_count += 1
        try:
            response = invoke(call)
        except ProviderError as error:
            checkpoint(
                "outcome_unknown" if error.outcome_unknown else "failed",
                index,
                call,
                error,
            )
            if error.outcome_unknown or error.category != "invalid_output":
                raise
            return None
        checkpoint("succeeded", index, call, response)
        return response.output if hasattr(response, "output") else response

    def assess(output, ids, *, repairing=False):
        from .source_first_schema import _evidence_ids

        money_patched = False
        if (
            repairing
            and isinstance(output, dict)
            and set(output) == {"financial_patches"}
        ):
            try:
                patched = {uid: copy.deepcopy(financial_candidates[uid]) for uid in ids}
                seen = set()
                for patch in output["financial_patches"]:
                    uid, index = patch["unit_id"], patch["claim_index"]
                    if (
                        uid not in patched
                        or type(index) is not int
                        or index not in financial_indexes[uid]
                        or (uid, index) in seen
                    ):
                        raise ValueError("financial_patch_assignment")
                    if any(
                        entry not in patch["money"]
                        for entry in patched[uid]["claims"][index]["money"]
                    ):
                        raise ValueError("financial_patch_erases_existing")
                    seen.add((uid, index))
                    patched[uid]["claims"][index]["money"] = copy.deepcopy(
                        patch["money"]
                    )
                output = {"provisions": list(patched.values())}
                money_patched = True
            except (KeyError, TypeError, ValueError):
                return {}, {uid: "financial_patch_assignment" for uid in ids}

        if (
            not isinstance(output, dict)
            or set(output) != {"provisions"}
            or not isinstance(output["provisions"], list)
        ):
            return {}, {uid: "invalid_structure" for uid in ids}
        rows = output["provisions"]
        if any(
            not isinstance(row, dict) or not isinstance(row.get("unit_id"), str)
            for row in rows
        ):
            return {}, {uid: "invalid_structure" for uid in ids}
        actual = [row["unit_id"] for row in rows]
        if len(actual) != len(set(actual)) or not set(actual) <= set(ids):
            # Never choose between duplicates or let a repair overwrite an
            # already accepted assignment.
            return {}, {uid: "invalid_assignment" for uid in ids}
        try:
            evidence_ids = _evidence_ids(output)
        except (ValidationError, TypeError):
            return {}, {uid: "invalid_structure" for uid in ids}
        if any(p not in graph.passages for p in evidence_ids):
            raise ValueError("source_identity")
        good, bad = {}, {uid: "missing_assignment" for uid in ids if uid not in actual}
        for row in rows:
            uid = row["unit_id"]
            if (
                repairing
                and uid in preserved_summaries
                and row.get("status") == "explained"
            ):
                row = {**row, "summary": preserved_summaries[uid]}
            if repairing and uid in targeted and not money_patched:
                try:
                    row = merge_repair(candidates[uid], row, targeted[uid], graph)
                except (ValidationError, KeyError, TypeError, IndexError):
                    bad[uid] = "repair_assignment"
                    continue
            checks = validate_provision(
                row, units[row["unit_id"]], graph, require_coverage=True
            )
            findings.extend(asdict(f) for f in checks)
            if any(f.outcome == "fatal" for f in checks):
                raise ValueError("source_identity")
            if checks:
                bad[row["unit_id"]] = checks[0].code
                if not repairing:
                    if all(
                        f.code
                        in {
                            "source_item_money_missing",
                            "source_item_amount_missing",
                            "financial_coverage_unverified",
                        }
                        for f in checks
                    ):
                        financial_candidates[uid] = copy.deepcopy(row)
                        missing_items = [
                            row["coverage_items"][int(f.path.split("/")[1])]
                            for f in checks
                            if f.code
                            in {
                                "source_item_money_missing",
                                "source_item_amount_missing",
                            }
                        ]
                        financial_indexes[uid] = (
                            {i for item in missing_items for i in item["claim_indexes"]}
                            if missing_items
                            else set(range(len(row["claims"])))
                        )
                    if not any(f.path in {"summary", "explanations/0"} for f in checks):
                        preserved_summaries[uid] = row["summary"]
                    targets = repair_items(row, checks, units[uid], graph)
                    if targets:
                        candidates[uid] = copy.deepcopy(row)
                        targeted[uid] = targets
            else:
                good[row["unit_id"]] = copy.deepcopy(row)
        return good, bad

    for call in plan.calls:
        good, bad = assess(dispatch(call), call.unit_ids)
        accepted.update(good)
        failed.update(bad)

    def reject_conflicts():
        conflicts = validate_combined(list(accepted.values()))
        findings.extend(asdict(f) for f in conflicts)
        for finding in conflicts:
            failed[finding.unit_id] = finding.code
            accepted.pop(finding.unit_id, None)

    reject_conflicts()
    if failed:
        # One bounded repair remains reserved. An oversized failed set must not
        # suppress every repair, nor erase failures that could not fit.
        repair = None
        selected = []
        for uid in (unit.id for unit in graph.units if unit.id in failed):
            if len(selected) == 8:
                break
            ids = selected + [uid]
            payload = _payload(graph, ids)
            if all(uid in financial_candidates for uid in ids):
                payload["repair_mode"] = "money_only"
                for item in payload["units"]:
                    item["financial_claims"] = [
                        {
                            "claim_index": i,
                            "actor": claim["actor"],
                            "action": claim["action"],
                            "money": claim["money"],
                        }
                        for i, claim in enumerate(
                            financial_candidates[item["id"]]["claims"]
                        )
                        if i in financial_indexes[item["id"]]
                    ]
            for payload_unit in payload["units"]:
                if payload_unit["id"] in targeted:
                    narrow_assignment(payload_unit, targeted[payload_unit["id"]], graph)
            payload["findings"] = {
                key: [f for f in findings if f["unit_id"] == key]
                or [{"code": failed[key]}]
                for key in ids
            }
            candidate = _call(
                "repair",
                ids,
                payload,
                plan.model,
                plan.reasoning_effort,
                plan.output_tokens,
            )
            if (
                candidate.estimated_input <= plan.per_call_input
                and sum(len(u["source_checklist"]) for u in payload["units"]) * 80
                <= plan.output_tokens
            ):
                repair, selected = candidate, ids
        if repair:
            good, bad = assess(dispatch(repair), repair.unit_ids, repairing=True)
            accepted.update(good)
            for uid in repair.unit_ids:
                failed.pop(uid, None)
            failed.update(bad)
            reject_conflicts()
    failed.update(
        {uid: "source_context_unresolved" for uid in plan.unresolved_unit_ids}
    )
    # Revalidate the final merged set, not only the latest repair.
    for uid, row in list(accepted.items()):
        if validate_provision(row, units[uid], graph, require_coverage=True):
            failed[uid] = "combined_validation_failed"
            del accepted[uid]
    synopsis = {"text": "", "explanation_ids": [], "status": "unavailable"}
    if accepted and plan.maximum_calls > call_count:
        call = _call(
            "synopsis",
            accepted,
            {
                "explanations": list(accepted.values()),
                "document_fingerprint": graph.document_fingerprint,
            },
            plan.model,
            plan.reasoning_effort,
            plan.output_tokens,
        )
        if call.estimated_input <= plan.per_call_input:
            output = dispatch(call)
            try:
                Draft202012Validator(SYNOPSIS_SCHEMA).validate(output)
                refs = output["explanation_ids"]
                if not refs or not set(refs) <= set(accepted):
                    raise ValidationError("synopsis_evidence")
                # Until independent semantic synthesis validation is available,
                # the synopsis may select complete accepted sentences, not invent
                # paraphrases or legal conclusions merely bearing a valid ID.
                remaining = output["text"].strip()
                for uid in refs:
                    sentence = accepted[uid]["summary"]
                    if remaining.startswith(sentence):
                        remaining = remaining[len(sentence) :].lstrip()
                    else:
                        raise ValidationError("unsupported_synopsis")
                if remaining:
                    raise ValidationError("unsupported_synopsis")
                # A synopsis remains a generated claim, explicitly unreviewed.
                synopsis = {
                    **output,
                    "status": "partial"
                    if failed or any(u.unresolved_dependencies for u in graph.units)
                    else "complete",
                }
            except ValidationError:
                pass
    rows = []
    for unit in graph.units:
        row = accepted.get(unit.id) or {
            "unit_id": unit.id,
            "status": "unresolved",
            "summary": "",
            "details": [],
            "claims": [],
            "unresolved_reason": failed.get(unit.id, "source_context_unresolved"),
        }
        rows.append(hydrate_evidence(row, graph))
    output = {
        "schema_version": VERSION,
        "document_fingerprint": graph.document_fingerprint,
        "pipeline_version": PROMPT_VERSION,
        "plan_fingerprint": plan.fingerprint,
        "synopsis": synopsis,
        "provisions": rows,
        "coverage": {
            **graph.coverage,
            "source_items": [
                {
                    **item,
                    "unit_id": unit.id,
                    "status": "structural_context"
                    if "structural_context" in item["kinds"]
                    else "mapped_unreviewed"
                    if unit.id in accepted
                    else "unresolved",
                }
                for unit in graph.units
                for item in source_checklist(unit, graph)
            ],
            "unresolved_unit_ids": [
                r["unit_id"] for r in rows if r["status"] == "unresolved"
            ],
            "context_limited_unit_ids": [
                u.id for u in graph.units if u.unresolved_dependencies
            ],
        },
        "quality": {
            "mechanical_status": "partial" if failed else "mechanically_valid",
            "semantic_review_status": "unreviewed",
        },
    }
    return AnalysisResult(
        output, "partial" if failed else "complete", call_count, tuple(findings)
    )
