from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.llm_credentials import llm_feature_available
from apps.accounts.models import LLMCredential, selected_credentials
from apps.legislation.models import Bill, BillEnhancement, BillEnhancementAttempt

from .dispatch import request_enhancement_dispatch
from .model_selection import credential_target, planning_for, saved_owned_token_target, selectable
from .source_packet import PreflightUnavailable, build_enhancement_preflight
from .shared import shared_enhancement

ACTIVE_STATUSES = {
    BillEnhancementAttempt.Status.PENDING,
    BillEnhancementAttempt.Status.RUNNING,
}
USER_RETRYABLE_FAILURES = {
    # Invalid output remains unpublished and terminal for automatic workers,
    # but the user can explicitly confirm a new paid attempt.
    "invalid_output",
    "preflight_changed",
    "credential_changed",
    "credential_disabled",
    "encryption_error",
    "feature_disabled",
    "invalid_credentials",
    "model_access_denied",
    "provider_request_rejected",
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
        and selectable(credential_target(credential))
        and credential.validation_status == LLMCredential.ValidationStatus.VALID
        and credential.validated_revision == credential.revision
        and credential.validated_provider == credential.provider
        and credential.validated_model == credential_target(credential)[1]
    )


def attempt_credential_failure(attempt):
    credential = attempt.credential
    enhancement = attempt.enhancement
    if (
        credential is None
        or credential.user_id != enhancement.user_id
        or credential.revision != attempt.credential_revision
        or credential.provider != enhancement.provider
    ):
        return "credential_changed"
    if not credential.enabled:
        return "credential_disabled"
    if not (
        credential.validation_status == LLMCredential.ValidationStatus.VALID
        and credential.validated_revision == credential.revision
        and credential.validated_provider == credential.provider
        and (credential.validated_model == enhancement.requested_model
             or attempt.execution_config.get("model") == enhancement.requested_model)
    ):
        return "credential_changed"
    return None


def reader_reconciliation_required(attempt):
    if (attempt is None or attempt.status != BillEnhancementAttempt.Status.OUTCOME_UNKNOWN
            or attempt.enhancement.output_schema_version != "1.4"):
        return False
    from django.db.models import Q
    from apps.legislation.models import BillEnhancementCallCache, BillEnhancementStep

    # Earlier retries can have no steps of their own. Check the shared reservation
    # for the original dispatch as well as one encountered from another job.
    steps = BillEnhancementStep.objects.filter(attempt__enhancement_id=attempt.enhancement_id)
    blocked = attempt.citation_resolution_json.get("blocked_reservation")
    return BillEnhancementCallCache.objects.filter(status="dispatching").filter(
        Q(pk__in=steps.values("request_fingerprint")) | Q(pk=blocked)
    ).exists()


def retry_allowed(attempt: BillEnhancementAttempt | None) -> bool:
    if attempt is None:
        return False
    if attempt.status == BillEnhancementAttempt.Status.SUCCEEDED:
        from .shared import _reader_result_valid
        saved = attempt.enhancement
        return (saved.result_completeness == "partial" and saved.output_schema_version == "2.0-source-first"
                or saved.result_json is not None and not _reader_result_valid(saved))
    if attempt.status == BillEnhancementAttempt.Status.OUTCOME_UNKNOWN:
        return not reader_reconciliation_required(attempt)
    if attempt.status == BillEnhancementAttempt.Status.PAUSED:
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


def reusable_publication(enhancement, credential):
    published = enhancement.published_attempt
    if (enhancement.output_schema_version == "2.0-source-first"
        and enhancement.result_completeness == "partial" and published
        and published.credential_id == credential.pk
        and published.credential_revision == credential.revision):
        return enhancement.result_json
    return None


def execution_config(provider, model, credential):
    from .model_capabilities import resolve_capabilities
    from .provider_registry import adapter_for
    from .model_selection import owned_token_target
    limits = resolve_capabilities(provider, model)
    return {"provider": provider, "model": model, "credential_id": credential.pk, "revision": credential.revision,
            "owned_token_target": owned_token_target(),
            "adapter": adapter_for(provider), "capabilities": asdict(limits), "capability_fingerprint": limits.fingerprint}


def confirmation_fingerprint(preflight, credential):
    config = execution_config(preflight.provider, preflight.requested_model, credential)
    identity = f"{preflight.request_fingerprint}:{credential.pk}:{credential.revision}:{config['adapter']}:{config['capability_fingerprint']}"
    return hashlib.sha256(identity.encode()).hexdigest()


def _validate_confirmation(preflight, credential, confirmed) -> None:
    if (preflight.provider, preflight.requested_model) == ("openrouter", "openrouter/free"):
        raise EnhancementServiceError("concrete_model_required")
    if confirmed.get("source_fingerprint") != preflight.source_fingerprint:
        raise EnhancementServiceError("preflight_changed")
    if confirmed.get("credential_revision") != credential.revision:
        raise EnhancementServiceError("credential_changed")
    if confirmed.get("request_fingerprint") != confirmation_fingerprint(preflight, credential):
        raise EnhancementServiceError("preflight_changed")


def _locked_credential(user) -> LLMCredential:
    type(user).objects.select_for_update().get(pk=user.pk)
    credential = selected_credentials(user).select_for_update().first()
    if credential is None:
        raise EnhancementServiceError("credential_not_configured")
    if not credential.enabled:
        raise EnhancementServiceError("credential_disabled")
    if not selectable(credential_target(credential)):
        raise EnhancementServiceError("credential_changed")
    return credential


def _require_current_validation(credential: LLMCredential) -> None:
    if not credential_is_current(credential):
        raise EnhancementServiceError("credential_unverified")


def _build_locked_preflight(bill_id: int, credential, *, owned_target=None):
    bill = Bill.objects.select_for_update().get(pk=bill_id)
    try:
        with planning_for(credential_target(credential), owned_target=owned_target):
            return bill, build_enhancement_preflight(bill)
    except PreflightUnavailable as exc:
        raise EnhancementServiceError(exc.reason) from exc


def _new_enhancement(*, user, bill, preflight) -> BillEnhancement:
    from .provider_registry import adapter_for
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
        source_manifest_json={**preflight.source_manifest, "adapter": adapter_for(preflight.provider)},
        source_snapshot_json=preflight.source_snapshot,
    )


def _create_attempt(*, enhancement, credential, estimated_input_tokens, sequence, approved_request_fingerprint="", reused_result=None):
    attempt = BillEnhancementAttempt.objects.create(
        enhancement=enhancement,
        sequence=sequence,
        approved_request_fingerprint=approved_request_fingerprint,
        execution_config=execution_config(enhancement.provider, enhancement.requested_model, credential),
        reused_result_json=reused_result,
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
        # The bill lock serializes requests across users, not just one payer.
        locked_bill = Bill.objects.select_for_update().get(pk=bill.pk)
        shared = shared_enhancement(locked_bill)
        if shared is not None:
            latest = shared.attempts.order_by("-sequence").first()
            if latest is not None:
                return AttemptCreation(shared, latest, False)
        credential = _locked_credential(user)
        locked_bill, preflight = _build_locked_preflight(bill.pk, credential)
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
        locked_bill = Bill.objects.select_for_update().get(pk=bill.pk)
        enhancement = (
            BillEnhancement.objects.select_for_update()
            .filter(pk=enhancement_id, user=user, bill=locked_bill)
            .first()
        )
        if enhancement is None:
            raise EnhancementServiceError("not_found", http_status=404)
        shared = shared_enhancement(locked_bill)
        if shared is not None and shared.pk != enhancement.pk:
            latest = shared.attempts.order_by("-sequence").first()
            if latest is not None:
                return AttemptCreation(shared, latest, False)
        credential = _locked_credential(user)
        latest = enhancement.attempts.order_by("-sequence").first()
        if reader_reconciliation_required(latest):
            raise EnhancementServiceError("reconciliation_required")
        owned_target = saved_owned_token_target(latest) if latest and latest.status == "paused" else None
        _, preflight = _build_locked_preflight(locked_bill.pk, credential, owned_target=owned_target)
        base_fingerprint = preflight.request_fingerprint
        reused_result = reusable_publication(enhancement, credential)
        if reused_result:
            with planning_for(credential_target(credential), owned_target=owned_target):
                preflight = build_enhancement_preflight(locked_bill, reuse_result=reused_result)
        _validate_confirmation(preflight, credential, confirmed)
        _require_current_validation(credential)
        if enhancement.request_fingerprint != base_fingerprint:
            raise EnhancementServiceError("preflight_changed")

        if latest is not None and latest.status in ACTIVE_STATUSES:
            return AttemptCreation(enhancement, latest, False)
        if not retry_allowed(latest):
            raise EnhancementServiceError("retry_not_allowed")

        with planning_for(credential_target(credential), owned_target=owned_target):
            attempt = _create_attempt(
                enhancement=enhancement,
                credential=credential,
                estimated_input_tokens=preflight.estimated_input_tokens,
                sequence=latest.sequence + 1,
                approved_request_fingerprint=preflight.request_fingerprint,
                reused_result=reused_result,
            )
        if latest.status == BillEnhancementAttempt.Status.PAUSED:
            from apps.legislation.models import BillEnhancementWorkUnit
            BillEnhancementWorkUnit.objects.bulk_create([
                BillEnhancementWorkUnit(attempt=attempt, node_key=node.node_key, parent_key=node.parent_key,
                    batch_index=node.batch_index, request_json=node.request_json, status=node.status,
                    result_json=node.result_json, reason=node.reason)
                for node in latest.work_units.all()
            ])
            # The confirmed request fingerprint above fixes provider/model.
            # Rotating its API key must not switch models halfway through a plan.
            attempt.pinned_model = latest.pinned_model
            attempt.save(update_fields=['pinned_model'])
        enhancement.status = BillEnhancement.Status.PENDING
        enhancement.completed_at = None
        enhancement.save(update_fields=["status", "completed_at", "updated_at"])
        return AttemptCreation(enhancement, attempt, True)
