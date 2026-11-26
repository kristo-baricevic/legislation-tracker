"""Corrected dependency transport invalidates failures without repeating map calls."""

# ruff: noqa: F401, F811
import copy
import hashlib
from dataclasses import replace
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.legislation.enhancements.providers.base import ProviderError
from apps.legislation.enhancements.reader_cache import call_identity
from apps.legislation.enhancements.reader_steps import DurableReaderProvider
from apps.legislation.enhancements.source_packet import canonical_json_bytes
from apps.legislation.models import BillEnhancementCallCache, BillEnhancementStep

from .test_dependency_provider_adapters import (
    _sdk_provider,
    _sdk_response,
    dependency_request,
)
from .test_enhancement_service import (
    enhancement_owner,
    enhancement_settings,
    source_bill,
)
from .test_enhancement_tasks import _pending_attempt
from .test_reader_enhancement_pipeline import install_reader
from .test_reader_reconciliation import Provider


def _old_identity(request, *, execution_version=3, adapter="existing"):
    """The pre-fix key format, given already normalized source-review inputs."""
    key = {
        "validator_version": 2,
        "execution_version": execution_version,
        "envelope": request.request_envelope,
        "sources": request.source_snapshot,
        "model": request.requested_model,
        "provider": request.provider,
        "reasoning": request.reasoning_effort,
    }
    if adapter != "existing":
        key["adapter"] = adapter
    return hashlib.sha256(canonical_json_bytes(key)).hexdigest()


def _running_attempt(owner, bill):
    install_reader(bill, count=0)
    attempt = _pending_attempt(owner, bill)
    attempt.status = "running"
    attempt.run_token = "dependency-lease"
    attempt.lease_expires_at = timezone.now() + timedelta(minutes=10)
    attempt.save()
    return attempt


@pytest.mark.django_db
@pytest.mark.parametrize("code", ["schema_required", "provider_output_limit"])
def test_old_failed_dependency_dispatch_does_not_poison_corrected_transport(
    settings, source_bill, enhancement_owner, enhancement_settings, code
):
    with enhancement_settings:
        attempt = _running_attempt(enhancement_owner, source_bill)
        request = dependency_request(settings)
        old_key = _old_identity(request)
        old_cache = BillEnhancementCallCache.objects.create(
            fingerprint=old_key,
            dispatch_identity=old_key,
            status="failed",
            diagnostic_code=code,
        )
        BillEnhancementStep.objects.create(
            attempt=attempt,
            step_index=0,
            stage="reader",
            request_fingerprint=old_key,
            status="failed",
            diagnostics={"logical_fingerprint": old_key, "code": code},
            input_tokens=100,
            output_tokens=4000,
            total_tokens=4100,
        )
        output = Provider().enhance_bill(request=request).output
        calls = []
        wrapper = DurableReaderProvider(
            _sdk_provider("openai", _sdk_response(output), calls),
            attempt,
            attempt.run_token,
            4,
        )

        result = wrapper.enhance_bill(
            api_key="offline", request=request, timeout_seconds=1
        )

        assert result.output == output
        assert result.usage.total_tokens == 165
        new_key, _ = call_identity(request)
        assert new_key != old_key
        assert len(calls) == wrapper.paid_calls == 1
        assert wrapper.cache_hits == 0
        assert BillEnhancementCallCache.objects.get(pk=new_key).status == "validated"
        old_cache.refresh_from_db()
        assert old_cache.status == "failed" and old_cache.diagnostic_code == code
        assert attempt.steps.count() == 2

        reused = wrapper.enhance_bill(
            api_key="offline", request=request, timeout_seconds=1
        )
        assert reused.output == output and reused.usage.total_tokens == 0
        assert len(calls) == 1 and wrapper.cache_hits == 1


@pytest.mark.django_db
@pytest.mark.parametrize("execution_version", [2, 3])
@pytest.mark.parametrize("salted", [False, True])
def test_old_ambiguous_dependency_dispatch_still_blocks_api_calls(
    settings,
    source_bill,
    enhancement_owner,
    enhancement_settings,
    execution_version,
    salted,
):
    with enhancement_settings:
        attempt = _running_attempt(enhancement_owner, source_bill)
        request = dependency_request(settings)
        logical_key = _old_identity(request, execution_version=execution_version)
        old_key = (
            hashlib.sha256(f"{logical_key}:rerun:99".encode()).hexdigest()
            if salted
            else logical_key
        )
        reservation = BillEnhancementCallCache.objects.create(
            fingerprint=old_key,
            dispatch_identity=logical_key,
            status="dispatching",
        )
        calls = []
        wrapper = DurableReaderProvider(
            _sdk_provider("openai", None, calls), attempt, attempt.run_token, 4
        )

        with pytest.raises(ProviderError) as error:
            wrapper.enhance_bill(api_key="offline", request=request, timeout_seconds=1)

        assert error.value.outcome_unknown
        assert error.value.citation_resolution["blocked_reservation"] == old_key
        assert not calls and not attempt.steps.exists()
        reservation.refresh_from_db()
        assert reservation.status == "dispatching"


@pytest.mark.parametrize("adapter", ["existing", "langchain"])
def test_map_call_identity_keeps_exact_pre_dependency_fix_format(settings, adapter):
    request = dependency_request(settings)
    source = {
        "source_ref": "src_0042",
        "quoted_text": "Public hospitals may apply for grants.",
        "start_char": 400,
        "end_char": 438,
        "context_source_refs": ["src_0090"],
        "context_quote_ids": {"src_0090": ["p0001"]},
        "dependencies": [{"start": 1200, "end": 1300}],
        "omitted_dependency_ranges": [],
        "review_quote_ids": ["p0001"],
        "factual_map": True,
    }
    envelope = {
        "source_review": True,
        "source_packet": {"sources": [copy.deepcopy(source)]},
        "output_schema": {"enum": ["src_0042:p0001"]},
    }
    request = replace(request, request_envelope=envelope, source_snapshot=[source])
    normalized_source = {
        "source_ref": "src_0001",
        "quoted_text": source["quoted_text"],
        "review_quote_ids": ["p0001"],
        "factual_map": True,
    }
    normalized = replace(
        request,
        source_snapshot=[normalized_source],
        request_envelope={
            "source_review": True,
            "source_packet": {"sources": [normalized_source]},
            "output_schema": {"enum": ["src_0001:p0001"]},
        },
    )
    fingerprint, references = call_identity(request, adapter=adapter)

    assert fingerprint == _old_identity(normalized, adapter=adapter)
    assert references == {"src_0042": "src_0001"}


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["record_id", "quote_id", "source_ref"])
@pytest.mark.parametrize("record_id", [[], {"bad": "id"}])
def test_malformed_record_id_is_a_known_paid_response(
    settings, enhancement_owner, source_bill, enhancement_settings, field, record_id
):
    from unittest.mock import Mock

    from apps.legislation.enhancements.providers.base import (
        ProviderResult,
        ProviderUsage,
    )
    from apps.legislation.enhancements.reader_discovery import discovery_schema

    from .test_dependency_cache_migration import _stage_request
    from .test_reader_facts import _output, _sources

    with enhancement_settings:
        attempt = _running_attempt(enhancement_owner, source_bill)
        base = _stage_request(settings, "map")
        sources = _sources("The agency shall publish an annual report.")
        sources[0]["review_quote_ids"] = ["p0001"]
        request = replace(
            base,
            source_snapshot=sources,
            request_envelope={
                **base.request_envelope,
                "source_review": True,
                "output_schema": discovery_schema(sources),
            },
        )
        output = _output(sources)
        if field == "record_id":
            output["factual_records"][0][field] = record_id
        else:
            output["policy_changes"][0]["source_quotes"][0][field] = record_id
        provider = Mock()
        provider.enhance_bill.return_value = ProviderResult(
            output, ProviderUsage(100, 50, 150), "known-response", "model"
        )
        wrapper = DurableReaderProvider(provider, attempt, attempt.run_token, 4)
        for _ in range(2):
            with pytest.raises(ProviderError) as failure:
                wrapper.enhance_bill(
                    request=request, api_key="offline", timeout_seconds=1
                )
            assert not failure.value.outcome_unknown
        step = attempt.steps.get()
        assert (step.status, step.total_tokens, step.response_id) == (
            "failed",
            150,
            "known-response",
        )
        cache = BillEnhancementCallCache.objects.get(pk=step.request_fingerprint)
        assert cache.status == "failed" and cache.response_id == step.response_id
        assert provider.enhance_bill.call_count == 1
