# ruff: noqa: F401, F811
from dataclasses import replace
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.legislation.enhancements.providers.base import (
    ProviderError,
    ProviderResult,
    ProviderUsage,
)
from apps.legislation.enhancements.reader_steps import DurableReaderProvider
from apps.legislation.enhancements.source_packet import build_enhancement_preflight
from apps.legislation.tests.test_enhancement_service import (
    enhancement_owner,
    enhancement_settings,
    source_bill,
)
from apps.legislation.tests.test_enhancement_tasks import _pending_attempt
from apps.legislation.tests.test_reader_enhancement_pipeline import install_reader


@pytest.mark.django_db
def test_ambiguous_reader_reservation_blocks_confirmation_until_reconciled(
    source_bill, enhancement_owner, enhancement_settings, monkeypatch
):
    from unittest.mock import Mock

    from rest_framework.test import APIClient

    from apps.legislation.models import BillEnhancementCallCache
    from apps.legislation.tasks import run_bill_enhancement_attempt

    from .test_enhancement_service import _confirmation

    install_reader(source_bill)
    client = APIClient()
    client.force_authenticate(enhancement_owner)
    provider = Mock()
    provider.enhance_bill.side_effect = ProviderError(
        "outcome_unknown", outcome_unknown=True
    )
    monkeypatch.setattr("apps.legislation.tasks.get_provider", lambda _: provider)
    url = f"/api/bills/{source_bill.pk}/enhancements/"
    with enhancement_settings:
        attempt = _pending_attempt(enhancement_owner, source_bill)
        confirmation = _confirmation(source_bill, attempt.credential)
        assert (
            run_bill_enhancement_attempt(attempt.pk, attempt.dispatch_token)["status"]
            == "outcome_unknown"
        )
        estimate = client.get(url + "estimate/").data
        assert not estimate["can_enhance"]
        assert estimate["unavailable_reason"] == "reconciliation_required"
        assert not estimate["matching_enhancement"]["latest_attempt"]["retry_allowed"]
        retry = client.post(
            url + f"{attempt.enhancement_id}/retry/", confirmation, format="json"
        )
        assert retry.status_code == 409 and "reconciliation_required" in str(retry.data)
        assert (
            attempt.enhancement.attempts.count()
            == provider.enhance_bill.call_count
            == 1
        )
        reservation = BillEnhancementCallCache.objects.get(status="dispatching")
        reservation.status = "failed"  # Simulate a reconciled, known failure.
        reservation.save()
        assert client.get(url + "estimate/").data["matching_enhancement"][
            "latest_attempt"
        ]["retry_allowed"]


@pytest.mark.django_db
def test_pending_salted_call_blocks_fresh_generation(
    source_bill, enhancement_owner, enhancement_settings
):
    from hashlib import sha256
    from unittest.mock import Mock

    from apps.legislation.enhancements.reader_cache import call_identity
    from apps.legislation.models import BillEnhancementCallCache

    install_reader(source_bill)
    with enhancement_settings:
        attempt = _pending_attempt(enhancement_owner, source_bill)
        attempt.status, attempt.run_token, attempt.lease_expires_at = (
            "running",
            "lease",
            timezone.now() + timedelta(minutes=1),
        )
        attempt.save()
        attempt.enhancement.rerun_after = 9
        attempt.enhancement.save()
        request = build_enhancement_preflight(source_bill)
        identity, _ = call_identity(request)
        prior = BillEnhancementCallCache.objects.create(
            fingerprint=sha256(f"{identity}:rerun:8".encode()).hexdigest(),
            dispatch_identity=identity,
            status="dispatching",
        )
        provider = Mock()
        with pytest.raises(ProviderError) as error:
            DurableReaderProvider(provider, attempt, "lease", 4).enhance_bill(
                api_key="offline", request=request, timeout_seconds=1
            )
        assert error.value.citation_resolution["blocked_reservation"] == prior.pk
        provider.enhance_bill.assert_not_called()


def test_cache_reference_remapping_does_not_edit_prose():
    from apps.legislation.enhancements.reader_cache import remap

    assert remap(
        {"text": "The name src_0042 appears in the source.", "source_ref": "src_0042"},
        {"src_0042": "src_0001"},
    ) == {"text": "The name src_0042 appears in the source.", "source_ref": "src_0001"}


@pytest.mark.django_db
@pytest.mark.parametrize("mismatch", [False, True])
def test_free_router_model_is_pinned_across_deliveries_and_completed_calls_reused(
    source_bill, enhancement_owner, enhancement_settings, mismatch
):
    import copy

    install_reader(source_bill, count=0)
    with enhancement_settings:
        p = build_enhancement_preflight(source_bill)
        refs = {s["source_ref"] for s in p.request_envelope["source_packet"]["sources"]}
        p = replace(
            p,
            provider="openrouter",
            requested_model="openrouter/free",
            source_snapshot=[s for s in p.source_snapshot if s["source_ref"] in refs],
        )
        a = _pending_attempt(enhancement_owner, source_bill)
        a.status, a.run_token, a.lease_expires_at = (
            "running",
            "run",
            timezone.now() + timedelta(minutes=10),
        )
        a.save()
        seen = []

        class Provider:
            def enhance_bill(self, *, request, **kwargs):
                seen.append(request.requested_model)
                return ProviderResult(
                    {
                        "schema_version": "1.4",
                        "explanations": [],
                        "summary": [
                            {
                                "text": "Requires a report.",
                                "source_quotes": [
                                    {
                                        "source_ref": p.source_snapshot[0][
                                            "source_ref"
                                        ],
                                        "quote_id": "p0001",
                                    }
                                ],
                            }
                        ],
                    },
                    ProviderUsage(10, 5, 15),
                    "response",
                    (
                        "other/model:free"
                        if mismatch and len(seen) == 2
                        else "fixture/model:free"
                    ),
                )

        DurableReaderProvider(Provider(), a, "run", 4).enhance_bill(
            api_key="offline", request=p, timeout_seconds=1
        )
        a.refresh_from_db()
        # A new worker delivery must not forget the selected model.
        second = copy.deepcopy(p.request_envelope)
        second["instructions"] += "\nKeep the explanation short."
        next_request = replace(p, request_envelope=second)
        wrapper = DurableReaderProvider(Provider(), a, "run", 4)
        if mismatch:
            with pytest.raises(ProviderError) as error:
                wrapper.enhance_bill(
                    api_key="offline", request=next_request, timeout_seconds=1
                )
            assert error.value.validation_code == "pinned_model_changed"
            assert a.steps.order_by("step_index").last().status == "failed"
        else:
            wrapper.enhance_bill(
                api_key="offline", request=next_request, timeout_seconds=1
            )
        cached = wrapper.enhance_bill(api_key="offline", request=p, timeout_seconds=1)
        assert seen == ["openrouter/free", "fixture/model:free"]
        assert cached.usage.total_tokens == 0
        assert a.steps.count() == 2


@pytest.mark.django_db
def test_empty_summary_is_not_saved_as_reusable_success(
    source_bill, enhancement_owner, enhancement_settings
):
    from apps.legislation.models import BillEnhancementCallCache

    install_reader(source_bill, count=0)
    with enhancement_settings:
        p = build_enhancement_preflight(source_bill)
        refs = {s["source_ref"] for s in p.request_envelope["source_packet"]["sources"]}
        p = replace(
            p, source_snapshot=[s for s in p.source_snapshot if s["source_ref"] in refs]
        )
        attempt = _pending_attempt(enhancement_owner, source_bill)
        attempt.status, attempt.run_token = "running", "test"
        attempt.lease_expires_at = timezone.now() + timedelta(minutes=10)
        attempt.save()

        class Provider:
            def enhance_bill(self, **kwargs):
                return ProviderResult(
                    {"schema_version": "1.4", "summary": [], "explanations": []},
                    ProviderUsage(10, 5, 15),
                    "test",
                    "test",
                )

        with pytest.raises(ProviderError) as error:
            DurableReaderProvider(Provider(), attempt, "test", 2).enhance_bill(
                api_key="offline", request=p, timeout_seconds=1
            )
        assert error.value.validation_code == "reader_coverage_incomplete"
        assert BillEnhancementCallCache.objects.get().status == "failed"
        assert attempt.steps.get().status == "failed"


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("crash", [False, True, "legacy_cache", "legacy_crash"])
def test_reader_step_persists_success_and_never_blindly_replays_a_dispatch(
    source_bill, enhancement_owner, enhancement_settings, crash
):
    install_reader(source_bill)
    with enhancement_settings:
        p = build_enhancement_preflight(source_bill)
        refs = {s["source_ref"] for s in p.request_envelope["source_packet"]["sources"]}
        p = replace(
            p, source_snapshot=[s for s in p.source_snapshot if s["source_ref"] in refs]
        )
        a = _pending_attempt(enhancement_owner, source_bill)
        a.status, a.run_token, a.lease_expires_at = (
            "running",
            "run",
            timezone.now() + timedelta(minutes=10),
        )
        a.save()

        class Provider:
            calls = 0

            def enhance_bill(self, **kwargs):
                self.calls += 1
                if crash is True or crash == "legacy_crash":
                    raise KeyboardInterrupt("simulate process death after dispatch")
                return ProviderResult(
                    {
                        "schema_version": "1.4",
                        "summary": [
                            {
                                "text": "Requires a report.",
                                "source_quotes": [
                                    {
                                        "source_ref": p.source_snapshot[0][
                                            "source_ref"
                                        ],
                                        "quote_id": "p0001",
                                    }
                                ],
                            }
                        ],
                        "explanations": [],
                    },
                    ProviderUsage(10, 5, 15),
                    "response",
                    "test",
                )

        real = Provider()
        wrapper = DurableReaderProvider(real, a, "run", 2)
        if crash is True or crash == "legacy_crash":
            with pytest.raises(KeyboardInterrupt):
                wrapper.enhance_bill(api_key="test", request=p, timeout_seconds=1)
            if crash == "legacy_crash":
                from apps.legislation.enhancements.reader_cache import call_identity
                from apps.legislation.models import BillEnhancementCallCache

                legacy_key, _ = call_identity(p, execution_version=2)
                BillEnhancementCallCache.objects.update(fingerprint=legacy_key)
                a.steps.all().delete()  # A later attempt has only the shared reservation.
            with pytest.raises(ProviderError) as error:
                wrapper.enhance_bill(api_key="test", request=p, timeout_seconds=1)
            assert error.value.outcome_unknown
            if crash == "legacy_crash":
                assert not a.steps.exists()
                assert (
                    BillEnhancementCallCache.objects.get(pk=legacy_key).status
                    == "dispatching"
                )
                from apps.legislation.enhancements.service import retry_allowed

                a.status = "outcome_unknown"
                a.citation_resolution_json = error.value.citation_resolution
                assert not retry_allowed(a)
                BillEnhancementCallCache.objects.filter(pk=legacy_key).update(
                    status="failed"
                )
                assert retry_allowed(a)
            else:
                assert a.steps.get().status == "dispatching"
        else:
            first = wrapper.enhance_bill(api_key="test", request=p, timeout_seconds=1)
            saved = a.steps.get()
            assert saved.status == "validated" and saved.result_json == first.output
            if crash == "legacy_cache":
                from apps.legislation.enhancements.reader_cache import call_identity
                from apps.legislation.models import BillEnhancementCallCache

                old_key, _ = call_identity(p, execution_version=2)
                BillEnhancementCallCache.objects.update(fingerprint=old_key)
                a.steps.all().delete()  # A new run has no old step reservation.
            second = wrapper.enhance_bill(api_key="test", request=p, timeout_seconds=1)
            assert second.output == first.output and second.usage.total_tokens == 0
            assert second.resolved_model == first.resolved_model
            from apps.legislation.enhancements.source_first_worker import step_usage

            assert step_usage(a.pk).total_tokens == (
                0 if crash == "legacy_cache" else 15
            )
        assert real.calls == 1


@pytest.mark.django_db(transaction=True)
def test_completed_source_call_reused_across_attempts_and_shifted_document_offsets(
    source_bill, enhancement_owner, enhancement_settings
):
    import copy

    from apps.legislation.enhancements.reader_discovery import (
        discovery_schema,
        discovery_sources,
    )

    install_reader(source_bill)
    with enhancement_settings:
        p = build_enhancement_preflight(source_bill)
        source = discovery_sources(
            "SEC. 1. Grants\nThe Secretary shall provide $100 for school grants.", 1
        )[0]
        envelope = {
            "source_review": True,
            "output_schema": discovery_schema([source]),
            "source_packet": {"sources": [source]},
        }
        p = replace(p, source_snapshot=[source], request_envelope=envelope)
        a = _pending_attempt(enhancement_owner, source_bill)
        a.status, a.run_token, a.lease_expires_at = (
            "running",
            "run",
            timezone.now() + timedelta(minutes=10),
        )
        a.save()

        class Provider:
            calls = 0

            def enhance_bill(self, **kwargs):
                self.calls += 1
                return ProviderResult(
                    {
                        "financial_items": [
                            {
                                "label": "Grant",
                                "amount_display": "$100",
                                "text": "Provides $100 for school grants.",
                                "fiscal_years": [],
                                "source_quotes": [
                                    {"source_ref": "src_0001", "quote_id": "p0001"}
                                ],
                            }
                        ],
                        "additional_changes": [],
                        "money_checks": {"src_0001:p0001": "financial"},
                    },
                    ProviderUsage(10, 5, 15),
                    "response",
                    "test",
                )

        provider = Provider()
        first = DurableReaderProvider(provider, a, "run", 2).enhance_bill(
            api_key="test", request=p, timeout_seconds=1
        )
        a.status = "failed"
        a.save()
        a.enhancement.status = "failed"
        a.enhancement.save()
        from django.contrib.auth import get_user_model

        other_user = get_user_model().objects.create_user(username="other-reader")
        b = _pending_attempt(other_user, source_bill)
        assert b.enhancement.user_id != a.enhancement.user_id
        b.status, b.run_token = "running", "other"
        b.lease_expires_at = timezone.now() + timedelta(minutes=10)
        b.save()
        shifted = copy.deepcopy(source)
        shifted.update(
            source_ref="src_0042",
            start_char=1000,
            end_char=1000 + len(source["quoted_text"]),
        )
        changed_envelope = {
            "source_review": True,
            "output_schema": discovery_schema([shifted]),
            "source_packet": {"sources": [shifted]},
        }
        newer = replace(p, source_snapshot=[shifted], request_envelope=changed_envelope)
        second = DurableReaderProvider(provider, b, "other", 2).enhance_bill(
            api_key="different-user-key", request=newer, timeout_seconds=1
        )
        assert provider.calls == 1
        assert second.usage.total_tokens == 0
        assert (
            second.output["financial_items"][0]["source_quotes"][0]["source_ref"]
            == "src_0042"
        )
        assert (
            second.output["financial_items"][0]["text"]
            == first.output["financial_items"][0]["text"]
        )


@pytest.mark.django_db
def test_usage_query_does_not_load_saved_responses(
    source_bill, enhancement_owner, enhancement_settings, django_assert_num_queries
):
    from apps.legislation.enhancements.source_first_worker import step_usage
    from apps.legislation.models import BillEnhancementStep

    with enhancement_settings:
        a = _pending_attempt(enhancement_owner, source_bill)
    BillEnhancementStep.objects.create(
        attempt=a,
        step_index=0,
        stage="reader",
        request_fingerprint="test",
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        result_json={"large": "x" * 100000},
    )
    with django_assert_num_queries(1) as captured:
        assert step_usage(a.pk).total_tokens == 15
    assert "result_json" not in captured.captured_queries[0]["sql"]
    BillEnhancementStep.objects.create(
        attempt=a, step_index=1, stage="reader", request_fingerprint="unknown"
    )
    assert step_usage(a.pk).total_tokens is None


@pytest.mark.django_db(transaction=True)
def test_concurrent_users_reserve_only_one_paid_call(
    source_bill, enhancement_owner, enhancement_settings
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from django.contrib.auth import get_user_model
    from django.db import close_old_connections, connection

    from apps.legislation.models import BillEnhancement, BillEnhancementAttempt

    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL unique-key concurrency")
    install_reader(source_bill)
    with enhancement_settings:
        p = build_enhancement_preflight(source_bill)
        refs = {s["source_ref"] for s in p.request_envelope["source_packet"]["sources"]}
        p = replace(
            p, source_snapshot=[s for s in p.source_snapshot if s["source_ref"] in refs]
        )
        a = _pending_attempt(enhancement_owner, source_bill)
        a.status, a.run_token, a.lease_expires_at = (
            "running",
            "first",
            timezone.now() + timedelta(minutes=10),
        )
        a.save()
        other = get_user_model().objects.create_user(username="concurrent-reader")
        enhancement = BillEnhancement.objects.get(pk=a.enhancement_id)
        enhancement.pk, enhancement.user = None, other
        enhancement.save()
        b = BillEnhancementAttempt.objects.get(pk=a.pk)
        b.pk, b.enhancement, b.run_token = None, enhancement, "second"
        b.save()
        entered, finish = Event(), Event()

        class Provider:
            calls = 0

            def enhance_bill(self, **kwargs):
                self.calls += 1
                entered.set()
                assert finish.wait(10)
                return ProviderResult(
                    {
                        "schema_version": "1.4",
                        "explanations": [],
                        "summary": [
                            {
                                "text": "Requires a report.",
                                "source_quotes": [
                                    {
                                        "source_ref": p.source_snapshot[0][
                                            "source_ref"
                                        ],
                                        "quote_id": "p0001",
                                    }
                                ],
                            }
                        ],
                    },
                    ProviderUsage(10, 5, 15),
                    "response",
                    "test",
                )

        provider = Provider()

        def run():
            close_old_connections()
            try:
                return DurableReaderProvider(provider, a, "first", 2).enhance_bill(
                    api_key="test", request=p, timeout_seconds=1
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run)
            try:
                assert entered.wait(10)
                with pytest.raises(ProviderError) as error:
                    DurableReaderProvider(provider, b, "second", 2).enhance_bill(
                        api_key="test", request=p, timeout_seconds=1
                    )
                assert error.value.outcome_unknown
            finally:
                finish.set()
            assert future.result(timeout=10).usage.total_tokens == 15
        reused = DurableReaderProvider(provider, b, "second", 2).enhance_bill(
            api_key="test", request=p, timeout_seconds=1
        )
        assert reused.usage.total_tokens == 0 and provider.calls == 1
