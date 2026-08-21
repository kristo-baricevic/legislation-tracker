import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.accounts.models import LLMCredential
from apps.accounts.tests.test_llm_credentials import FERNET_KEY
from apps.legislation.enhancements.service import (
    EnhancementServiceError,
    create_enhancement_attempt,
    retry_enhancement_attempt,
)
from apps.legislation.enhancements.source_packet import build_enhancement_preflight
from apps.legislation.models import Bill, BillDocument, BillEnhancementAttempt


@pytest.fixture
def enhancement_settings():
    return override_settings(
        LLM_ENHANCEMENTS_ENABLED=True,
        LLM_CREDENTIAL_ENCRYPTION_KEYS=f"primary:{FERNET_KEY}",
        LLM_CREDENTIAL_ACTIVE_KEY_ID="primary",
        LLM_ENHANCEMENT_PROVIDER="openai",
        LLM_ENHANCEMENT_MODEL="gpt-5.6-luna",
        LLM_ENHANCEMENT_REASONING_EFFORT="none",
        LLM_ENHANCEMENT_ALLOW_INSECURE_HTTP_IN_DEBUG=True,
    )


@pytest.fixture
def enhancement_owner(db):
    return get_user_model().objects.create_user(
        username="enhancement-owner@example.com",
        email="enhancement-owner@example.com",
        password="password123",
    )


@pytest.fixture
def source_bill(db):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 880",
        title="Durable Enhancement Act",
        status="introduced",
    )
    BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        is_active_version=True,
        extracted_text="SEC. 2. The Secretary shall publish a report within 90 days.",
        content_hash="source-hash-880",
    )
    return bill


def _valid_credential(user):
    credential = LLMCredential.objects.create_for_key(
        user=user,
        provider="openai",
        api_key="sk-test-enhancement",
    )
    credential.validation_status = LLMCredential.ValidationStatus.VALID
    credential.validated_revision = credential.revision
    credential.validated_provider = credential.provider
    credential.validated_model = "gpt-5.6-luna"
    credential.save()
    return credential


def _confirmation(bill, credential):
    preflight = build_enhancement_preflight(bill)
    return {
        "source_fingerprint": preflight.source_fingerprint,
        "request_fingerprint": preflight.request_fingerprint,
        "credential_revision": credential.revision,
    }


@pytest.mark.django_db
def test_create_is_idempotent_for_active_and_successful_requests(
    enhancement_owner,
    source_bill,
    enhancement_settings,
):
    with enhancement_settings:
        credential = _valid_credential(enhancement_owner)
        confirmation = _confirmation(source_bill, credential)
        first = create_enhancement_attempt(
            user=enhancement_owner,
            bill=source_bill,
            confirmed=confirmation,
        )
        second = create_enhancement_attempt(
            user=enhancement_owner,
            bill=source_bill,
            confirmed=confirmation,
        )

        assert first.created is True
        assert second.created is False
        assert second.attempt.pk == first.attempt.pk
        assert BillEnhancementAttempt.objects.count() == 1

        first.enhancement.status = first.enhancement.Status.SUCCEEDED
        first.enhancement.save(update_fields=["status"])
        third = create_enhancement_attempt(
            user=enhancement_owner,
            bill=source_bill,
            confirmed=confirmation,
        )

    assert third.created is False
    assert BillEnhancementAttempt.objects.count() == 1


@pytest.mark.django_db
def test_create_rejects_changed_confirmation_and_unvalidated_credential(
    enhancement_owner,
    source_bill,
    enhancement_settings,
):
    with enhancement_settings:
        credential = _valid_credential(enhancement_owner)
        confirmation = _confirmation(source_bill, credential)
        with pytest.raises(EnhancementServiceError) as changed:
            create_enhancement_attempt(
                user=enhancement_owner,
                bill=source_bill,
                confirmed={**confirmation, "source_fingerprint": "stale"},
            )
        assert changed.value.code == "preflight_changed"
        assert BillEnhancementAttempt.objects.count() == 0

        credential.replace_key("sk-test-replaced")
        with pytest.raises(EnhancementServiceError) as invalid:
            create_enhancement_attempt(
                user=enhancement_owner,
                bill=source_bill,
                confirmed=confirmation,
            )
        assert invalid.value.code == "credential_changed"
        assert BillEnhancementAttempt.objects.count() == 0


@pytest.mark.django_db
def test_terminal_attempt_requires_explicit_eligible_retry(
    enhancement_owner,
    source_bill,
    enhancement_settings,
):
    with enhancement_settings:
        credential = _valid_credential(enhancement_owner)
        confirmation = _confirmation(source_bill, credential)
        created = create_enhancement_attempt(
            user=enhancement_owner,
            bill=source_bill,
            confirmed=confirmation,
        )
        attempt = created.attempt
        attempt.status = attempt.Status.FAILED
        attempt.failure_category = "provider_rate_limited"
        attempt.save(update_fields=["status", "failure_category"])
        created.enhancement.status = created.enhancement.Status.FAILED
        created.enhancement.save(update_fields=["status"])

        with pytest.raises(EnhancementServiceError) as duplicate_create:
            create_enhancement_attempt(
                user=enhancement_owner,
                bill=source_bill,
                confirmed=confirmation,
            )
        assert duplicate_create.value.code == "retry_required"

        retried = retry_enhancement_attempt(
            user=enhancement_owner,
            bill=source_bill,
            enhancement_id=created.enhancement.pk,
            confirmed=confirmation,
        )

    assert retried.created is True
    assert retried.attempt.sequence == 2
    assert retried.attempt.status == BillEnhancementAttempt.Status.PENDING
    assert created.enhancement.attempts.count() == 2


@pytest.mark.django_db
def test_refusal_is_not_retryable_and_ownership_is_enforced(
    enhancement_owner,
    source_bill,
    enhancement_settings,
):
    other = get_user_model().objects.create_user(
        username="other-enhancement@example.com",
        email="other-enhancement@example.com",
        password="password123",
    )
    with enhancement_settings:
        credential = _valid_credential(enhancement_owner)
        confirmation = _confirmation(source_bill, credential)
        created = create_enhancement_attempt(
            user=enhancement_owner,
            bill=source_bill,
            confirmed=confirmation,
        )
        created.attempt.status = created.attempt.Status.REFUSED
        created.attempt.failure_category = "content_refusal"
        created.attempt.save(update_fields=["status", "failure_category"])
        created.enhancement.status = created.enhancement.Status.REFUSED
        created.enhancement.save(update_fields=["status"])

        with pytest.raises(EnhancementServiceError) as refused:
            retry_enhancement_attempt(
                user=enhancement_owner,
                bill=source_bill,
                enhancement_id=created.enhancement.pk,
                confirmed=confirmation,
            )
        assert refused.value.code == "retry_not_allowed"

        with pytest.raises(EnhancementServiceError) as hidden:
            retry_enhancement_attempt(
                user=other,
                bill=source_bill,
                enhancement_id=created.enhancement.pk,
                confirmed=confirmation,
            )
        assert hidden.value.http_status == 404


@pytest.mark.django_db
@pytest.mark.parametrize(
    "failure_category",
    [
        "credential_changed",
        "credential_disabled",
        "feature_disabled",
        "invalid_credentials",
        "model_access_denied",
        "provider_rate_limited",
        "provider_unavailable",
        "quota_exhausted",
    ],
)
def test_definitive_pre_call_or_recoverable_provider_failures_allow_confirmed_retry(
    enhancement_owner,
    source_bill,
    enhancement_settings,
    failure_category,
):
    with enhancement_settings:
        credential = _valid_credential(enhancement_owner)
        confirmation = _confirmation(source_bill, credential)
        created = create_enhancement_attempt(
            user=enhancement_owner,
            bill=source_bill,
            confirmed=confirmation,
        )
        created.attempt.status = created.attempt.Status.FAILED
        created.attempt.failure_category = failure_category
        created.attempt.save(update_fields=["status", "failure_category"])
        created.enhancement.status = created.enhancement.Status.FAILED
        created.enhancement.save(update_fields=["status"])

        retried = retry_enhancement_attempt(
            user=enhancement_owner,
            bill=source_bill,
            enhancement_id=created.enhancement.pk,
            confirmed=confirmation,
        )

    assert retried.created is True
    assert retried.attempt.sequence == 2
