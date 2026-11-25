from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from django.db import close_old_connections, connection
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.legislation.enhancements.private_diagnostics import (
    capture_step,
    capture_visible,
)
from apps.legislation.enhancements.service import (
    EnhancementServiceError,
    create_enhancement_attempt,
)
from apps.legislation.models import BillEnhancementDiagnostic, BillEnhancementStep
from apps.legislation.tests.test_enhancement_service import (
    _confirmation,
    _valid_credential,
    enhancement_owner,
    enhancement_settings,
    source_bill,
)
from apps.legislation.tests.test_enhancement_tasks import _pending_attempt


@pytest.mark.django_db
def test_cutover_requires_previous_reader_to_drain(
    enhancement_owner, enhancement_settings, source_bill
):
    from importlib import import_module
    from types import SimpleNamespace

    from django.apps import apps

    from .test_reader_enhancement_pipeline import install_reader

    require_drain = import_module(
        "apps.legislation.migrations.0032_require_reader_queue_drain"
    ).require_reader_queue_drain
    install_reader(source_bill)
    with enhancement_settings:
        attempt = _pending_attempt(enhancement_owner, source_bill)
    saved = attempt.enhancement
    saved.source_manifest_json["execution_settings"]["reader_execution_version"] = 7
    saved.save()
    editor = SimpleNamespace(connection=connection)
    for status in ("pending", "running"):
        attempt.status = status
        attempt.save()
        with pytest.raises(RuntimeError, match="previous worker"):
            require_drain(apps, editor)
    attempt.status = "succeeded"
    attempt.save()
    require_drain(apps, editor)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "schema,provider,effort", [("1.1", "openrouter", "none"), ("1.4", "openai", "none")]
)
def test_cutover_preserves_outstanding_paused_work(
    enhancement_owner, enhancement_settings, source_bill, schema, provider, effort
):
    from importlib import import_module
    from types import SimpleNamespace

    from django.apps import apps

    guard = import_module(
        "apps.legislation.migrations.0033_require_resumable_queue_drain"
    ).require_resumable_queue_drain
    with enhancement_settings:
        attempt = _pending_attempt(enhancement_owner, source_bill)
    saved = attempt.enhancement
    saved.output_schema_version, saved.provider, saved.reasoning_effort = (
        schema,
        provider,
        effort,
    )
    saved.source_manifest_json["execution_settings"] = {"reader_execution_version": 7}
    saved.save()
    editor = SimpleNamespace(connection=connection)
    for status in ("pending", "running", "paused"):
        attempt.status = status
        attempt.save()
        with pytest.raises(RuntimeError, match="previous worker"):
            guard(apps, editor)
    type(attempt).objects.create(
        enhancement=saved,
        sequence=2,
        credential_revision=1,
        status="succeeded",
        estimated_input_tokens=0,
        available_at=timezone.now(),
    )
    guard(apps, editor)


@pytest.mark.django_db
def test_legacy_native_request_drains_on_previous_worker(
    enhancement_owner, enhancement_settings, source_bill, monkeypatch
):
    from importlib import import_module
    from types import SimpleNamespace
    from unittest.mock import Mock, patch

    from django.apps import apps

    from apps.legislation.enhancements.providers.base import (
        ProviderResult,
        ProviderUsage,
    )
    from apps.legislation.enhancements.source_packet import build_enhancement_preflight
    from apps.legislation.tasks import run_bill_enhancement_attempt

    from .test_enhancement_tasks import _valid_output

    guard = import_module(
        "apps.legislation.migrations.0034_require_legacy_model_limit_drain"
    ).require_legacy_model_limit_drain
    editor = SimpleNamespace(connection=connection)
    with (
        enhancement_settings,
        override_settings(
            LLM_SOURCE_FIRST_ENABLED=False,
            LLM_READER_OWNED_TOKEN_TARGET=0,
            LLM_READER_MODEL_CAPACITIES={
                "openai/gpt-5.6-luna": {"output_tokens": 2048}
            },
        ),
    ):
        old_limits = patch(
            "apps.legislation.enhancements.source_packet.legacy_token_limits",
            return_value=(100000, 8000),
        )
        with old_limits:
            attempt = _pending_attempt(enhancement_owner, source_bill)
        saved = attempt.enhancement
        attempt.execution_config = {}
        attempt.save(update_fields=["execution_config"])
        del saved.source_manifest_json["model_limits_version"]
        saved.save()
        assert (
            build_enhancement_preflight(source_bill).request_fingerprint
            != saved.request_fingerprint
        )
        for state in ("paused", "running", "pending"):
            attempt.status = state
            attempt.save(update_fields=["status"])
            with pytest.raises(RuntimeError, match="previous worker"):
                guard(apps, editor)
        with override_settings(
            LLM_READER_MODEL_CAPACITIES={
                "openai/gpt-5.6-luna": {"context_tokens": 8192}
            }
        ):
            with pytest.raises(RuntimeError, match="previous worker"):
                guard(apps, editor)
        provider = Mock()
        provider.enhance_bill.return_value = ProviderResult(
            _valid_output("src_0001"), ProviderUsage(4, 3, 7), "id", "model"
        )
        monkeypatch.setattr("apps.legislation.tasks.get_provider", lambda _: provider)
        with old_limits:
            assert (
                run_bill_enhancement_attempt(attempt.pk, attempt.dispatch_token)[
                    "status"
                ]
                == "succeeded"
            )
        assert (
            provider.enhance_bill.call_args.kwargs["request"].request_envelope[
                "max_output_tokens"
            ]
            == 8000
        )
        guard(apps, editor)


@pytest.mark.django_db
def test_cutover_drains_source_first_jobs_with_changed_confirmed_limits(
    enhancement_owner, enhancement_settings, source_bill
):
    from importlib import import_module
    from types import SimpleNamespace

    from django.apps import apps

    from apps.legislation.enhancements.source_packet import build_enhancement_preflight

    guard = import_module(
        "apps.legislation.migrations.0035_require_source_first_model_limit_drain"
    ).require_source_first_drain
    editor = SimpleNamespace(connection=connection)
    with (
        enhancement_settings,
        override_settings(
            LLM_SOURCE_FIRST_ENABLED=True,
            LLM_READER_OWNED_TOKEN_TARGET=0,
            LLM_READER_MODEL_CAPACITIES={},
        ),
    ):
        attempt = _pending_attempt(enhancement_owner, source_bill)
        saved = attempt.enhancement
        assert saved.output_schema_version == "2.0-source-first"
        assert (
            build_enhancement_preflight(source_bill).analysis_plan.output_tokens == 8000
        )
        del saved.source_manifest_json["model_limits_version"]
        saved.save()
        guard(apps, editor)
        with override_settings(
            LLM_READER_MODEL_CAPACITIES={"openai/gpt-5.6-luna": {"output_tokens": 2048}}
        ):
            rebuilt = build_enhancement_preflight(source_bill)
            assert rebuilt.analysis_plan.output_tokens == 2048
            assert rebuilt.request_fingerprint != saved.request_fingerprint
            for state in ("pending", "running", "paused"):
                attempt.status = state
                attempt.save(update_fields=["status"])
                with pytest.raises(RuntimeError, match="previous worker"):
                    guard(apps, editor)
            type(attempt).objects.create(
                enhancement=saved,
                sequence=2,
                credential_revision=1,
                status="succeeded",
                estimated_input_tokens=0,
                available_at=timezone.now(),
            )
            guard(apps, editor)


@pytest.mark.django_db
def test_recreated_key_cannot_authorize_an_old_estimate(
    enhancement_owner, enhancement_settings, source_bill
):
    with enhancement_settings:
        original = _valid_credential(enhancement_owner)
        confirmed = _confirmation(source_bill, original)
        original.delete()
        replacement = _valid_credential(enhancement_owner)
        from apps.accounts.models import LLMPreference

        LLMPreference.objects.filter(user=enhancement_owner).update(
            active_credential=replacement
        )
        assert replacement.revision == confirmed["credential_revision"]
        with pytest.raises(EnhancementServiceError, match="preflight_changed"):
            create_enhancement_attempt(
                user=enhancement_owner, bill=source_bill, confirmed=confirmed
            )
        assert not BillEnhancementStep.objects.exists()


@pytest.mark.django_db
def test_confirmed_reader_rebuilds_original_target_after_flag_changes(
    enhancement_owner, enhancement_settings, source_bill
):
    from apps.legislation.tasks import _worker_preflight

    from .test_reader_enhancement_pipeline import install_reader

    install_reader(source_bill)
    with enhancement_settings, override_settings(LLM_READER_OWNED_TOKEN_TARGET=1000):
        credential = _valid_credential(enhancement_owner)
        attempt = create_enhancement_attempt(
            user=enhancement_owner,
            bill=source_bill,
            confirmed=_confirmation(source_bill, credential),
        ).attempt
        assert attempt.execution_config["owned_token_target"] == 1000
        with override_settings(LLM_READER_OWNED_TOKEN_TARGET=4000):
            preflight, _, failure = _worker_preflight(attempt)
            assert failure is None
            assert (
                preflight.request_fingerprint == attempt.enhancement.request_fingerprint
            )
            attempt.status = attempt.enhancement.status = "paused"
            attempt.save()
            attempt.enhancement.save()
            client = APIClient()
            client.force_authenticate(enhancement_owner)
            url = f"/api/bills/{source_bill.pk}/enhancements/"
            estimate = client.get(url + "estimate/").data
            assert estimate["matching_enhancement"]["id"] == attempt.enhancement_id
            response = client.post(
                url + f"{attempt.enhancement_id}/retry/", estimate, format="json"
            )
            assert response.status_code == 202, response.data
            resumed = attempt.enhancement.attempts.get(sequence=2)
            assert resumed.execution_config["owned_token_target"] == 1000
            assert (
                _worker_preflight(resumed)[0].request_fingerprint
                == preflight.request_fingerprint
            )


@pytest.mark.django_db(transaction=True)
def test_concurrent_accounts_share_one_dispatch(
    enhancement_owner, enhancement_settings, source_bill
):
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL row locks")
    bill_type = type(source_bill)
    second = User.objects.create_user(
        username="second-owner", email="second-owner@example.test"
    )
    barrier = Barrier(2)
    with enhancement_settings:
        confirmations = [
            (user.pk, _confirmation(source_bill, _valid_credential(user)))
            for user in (enhancement_owner, second)
        ]

        def submit(item):
            close_old_connections()
            try:
                user = User.objects.get(pk=item[0])
                bill = bill_type.objects.get(pk=source_bill.pk)
                barrier.wait(timeout=10)
                created = create_enhancement_attempt(
                    user=user, bill=bill, confirmed=item[1]
                )
                return created.attempt.pk, created.created
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, confirmations))
        assert results[0][0] == results[1][0]
        assert sorted(created for _, created in results) == [False, True]


@pytest.mark.django_db(transaction=True)
def test_two_reservations_cannot_exceed_one_call(
    enhancement_owner, enhancement_settings, source_bill
):
    from dataclasses import replace
    from unittest.mock import Mock

    from apps.legislation.enhancements.providers.base import ProviderError
    from apps.legislation.enhancements.reader_steps import (
        DurableReaderProvider,
        ReaderBudgetPaused,
    )
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
                    wrapper.enhance_bill(
                        api_key="fixture", request=request, timeout_seconds=1
                    )
                except ReaderBudgetPaused:
                    return "budget"
                except ProviderError as error:
                    return error.category
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(dispatch, ["first", "second"])) == [
                "budget",
                "provider_rate_limited",
            ]
        assert attempt.steps.count() == provider.enhance_bill.call_count == 1


@pytest.mark.django_db
def test_reader_detects_key_rotation_at_reservation(
    enhancement_owner, enhancement_settings, source_bill
):
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
        LLMCredential.objects.filter(pk=attempt.credential_id).update(
            revision=attempt.credential_revision + 1
        )
        provider = Mock()
        with pytest.raises(ProviderError) as caught:
            DurableReaderProvider(provider, attempt, "test-run", 1).enhance_bill(
                api_key="fixture", request=preflight, timeout_seconds=1
            )
        assert caught.value.category == "credential_changed"
        assert not attempt.steps.exists()
        provider.enhance_bill.assert_not_called()


@pytest.mark.django_db
def test_diagnostic_requires_current_owner_and_expires(
    enhancement_owner, enhancement_settings, source_bill
):
    with enhancement_settings, override_settings(LLM_DIAGNOSTIC_RETENTION_DAYS=1):
        attempt = _pending_attempt(enhancement_owner, source_bill)
        step = BillEnhancementStep.objects.create(
            attempt=attempt, step_index=0, status="failed", stage="reader"
        )
        with capture_step(step, enhancement_owner.pk):
            capture_visible(
                [{"content": "known-secret"}],
                {},
                "{ malformed",
                "stop",
                "response",
                "model",
                "known-secret",
            )
        url = f"/api/bills/{source_bill.pk}/enhancements/diagnostics/{step.pk}/"
        client = APIClient()
        client.force_authenticate(
            User.objects.create_user(username="other", email="other@example.test")
        )
        assert client.get(url).status_code == 404
        client.force_authenticate(enhancement_owner)
        response = client.get(url)
        assert response.status_code == 200 and b"known-secret" not in response.content
        assert response.json()["visible_output"] == "{ malformed"
        BillEnhancementDiagnostic.objects.update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        assert client.get(url).status_code == 404
