"""Truncated reconciliation recovers through the real durable worker path."""

from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.legislation.enhancements.providers.base import ProviderError, ProviderUsage
from apps.legislation.enhancements.reader_cache import call_identity
from apps.legislation.models import BillEnhancementCallCache
from apps.legislation.tasks import (
    recover_stale_bill_enhancement_attempts,
    run_bill_enhancement_attempt,
)
from apps.legislation.tests.test_enhancement_service import _valid_credential
from apps.legislation.tests.test_large_bill_planning_regression import _stored_document
from apps.legislation.tests.test_large_bill_staged_flow import (
    RecordedModel,
    SimulatedWorkerCrash,
    _confirmation,
    _cross_section_source,
)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("mode", ["complete", "retry", "crash"])
def test_truncated_dependency_does_not_poison_durable_run(
    tmp_path, enhancement_owner, enhancement_settings, monkeypatch, mode
):
    class Model(RecordedModel):
        def __init__(self):
            super().__init__()
            self.truncated = []
            self.transient_failures = []

        def enhance_bill(self, *, request, **kwargs):
            if request.request_envelope.get("dependency_review") and not self.truncated:
                self.truncated.append(request)
                assert (
                    len(request.request_envelope["dependency_review"]["record_ids"]) > 1
                )
                limit = request.request_envelope["max_output_tokens"]
                raise ProviderError(
                    "invalid_output",
                    validation_code="provider_output_limit",
                    usage=ProviderUsage(100, limit, 100 + limit),
                )
            if (
                mode == "retry"
                and request.request_envelope.get("dependency_review")
                and not self.transient_failures
            ):
                self.transient_failures.append(request)
                raise ProviderError(
                    "provider_unavailable",
                    retry_allowed=True,
                    usage=ProviderUsage(0, 0, 0),
                )
            return super().enhance_bill(request=request, **kwargs)

    model = Model()
    monkeypatch.setattr("apps.legislation.tasks.get_provider", lambda _: model)

    def forbid_network(*args, **kwargs):
        pytest.fail("The dependency recovery test attempted a real HTTP request")

    monkeypatch.setattr("httpx.Client.send", forbid_network)
    monkeypatch.setattr("requests.sessions.Session.request", forbid_network)
    client = APIClient()
    client.force_authenticate(enhancement_owner)
    with (
        enhancement_settings,
        override_settings(
            STORAGES={
                "default": {
                    "BACKEND": "django.core.files.storage.FileSystemStorage",
                    "OPTIONS": {"location": tmp_path},
                }
            },
            LLM_READER_OWNED_TOKEN_TARGET=0,
            LLM_SOURCE_FIRST_ENABLED=False,
            LLM_READER_MAX_CALLS=0,
            LLM_READER_CALLS_PER_DELIVERY=500,
        ),
    ):
        document = _stored_document(_cross_section_source(), tmp_path, number="S 99996")
        _valid_credential(enhancement_owner)
        attempt = _confirmation(client, document.bill)
        model.attempt = attempt
        cached_dependency_key = None
        if mode == "crash":
            from apps.legislation.enhancements.reader_steps import DurableReaderProvider

            dispatch = DurableReaderProvider.enhance_bill

            def crash_after_validated_dependency(self, *, request, **kwargs):
                nonlocal cached_dependency_key
                result = dispatch(self, request=request, **kwargs)
                if (
                    request.request_envelope.get("dependency_review")
                    and cached_dependency_key is None
                ):
                    cached_dependency_key = call_identity(request)[0]
                    assert (
                        BillEnhancementCallCache.objects.get(
                            pk=cached_dependency_key
                        ).status
                        == "validated"
                    )
                    raise SimulatedWorkerCrash()
                return result

            monkeypatch.setattr(
                DurableReaderProvider, "enhance_bill", crash_after_validated_dependency
            )
            with pytest.raises(SimulatedWorkerCrash):
                run_bill_enhancement_attempt(attempt.pk, attempt.dispatch_token)
            attempt.refresh_from_db()
            attempt.lease_expires_at = timezone.now() - timedelta(seconds=1)
            attempt.save(update_fields=["lease_expires_at"])
            recover_stale_bill_enhancement_attempts()
        elif mode == "retry":
            outcome = run_bill_enhancement_attempt(attempt.pk, attempt.dispatch_token)
            attempt.refresh_from_db()
            assert outcome["status"] == "failed", attempt.failure_detail
            assert attempt.failure_category == "provider_unavailable"

        if mode != "complete":
            mapped_keys = {key for stage, key, _ in model.calls if stage == "map"}
            assert mapped_keys
            assert len(model.truncated) == 1
            attempt = _confirmation(client, document.bill, attempt.enhancement_id)
            model.attempt = attempt

        outcome = run_bill_enhancement_attempt(attempt.pk, attempt.dispatch_token)
        attempt.refresh_from_db()
        attempt.enhancement.refresh_from_db()
        assert outcome["status"] == "succeeded", attempt.failure_detail
        assert len(model.truncated) == 1
        if mode != "complete":
            assert {
                key for stage, key, _ in model.calls if stage == "map"
            } == mapped_keys
        if cached_dependency_key is not None:
            assert sum(key == cached_dependency_key for _, key, _ in model.calls) == 1
        failed_key, _ = call_identity(model.truncated[0])
        assert (
            BillEnhancementCallCache.objects.get(pk=failed_key).diagnostic_code
            == "provider_output_limit"
        )
        assert all(key != failed_key for _, key, _ in model.calls)
        result = attempt.enhancement.result_json
        assert "50 percent" in result["summary"][0]["text"]
        grant = next(
            item
            for item in result["source_review"].get(
                "policy_drafts", result["source_review"]["policy_changes"]
            )
            if "award grants" in item["text"].lower()
        )
        assert "50 percent" in grant["text"]
        assert any("50 percent" in quote["quote"] for quote in grant["source_quotes"])
