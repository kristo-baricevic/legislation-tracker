from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import timedelta

import pytest
from django.db import close_old_connections, connection
from django.test import override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.legislation.enhancements.private_diagnostics import capture_step, capture_visible
from apps.legislation.enhancements.service import EnhancementServiceError, create_enhancement_attempt
from apps.legislation.models import BillEnhancementDiagnostic, BillEnhancementStep
from apps.legislation.tests.test_enhancement_service import (
    _confirmation, _valid_credential, enhancement_owner, enhancement_settings, source_bill,
)
from apps.legislation.tests.test_enhancement_tasks import _pending_attempt
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_recreated_key_cannot_authorize_an_old_estimate(enhancement_owner, enhancement_settings, source_bill):
    with enhancement_settings:
        original = _valid_credential(enhancement_owner)
        confirmed = _confirmation(source_bill, original)
        original.delete()
        replacement = _valid_credential(enhancement_owner)
        from apps.accounts.models import LLMPreference
        LLMPreference.objects.filter(user=enhancement_owner).update(active_credential=replacement)
        assert replacement.revision == confirmed["credential_revision"]
        with pytest.raises(EnhancementServiceError, match="preflight_changed"):
            create_enhancement_attempt(user=enhancement_owner, bill=source_bill, confirmed=confirmed)
        assert not BillEnhancementStep.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_concurrent_accounts_share_one_dispatch(enhancement_owner, enhancement_settings, source_bill):
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL row locks")
    bill_type = type(source_bill)
    second = User.objects.create_user(username="second-owner", email="second-owner@example.test")
    barrier = Barrier(2)
    with enhancement_settings:
        confirmations = [(user.pk, _confirmation(source_bill, _valid_credential(user)))
                         for user in (enhancement_owner, second)]

        def submit(item):
            close_old_connections()
            try:
                user = User.objects.get(pk=item[0])
                bill = bill_type.objects.get(pk=source_bill.pk)
                barrier.wait(timeout=10)
                created = create_enhancement_attempt(user=user, bill=bill, confirmed=item[1])
                return created.attempt.pk, created.created
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, confirmations))
        assert results[0][0] == results[1][0]
        assert sorted(created for _, created in results) == [False, True]


@pytest.mark.django_db(transaction=True)
def test_two_reservations_cannot_exceed_one_call(enhancement_owner, enhancement_settings, source_bill):
    from dataclasses import replace
    from unittest.mock import Mock
    from apps.legislation.enhancements.providers.base import ProviderError
    from apps.legislation.enhancements.reader_steps import DurableReaderProvider, ReaderBudgetPaused
    from apps.legislation.enhancements.source_packet import build_enhancement_preflight
    from .test_reader_enhancement_pipeline import install_reader

    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL row locks")
    install_reader(source_bill)
    barrier = Barrier(2)
    with enhancement_settings:
        attempt = _pending_attempt(enhancement_owner, source_bill)
        attempt.status, attempt.run_token = "running", "test-run"
        attempt.lease_expires_at = timezone.now() + timedelta(minutes=5)
        attempt.save()
        preflight = build_enhancement_preflight(source_bill)
        provider = Mock()
        provider.enhance_bill.side_effect = ProviderError("provider_rate_limited")

        def dispatch(label):
            close_old_connections()
            try:
                envelope = {**preflight.request_envelope, "instructions": label}
                request = replace(preflight, request_envelope=envelope)
                wrapper = DurableReaderProvider(provider, attempt, "test-run", 1)
                barrier.wait(timeout=10)
                try:
                    wrapper.enhance_bill(api_key="fixture", request=request, timeout_seconds=1)
                except ReaderBudgetPaused:
                    return "budget"
                except ProviderError as error:
                    return error.category
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(dispatch, ["first", "second"])) == ["budget", "provider_rate_limited"]
        assert attempt.steps.count() == provider.enhance_bill.call_count == 1


@pytest.mark.django_db
def test_reader_detects_key_rotation_at_reservation(enhancement_owner, enhancement_settings, source_bill):
    from unittest.mock import Mock
    from apps.accounts.models import LLMCredential
    from apps.legislation.enhancements.providers.base import ProviderError
    from apps.legislation.enhancements.reader_steps import DurableReaderProvider
    from apps.legislation.enhancements.source_packet import build_enhancement_preflight
    from .test_reader_enhancement_pipeline import install_reader

    install_reader(source_bill)
    with enhancement_settings:
        attempt = _pending_attempt(enhancement_owner, source_bill)
        attempt.status, attempt.run_token = "running", "test-run"
        attempt.lease_expires_at = timezone.now() + timedelta(minutes=5)
        attempt.save()
        preflight = build_enhancement_preflight(source_bill)
        LLMCredential.objects.filter(pk=attempt.credential_id).update(revision=attempt.credential_revision + 1)
        provider = Mock()
        with pytest.raises(ProviderError) as caught:
            DurableReaderProvider(provider, attempt, "test-run", 1).enhance_bill(
                api_key="fixture", request=preflight, timeout_seconds=1)
        assert caught.value.category == "credential_changed"
        assert not attempt.steps.exists()
        provider.enhance_bill.assert_not_called()


@pytest.mark.django_db
def test_diagnostic_requires_current_owner_and_expires(enhancement_owner, enhancement_settings, source_bill):
    with enhancement_settings, override_settings(LLM_DIAGNOSTIC_RETENTION_DAYS=1):
        attempt = _pending_attempt(enhancement_owner, source_bill)
        step = BillEnhancementStep.objects.create(attempt=attempt, step_index=0, status="failed", stage="reader")
        with capture_step(step, enhancement_owner.pk):
            capture_visible([{"content": "known-secret"}], {}, "{ malformed", "stop", "response", "model", "known-secret")
        url = f"/api/bills/{source_bill.pk}/enhancements/diagnostics/{step.pk}/"
        client = APIClient()
        client.force_authenticate(User.objects.create_user(username="other", email="other@example.test"))
        assert client.get(url).status_code == 404
        client.force_authenticate(enhancement_owner)
        response = client.get(url)
        assert response.status_code == 200 and b"known-secret" not in response.content
        assert response.json()["visible_output"] == "{ malformed"
        BillEnhancementDiagnostic.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
        assert client.get(url).status_code == 404
