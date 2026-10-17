"""Durable boundary around each provider call. Never automatically replay dispatches."""

from dataclasses import replace
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.legislation.models import BillEnhancementAttempt, BillEnhancementStep

from .providers.base import ProviderError, ProviderUsage
from .provision_pipeline import run_analysis


def execute_source_first(attempt, run_token, preflight, provider, worker_preflight):
    current_key = None

    def check_current():
        nonlocal current_key
        current = BillEnhancementAttempt.objects.select_related(
            "credential", "enhancement__bill"
        ).get(pk=attempt.pk)
        if (
            current.status != "running"
            or current.run_token != run_token
            or not current.lease_expires_at
            or current.lease_expires_at <= timezone.now()
        ):
            raise ProviderError("outcome_unknown", outcome_unknown=True)
        fresh, current_key, failure = worker_preflight(current)
        if failure:
            raise ProviderError(failure)
        if fresh.request_fingerprint != preflight.request_fingerprint:
            raise ProviderError("source_unavailable")

    def checkpoint(state, index, call, response):
        with transaction.atomic():
            locked = BillEnhancementAttempt.objects.select_for_update().get(
                pk=attempt.pk
            )
            if state == "dispatching":
                check_current()
                existing = BillEnhancementStep.objects.filter(
                    attempt=locked, step_index=index
                ).first()
                if existing:
                    # A restarted worker cannot know if an in-flight call charged.
                    raise ProviderError("outcome_unknown", outcome_unknown=True)
                BillEnhancementStep.objects.create(
                    attempt=locked,
                    step_index=index,
                    stage=call.stage,
                    request_fingerprint=call.request_fingerprint,
                    unit_ids=list(call.unit_ids),
                    status="dispatching",
                )
                locked.lease_expires_at = timezone.now() + timedelta(
                    seconds=max(
                        settings.LLM_ENHANCEMENT_RUN_LEASE_SECONDS,
                        settings.LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS + 30,
                    )
                )
                locked.save(update_fields=["lease_expires_at", "updated_at"])
            else:
                # Retain paid-call evidence even when cancellation won the race;
                # check_current prevents a further dispatch or publication.
                usage = getattr(response, "usage", ProviderUsage())
                BillEnhancementStep.objects.filter(
                    attempt=locked,
                    step_index=index,
                    request_fingerprint=call.request_fingerprint,
                    status="dispatching",
                ).update(
                    status=state,
                    result_json=getattr(response, "output", None),
                    response_id=getattr(response, "response_id", ""),
                    diagnostics=(
                        {
                            "category": response.category,
                            "code": response.validation_code,
                            "detail": response.validation_detail,
                        }
                        if isinstance(response, ProviderError)
                        else {}
                    ),
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    total_tokens=usage.total_tokens,
                )

    def invoke(call):
        request = replace(
            preflight, request_envelope={"source_first_payload": call.payload}
        )
        method = getattr(
            provider,
            {
                "generation": "generate_provisions",
                "repair": "repair_provisions",
                "synopsis": "generate_synopsis",
            }[call.stage],
        )
        return method(
            api_key=current_key,
            request=request,
            timeout_seconds=settings.LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS,
        )

    result = run_analysis(preflight.analysis_plan, invoke, checkpoint)
    check_current()
    return result


def step_usage(attempt_id):
    rows = list(BillEnhancementStep.objects.filter(attempt_id=attempt_id))

    def total(field):
        values = [getattr(r, field) for r in rows]
        return None if any(v is None for v in values) else sum(values)

    return ProviderUsage(
        total("input_tokens"), total("output_tokens"), total("total_tokens")
    )


def should_promote(existing, candidate):
    if not candidate or candidate.get("schema_version") != "2.0-source-first":
        return False
    if not existing:
        return True
    if existing.get("document_fingerprint") != candidate.get("document_fingerprint"):
        return False
    old_missing = set(existing["coverage"]["unresolved_unit_ids"])
    new_missing = set(candidate["coverage"]["unresolved_unit_ids"])
    if not old_missing:
        return False
    old_accepted = {
        r["unit_id"]: r for r in existing["provisions"] if r["status"] == "explained"
    }
    new_rows = {r["unit_id"]: r for r in candidate["provisions"]}
    return new_missing < old_missing and all(
        new_rows.get(uid) == row for uid, row in old_accepted.items()
    )
