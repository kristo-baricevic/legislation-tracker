"""Model pinning and explicit selection can send identical OpenRouter HTTP bodies."""

# ruff: noqa: F401, F811
import hashlib
import json
from copy import copy
from dataclasses import replace

import httpx
import pytest

from apps.legislation.enhancements.provider_registry import get_provider
from apps.legislation.enhancements.providers.base import ProviderError
from apps.legislation.enhancements.reader_steps import DurableReaderProvider
from apps.legislation.enhancements.source_packet import canonical_json_bytes
from apps.legislation.models import BillEnhancementCallCache

from .test_dependency_cache_identity import _running_attempt
from .test_dependency_cache_migration import CAPTURE, _current_request
from .test_enhancement_service import (
    enhancement_owner,
    enhancement_settings,
    source_bill,
)

ALIAS = "openrouter/free"
PIN = "fixture/model:free"
OTHER = "fixture/other:free"


def _select(request, model):
    return replace(
        request,
        requested_model=model,
        request_envelope={**request.request_envelope, "requested_model": model},
    )


def _pre_upgrade_key(request, adapter):
    # Verbatim dispatch preimage from 5d3cb4b. It stored the logical alias,
    # even when the SDK received a concrete, pinned free model.
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "dispatch": request.request_envelope,
                "provider": request.provider,
                "model": request.requested_model,
                "reasoning": request.reasoning_effort,
                "adapter": adapter,
            }
        )
    ).hexdigest()


@pytest.mark.django_db
@pytest.mark.parametrize("adapter", ["existing", "langchain"])
@pytest.mark.parametrize(
    "historical,orphan,next_model,additional",
    [
        (False, False, PIN, 0),
        (False, True, PIN, 0),
        (False, True, OTHER, 1),
        (True, False, PIN, 0),
        (True, False, OTHER, 1),
        (True, True, PIN, 0),
        # An old alias-only row lost its step. Even a salted primary key cannot
        # establish which concrete model was called; keep its outcome fenced.
        (True, True, OTHER, 0),
        (True, "conflicting_step", OTHER, 0),
        (True, "unrecorded_model", OTHER, 0),
        # The opposite direction addresses the same operation too.
        (True, False, ALIAS, 0),
        (False, True, ALIAS, 0),
    ],
)
def test_pinned_timeout_then_explicit_model(
    settings,
    monkeypatch,
    source_bill,
    enhancement_owner,
    enhancement_settings,
    adapter,
    historical,
    orphan,
    next_model,
    additional,
):
    calls = []

    async def timeout(client, request, **kwargs):
        calls.append(json.loads(request.content))
        raise httpx.ReadTimeout("response lost after dispatch", request=request)

    monkeypatch.setattr(httpx.AsyncClient, "send", timeout)
    with enhancement_settings:
        first = _running_attempt(enhancement_owner, source_bill)
        first.pinned_model = PIN if next_model != ALIAS else ""
        first.execution_config = {**first.execution_config, "adapter": adapter}
        first.save()
        first.enhancement.rerun_after = 22
        first.enhancement.save(update_fields=["rerun_after"])
        request = _select(
            _current_request(settings, next(iter(CAPTURE["cases"])), "openrouter"),
            ALIAS if next_model != ALIAS else PIN,
        )
        sdk = get_provider("openrouter", adapter=adapter)
        with pytest.raises(ProviderError) as original:
            DurableReaderProvider(sdk, first, first.run_token, 4).enhance_bill(
                api_key="offline", request=request, timeout_seconds=2
            )
        assert original.value.outcome_unknown
        assert [call["model"] for call in calls] == [PIN]
        assert "requested_model" not in calls[0]
        step = first.steps.get()
        reservation = BillEnhancementCallCache.objects.get(pk=step.request_fingerprint)
        assert reservation.status == "dispatching"
        if historical:
            reservation.dispatch_identity = _pre_upgrade_key(request, adapter)
            reservation.save(update_fields=["dispatch_identity"])
        if orphan is True:
            step.delete()
        elif orphan in ("conflicting_step", "unrecorded_model"):
            # Historical rows are shared. One mismatching step must not hide
            # another matching (or unidentifiable) dispatch with this key.
            extra = copy(step)
            extra.pk = None
            extra.step_index += 1
            extra.diagnostics = (
                {"requested_model": OTHER} if orphan == "conflicting_step" else {}
            )
            extra.save(force_insert=True)
        type(first).objects.filter(pk=first.pk).update(status="outcome_unknown")
        second = copy(first)
        second.pk = None
        second.sequence += 1
        second.pinned_model = PIN if next_model == ALIAS else ""
        second.save(force_insert=True)
        with pytest.raises(ProviderError) as retry:
            DurableReaderProvider(sdk, second, second.run_token, 4).enhance_bill(
                api_key="offline",
                request=_select(request, next_model),
                timeout_seconds=2,
            )
        assert retry.value.outcome_unknown
        assert len(calls) == 1 + additional, [call["model"] for call in calls]
        if additional:
            assert calls[1] == {**calls[0], "model": OTHER}
        else:
            assert (
                retry.value.citation_resolution["blocked_reservation"] == reservation.pk
            )
        assert second.steps.count() == additional
        reservation.refresh_from_db()
        assert reservation.status == "dispatching"
