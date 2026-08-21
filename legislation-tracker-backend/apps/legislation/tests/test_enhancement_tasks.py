# ruff: noqa: F401, F811

from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.accounts.models import LLMCredential
from apps.legislation.enhancements.providers.base import (
    ProviderError,
    ProviderResult,
    ProviderUsage,
)
from apps.legislation.enhancements.service import create_enhancement_attempt
from apps.legislation.models import BillEnhancement, BillEnhancementAttempt
from apps.legislation.tasks import (
    dispatch_bill_enhancement_attempts,
    recover_stale_bill_enhancement_attempts,
    run_bill_enhancement_attempt,
)

from .test_enhancement_service import (
    _confirmation,
    _valid_credential,
    enhancement_owner,
    enhancement_settings,
    source_bill,
)


def _pending_attempt(owner, bill):
    credential = LLMCredential.objects.filter(user=owner).first()
    if credential is None:
        credential = _valid_credential(owner)
    created = create_enhancement_attempt(
        user=owner,
        bill=bill,
        confirmed=_confirmation(bill, credential),
    )
    return created.attempt


def _valid_output(source_ref):
    return {
        "schema_version": "1.1",
        "overview": [
            {"text": "The bill requires a report.", "source_refs": [source_ref]}
        ],
        "key_impacts": [],
        "obligations": [],
        "funding_and_timing": [],
        "uncertain_language": [],
    }


@pytest.mark.django_db(transaction=True)
def test_dispatch_publishes_only_id_and_token_and_recovers_publish_failure(
    enhancement_owner,
    source_bill,
    enhancement_settings,
    monkeypatch,
):
    published = []
    with enhancement_settings:
        attempt = _pending_attempt(enhancement_owner, source_bill)

        def publish(*, args):
            published.append(args)

        monkeypatch.setattr(
            "apps.legislation.tasks.run_bill_enhancement_attempt.apply_async",
            publish,
        )
        result = dispatch_bill_enhancement_attempts(attempt_ids=[attempt.id])
        attempt.refresh_from_db()

        assert result == {"published": 1, "failed": 0}
        assert published == [[attempt.id, attempt.dispatch_token]]
        assert attempt.status == BillEnhancementAttempt.Status.PENDING
        assert attempt.dispatch_lease_expires_at > timezone.now()

        attempt.dispatch_lease_expires_at = timezone.now() - timedelta(seconds=1)
        attempt.save(update_fields=["dispatch_lease_expires_at"])
        monkeypatch.setattr(
            "apps.legislation.tasks.run_bill_enhancement_attempt.apply_async",
            lambda **kwargs: (_ for _ in ()).throw(ConnectionError("broker down")),
        )
        failed = dispatch_bill_enhancement_attempts(attempt_ids=[attempt.id])
        attempt.refresh_from_db()

    assert failed == {"published": 0, "failed": 1}
    assert attempt.status == BillEnhancementAttempt.Status.PENDING
    assert attempt.dispatch_token == ""
    assert attempt.dispatch_lease_expires_at is None


@pytest.mark.django_db(transaction=True)
def test_worker_claims_once_validates_and_promotes_usage(
    enhancement_owner,
    source_bill,
    enhancement_settings,
    monkeypatch,
):
    calls = []

    class Provider:
        def enhance_bill(self, **kwargs):
            calls.append(kwargs)
            source_ref = kwargs["request"].source_snapshot[0]["source_ref"]
            return ProviderResult(
                output=_valid_output(source_ref),
                usage=ProviderUsage(
                    input_tokens=120, output_tokens=30, total_tokens=150
                ),
                response_id="private-response-id",
                resolved_model="gpt-5.6-luna-2026-08-01",
            )

    with enhancement_settings:
        attempt = _pending_attempt(enhancement_owner, source_bill)
        attempt.dispatch_token = "dispatch-one"
        attempt.save(update_fields=["dispatch_token"])
        monkeypatch.setattr(
            "apps.legislation.tasks.get_provider",
            lambda name: Provider(),
        )

        first = run_bill_enhancement_attempt(attempt.id, "dispatch-one")
        duplicate = run_bill_enhancement_attempt(attempt.id, "dispatch-one")
        attempt.refresh_from_db()
        enhancement = attempt.enhancement
        enhancement.refresh_from_db()

    assert first == {"status": "succeeded"}
    assert duplicate == {"status": "not_claimed"}
    assert len(calls) == 1
    assert calls[0]["api_key"] == "sk-test-enhancement"
    assert attempt.status == BillEnhancementAttempt.Status.SUCCEEDED
    assert attempt.provider_response_id == "private-response-id"
    assert attempt.resolved_model == "gpt-5.6-luna-2026-08-01"
    assert enhancement.status == BillEnhancement.Status.SUCCEEDED
    assert enhancement.successful_attempt_id == attempt.id
    assert enhancement.total_tokens == 150


@pytest.mark.django_db(transaction=True)
def test_worker_fails_closed_before_provider_when_feature_or_credential_changed(
    enhancement_owner,
    source_bill,
    enhancement_settings,
    monkeypatch,
):
    provider_calls = []
    with enhancement_settings:
        disabled_attempt = _pending_attempt(enhancement_owner, source_bill)
        disabled_attempt.dispatch_token = "disabled-token"
        disabled_attempt.save(update_fields=["dispatch_token"])
        monkeypatch.setattr(
            "apps.legislation.tasks.get_provider",
            lambda name: provider_calls.append(name),
        )

    with override_settings(LLM_ENHANCEMENTS_ENABLED=False):
        disabled = run_bill_enhancement_attempt(
            disabled_attempt.id,
            "disabled-token",
        )
    disabled_attempt.refresh_from_db()

    with enhancement_settings:
        disabled_attempt.enhancement.delete()
        changed_attempt = _pending_attempt(enhancement_owner, source_bill)
        changed_attempt.dispatch_token = "changed-token"
        changed_attempt.save(update_fields=["dispatch_token"])
        changed_attempt.credential.replace_key("sk-test-new-revision")
        changed = run_bill_enhancement_attempt(changed_attempt.id, "changed-token")
        changed_attempt.refresh_from_db()

    assert disabled == {"status": "failed", "category": "feature_disabled"}
    assert disabled_attempt.failure_category == "feature_disabled"
    assert changed == {"status": "failed", "category": "credential_changed"}
    assert changed_attempt.failure_category == "credential_changed"
    assert provider_calls == []


@pytest.mark.django_db(transaction=True)
def test_provider_timeout_becomes_unknown_and_invalid_output_is_terminal(
    enhancement_owner,
    source_bill,
    enhancement_settings,
    monkeypatch,
):
    class TimeoutProvider:
        def enhance_bill(self, **kwargs):
            raise ProviderError(
                "provider_timeout",
                outcome_unknown=True,
                retry_allowed=False,
                usage=ProviderUsage(input_tokens=50),
            )

    with enhancement_settings:
        attempt = _pending_attempt(enhancement_owner, source_bill)
        attempt.dispatch_token = "timeout-token"
        attempt.save(update_fields=["dispatch_token"])
        monkeypatch.setattr(
            "apps.legislation.tasks.get_provider",
            lambda name: TimeoutProvider(),
        )
        unknown = run_bill_enhancement_attempt(attempt.id, "timeout-token")
        attempt.refresh_from_db()
        attempt.enhancement.refresh_from_db()

        assert unknown == {"status": "outcome_unknown", "category": "provider_timeout"}
        assert attempt.status == BillEnhancementAttempt.Status.OUTCOME_UNKNOWN
        assert attempt.input_tokens == 50
        assert attempt.enhancement.status == BillEnhancement.Status.OUTCOME_UNKNOWN

        attempt.enhancement.delete()
        attempt = _pending_attempt(enhancement_owner, source_bill)
        attempt.dispatch_token = "invalid-token"
        attempt.save(update_fields=["dispatch_token"])

        class InvalidProvider:
            def enhance_bill(self, **kwargs):
                return ProviderResult(
                    output={"not": "the schema"},
                    usage=ProviderUsage(total_tokens=99),
                    response_id="private-invalid-id",
                    resolved_model="resolved",
                )

        monkeypatch.setattr(
            "apps.legislation.tasks.get_provider",
            lambda name: InvalidProvider(),
        )
        invalid = run_bill_enhancement_attempt(attempt.id, "invalid-token")
        attempt.refresh_from_db()

    assert invalid == {"status": "failed", "category": "invalid_output"}
    assert attempt.failure_category == "invalid_output"
    assert attempt.total_tokens == 99


@pytest.mark.django_db(transaction=True)
def test_definitive_provider_auth_rejection_invalidates_only_the_used_revision(
    enhancement_owner,
    source_bill,
    enhancement_settings,
    monkeypatch,
):
    class RejectedProvider:
        def enhance_bill(self, **kwargs):
            raise ProviderError("invalid_credentials")

    with enhancement_settings:
        attempt = _pending_attempt(enhancement_owner, source_bill)
        attempt.dispatch_token = "rejected-token"
        attempt.save(update_fields=["dispatch_token"])
        monkeypatch.setattr(
            "apps.legislation.tasks.get_provider",
            lambda name: RejectedProvider(),
        )

        result = run_bill_enhancement_attempt(attempt.id, "rejected-token")
        attempt.refresh_from_db()
        credential = LLMCredential.objects.get(pk=attempt.credential_id)

    assert result == {"status": "failed", "category": "invalid_credentials"}
    assert credential.validation_status == LLMCredential.ValidationStatus.INVALID
    assert credential.validated_revision == attempt.credential_revision


@pytest.mark.django_db(transaction=True)
def test_worker_does_not_report_success_after_its_run_lease_was_recovered(
    enhancement_owner,
    source_bill,
    enhancement_settings,
    monkeypatch,
):
    class Provider:
        def enhance_bill(self, **kwargs):
            source_ref = kwargs["request"].source_snapshot[0]["source_ref"]
            return ProviderResult(
                output=_valid_output(source_ref),
                usage=ProviderUsage(total_tokens=12),
                response_id="private-response-id",
                resolved_model="resolved-model",
            )

    with enhancement_settings:
        attempt = _pending_attempt(enhancement_owner, source_bill)
        attempt.dispatch_token = "lost-lease-token"
        attempt.save(update_fields=["dispatch_token"])
        monkeypatch.setattr(
            "apps.legislation.tasks.get_provider",
            lambda name: Provider(),
        )
        monkeypatch.setattr(
            "apps.legislation.tasks._finish_enhancement_attempt",
            lambda **kwargs: False,
        )

        result = run_bill_enhancement_attempt(attempt.id, "lost-lease-token")

    assert result == {"status": "outcome_unknown", "category": "outcome_unknown"}


@pytest.mark.django_db(transaction=True)
def test_recovery_marks_expired_run_unknown_without_provider_or_dispatch(
    enhancement_owner,
    source_bill,
    enhancement_settings,
    monkeypatch,
):
    calls = []
    with enhancement_settings:
        attempt = _pending_attempt(enhancement_owner, source_bill)
        attempt.status = BillEnhancementAttempt.Status.RUNNING
        attempt.run_token = "lost-worker"
        attempt.lease_expires_at = timezone.now() - timedelta(seconds=1)
        attempt.started_at = timezone.now() - timedelta(minutes=5)
        attempt.save()
        attempt.enhancement.status = BillEnhancement.Status.RUNNING
        attempt.enhancement.save(update_fields=["status"])
        monkeypatch.setattr(
            "apps.legislation.tasks.get_provider",
            lambda name: calls.append(name),
        )
        monkeypatch.setattr(
            "apps.legislation.tasks.run_bill_enhancement_attempt.apply_async",
            lambda **kwargs: calls.append(kwargs),
        )

        result = recover_stale_bill_enhancement_attempts()
        attempt.refresh_from_db()
        attempt.enhancement.refresh_from_db()

    assert result == {"recovered": 1}
    assert attempt.status == BillEnhancementAttempt.Status.OUTCOME_UNKNOWN
    assert attempt.failure_category == "outcome_unknown"
    assert attempt.enhancement.status == BillEnhancement.Status.OUTCOME_UNKNOWN
    assert calls == []
