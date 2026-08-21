from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.llm_credentials import llm_feature_available
from apps.accounts.models import LLMCredential
from apps.legislation.models import Bill, BillEnhancement, BillEnhancementAttempt

from .dispatch import request_enhancement_dispatch
from .source_packet import PreflightUnavailable, build_enhancement_preflight

ACTIVE_STATUSES = {
    BillEnhancementAttempt.Status.PENDING,
    BillEnhancementAttempt.Status.RUNNING,
}
USER_RETRYABLE_FAILURES = {
    "credential_changed",
    "credential_disabled",
    "encryption_error",
    "feature_disabled",
    "invalid_credentials",
    "model_access_denied",
    "provider_rate_limited",
    "provider_unavailable",
    "source_unavailable",
}


class EnhancementServiceError(RuntimeError):
    def __init__(self, code: str, *, http_status: int = 409):
        super().__init__(code)
        self.code = code
        self.http_status = http_status


@dataclass(frozen=True)
class AttemptCreation:
    enhancement: BillEnhancement
    attempt: BillEnhancementAttempt
    created: bool


def credential_is_current(credential: LLMCredential | None) -> bool:
    return bool(
        credential
        and credential.enabled
        and credential.provider == settings.LLM_ENHANCEMENT_PROVIDER
        and credential.validation_status == LLMCredential.ValidationStatus.VALID
        and credential.validated_revision == credential.revision
        and credential.validated_provider == credential.provider
        and credential.validated_model == settings.LLM_ENHANCEMENT_MODEL
    )


def retry_allowed(attempt: BillEnhancementAttempt | None) -> bool:
    if attempt is None:
        return False
    if attempt.status == BillEnhancementAttempt.Status.OUTCOME_UNKNOWN:
        return True
    if attempt.status != BillEnhancementAttempt.Status.FAILED:
        return False
    if attempt.failure_category == "quota_exhausted":
        credential = attempt.credential
        return bool(
            credential_is_current(credential)
            and attempt.completed_at
            and credential.validated_at
            and credential.validated_at > attempt.completed_at
        )
    return attempt.failure_category in USER_RETRYABLE_FAILURES


def _validate_confirmation(preflight, credential, confirmed) -> None:
    if confirmed.get("source_fingerprint") != preflight.source_fingerprint:
        raise EnhancementServiceError("preflight_changed")
    if confirmed.get("request_fingerprint") != preflight.request_fingerprint:
        raise EnhancementServiceError("preflight_changed")
    if confirmed.get("credential_revision") != credential.revision:
        raise EnhancementServiceError("credential_changed")


def _locked_credential(user) -> LLMCredential:
    credential = LLMCredential.objects.select_for_update().filter(user=user).first()
    if credential is None:
        raise EnhancementServiceError("credential_not_configured")
    if not credential.enabled:
        raise EnhancementServiceError("credential_disabled")
    if credential.provider != settings.LLM_ENHANCEMENT_PROVIDER:
        raise EnhancementServiceError("credential_changed")
    return credential


def _require_current_validation(credential: LLMCredential) -> None:
    if not credential_is_current(credential):
        raise EnhancementServiceError("credential_unverified")


def _build_locked_preflight(bill_id: int):
    bill = Bill.objects.select_for_update().get(pk=bill_id)
    try:
        return bill, build_enhancement_preflight(bill)
    except PreflightUnavailable as exc:
        raise EnhancementServiceError(exc.reason) from exc


def _new_enhancement(*, user, bill, preflight) -> BillEnhancement:
    return BillEnhancement.objects.create(
        user=user,
        bill=bill,
        provider=preflight.provider,
        requested_model=preflight.requested_model,
        reasoning_effort=preflight.reasoning_effort,
        prompt_version=preflight.prompt_version,
        output_schema_version=preflight.output_schema_version,
        source_packet_version=preflight.source_packet_version,
        source_fingerprint=preflight.source_fingerprint,
        request_fingerprint=preflight.request_fingerprint,
        source_manifest_json=preflight.source_manifest,
        source_snapshot_json=preflight.source_snapshot,
    )


def _create_attempt(*, enhancement, credential, estimated_input_tokens, sequence):
    attempt = BillEnhancementAttempt.objects.create(
        enhancement=enhancement,
        sequence=sequence,
        credential=credential,
        credential_revision=credential.revision,
        status=BillEnhancementAttempt.Status.PENDING,
        available_at=timezone.now(),
        estimated_input_tokens=estimated_input_tokens,
    )
    transaction.on_commit(lambda: request_enhancement_dispatch(attempt.pk))
    return attempt


def create_enhancement_attempt(*, user, bill, confirmed) -> AttemptCreation:
    if not llm_feature_available():
        raise EnhancementServiceError("feature_unavailable", http_status=503)

    with transaction.atomic():
        locked_bill, preflight = _build_locked_preflight(bill.pk)
        credential = _locked_credential(user)
        _validate_confirmation(preflight, credential, confirmed)
        _require_current_validation(credential)
        enhancement = (
            BillEnhancement.objects.select_for_update()
            .filter(
                user=user,
                bill=locked_bill,
                request_fingerprint=preflight.request_fingerprint,
            )
            .first()
        )
        if enhancement is not None:
            latest = enhancement.attempts.order_by("-sequence").first()
            if (
                enhancement.status
                in {
                    BillEnhancement.Status.PENDING,
                    BillEnhancement.Status.RUNNING,
                    BillEnhancement.Status.SUCCEEDED,
                }
                and latest is not None
            ):
                return AttemptCreation(enhancement, latest, False)
            raise EnhancementServiceError("retry_required")

        try:
            # Keep uniqueness races inside a savepoint so the outer transaction
            # remains usable when another request wins the same identity.
            with transaction.atomic():
                enhancement = _new_enhancement(
                    user=user,
                    bill=locked_bill,
                    preflight=preflight,
                )
                attempt = _create_attempt(
                    enhancement=enhancement,
                    credential=credential,
                    estimated_input_tokens=preflight.estimated_input_tokens,
                    sequence=1,
                )
        except IntegrityError:
            enhancement = BillEnhancement.objects.get(
                user=user,
                bill=locked_bill,
                request_fingerprint=preflight.request_fingerprint,
            )
            attempt = enhancement.attempts.order_by("-sequence").first()
            if attempt is None:
                raise
            return AttemptCreation(enhancement, attempt, False)
        return AttemptCreation(enhancement, attempt, True)


def retry_enhancement_attempt(
    *,
    user,
    bill,
    enhancement_id: int,
    confirmed,
) -> AttemptCreation:
    if not llm_feature_available():
        raise EnhancementServiceError("feature_unavailable", http_status=503)

    with transaction.atomic():
        locked_bill, preflight = _build_locked_preflight(bill.pk)
        enhancement = (
            BillEnhancement.objects.select_for_update()
            .filter(pk=enhancement_id, user=user, bill=locked_bill)
            .first()
        )
        if enhancement is None:
            raise EnhancementServiceError("not_found", http_status=404)
        credential = _locked_credential(user)
        _validate_confirmation(preflight, credential, confirmed)
        _require_current_validation(credential)
        if enhancement.request_fingerprint != preflight.request_fingerprint:
            raise EnhancementServiceError("preflight_changed")

        latest = enhancement.attempts.order_by("-sequence").first()
        if latest is not None and latest.status in ACTIVE_STATUSES:
            return AttemptCreation(enhancement, latest, False)
        if not retry_allowed(latest):
            raise EnhancementServiceError("retry_not_allowed")

        attempt = _create_attempt(
            enhancement=enhancement,
            credential=credential,
            estimated_input_tokens=preflight.estimated_input_tokens,
            sequence=latest.sequence + 1,
        )
        enhancement.status = BillEnhancement.Status.PENDING
        enhancement.completed_at = None
        enhancement.save(update_fields=["status", "completed_at", "updated_at"])
        return AttemptCreation(enhancement, attempt, True)
