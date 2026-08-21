from __future__ import annotations

import copy

from rest_framework import serializers

from apps.legislation.models import BillEnhancement, BillEnhancementAttempt

from .prompts import LEGAL_INFORMATION_DISCLAIMER, TRUNCATED_COVERAGE_NOTICE
from .service import retry_allowed


class EnhancementConfirmationSerializer(serializers.Serializer):
    source_fingerprint = serializers.RegexField(r"^[a-f0-9]{64}$")
    request_fingerprint = serializers.RegexField(r"^[a-f0-9]{64}$")
    credential_revision = serializers.IntegerField(min_value=1)


def _attempt_payload(attempt: BillEnhancementAttempt) -> dict:
    return {
        "id": attempt.pk,
        "sequence": attempt.sequence,
        "status": attempt.status,
        "credential_revision": attempt.credential_revision,
        "estimated_input_tokens": attempt.estimated_input_tokens,
        "usage": {
            "input_tokens": attempt.input_tokens,
            "output_tokens": attempt.output_tokens,
            "total_tokens": attempt.total_tokens,
        },
        "resolved_model": attempt.resolved_model or None,
        "failure_category": attempt.failure_category or None,
        "retry_allowed": retry_allowed(attempt),
        "started_at": attempt.started_at,
        "completed_at": attempt.completed_at,
        "created_at": attempt.created_at,
    }


def _expanded_result(enhancement: BillEnhancement):
    if enhancement.result_json is None:
        return None
    result = copy.deepcopy(enhancement.result_json)
    sources = {
        source["source_ref"]: source for source in enhancement.source_snapshot_json
    }
    for category in (
        "overview",
        "key_impacts",
        "obligations",
        "funding_and_timing",
        "uncertain_language",
    ):
        for item in result.get(category, []):
            item["cited_sources"] = [
                {
                    "source_ref": source_ref,
                    "label": "Cited source",
                    "quoted_text": sources[source_ref]["quoted_text"],
                    "section_label": sources[source_ref].get("section_label"),
                    "start_char": sources[source_ref].get("start_char"),
                    "end_char": sources[source_ref].get("end_char"),
                }
                for source_ref in item["source_refs"]
                if source_ref in sources
            ]
    return result


def enhancement_payload(enhancement: BillEnhancement, *, detail: bool) -> dict:
    attempts = getattr(enhancement, "ordered_attempts_cache", None)
    if attempts is None:
        attempts = list(enhancement.attempts.order_by("sequence"))
    payload = {
        "id": enhancement.pk,
        "bill_id": enhancement.bill_id,
        "status": enhancement.status,
        "provider": enhancement.provider,
        "requested_model": enhancement.requested_model,
        "reasoning_effort": enhancement.reasoning_effort,
        "prompt_version": enhancement.prompt_version,
        "output_schema_version": enhancement.output_schema_version,
        "source_packet_version": enhancement.source_packet_version,
        "source_fingerprint": enhancement.source_fingerprint,
        "request_fingerprint": enhancement.request_fingerprint,
        "truncated": bool(enhancement.source_manifest_json.get("truncated")),
        "coverage_notice": (
            TRUNCATED_COVERAGE_NOTICE
            if enhancement.source_manifest_json.get("truncated")
            else None
        ),
        "disclaimer": LEGAL_INFORMATION_DISCLAIMER,
        "usage": {
            "input_tokens": enhancement.input_tokens,
            "output_tokens": enhancement.output_tokens,
            "total_tokens": enhancement.total_tokens,
        },
        "created_at": enhancement.created_at,
        "updated_at": enhancement.updated_at,
        "completed_at": enhancement.completed_at,
        "latest_attempt": _attempt_payload(attempts[-1]) if attempts else None,
    }
    if detail:
        payload["result"] = _expanded_result(enhancement)
        payload["attempts"] = [_attempt_payload(attempt) for attempt in attempts]
        payload["poll_after_seconds"] = (
            2
            if enhancement.status
            in {
                BillEnhancement.Status.PENDING,
                BillEnhancement.Status.RUNNING,
            }
            else None
        )
    return payload
