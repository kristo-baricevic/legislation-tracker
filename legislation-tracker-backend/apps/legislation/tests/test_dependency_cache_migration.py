"""Migration tests use requests/keys captured by a complete 563c64c checkout.

The JSON fixture records the exact commit and builder/cache file hashes. Its
planned case also ran that revision's planned_sources(), not today's planner
with its version field edited. No historical Python or git checkout is needed
to run these regressions.
"""

# ruff: noqa: F401, F811
import copy
import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.legislation.enhancements.providers.base import ProviderError
from apps.legislation.enhancements.reader_batches import reader_execution_settings
from apps.legislation.enhancements.reader_cache import call_identity, remap
from apps.legislation.enhancements.reader_chunking import planned_sources
from apps.legislation.enhancements.reader_reconciliation import _request
from apps.legislation.enhancements.reader_steps import DurableReaderProvider
from apps.legislation.enhancements.source_packet import canonical_json_bytes
from apps.legislation.enhancements.types import EnhancementPreflight
from apps.legislation.models import (
    BillEnhancement,
    BillEnhancementAttempt,
    BillEnhancementCallCache,
    BillEnhancementStep,
)

from .test_dependency_cache_identity import _running_attempt
from .test_dependency_provider_adapters import _sdk_provider, _sdk_response
from .test_enhancement_service import (
    enhancement_owner,
    enhancement_settings,
    source_bill,
)

CAPTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "dependency_cache_563c64c.json").read_text()
)
VARIANTS = [
    ("openai", "existing", False, False),
    ("openai", "langchain", True, False),
    ("anthropic", "existing", True, False),
    ("gemini", "langchain", False, False),
    ("openrouter", "existing", False, False),
    ("openrouter", "langchain", True, True),
]


def _decode(value):
    value = copy.deepcopy(value)
    return EnhancementPreflight(
        **value, request_bytes=canonical_json_bytes(value["request_envelope"])
    )


def _current_request(
    settings,
    name,
    provider="openai",
    *,
    replan=False,
    renumber=False,
    record_index=None,
):
    settings.LLM_READER_MAX_OUTPUT_TOKENS = 24000
    settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES = 100000
    settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS = 100000
    settings.LLM_READER_MODEL_CAPACITIES = {
        f"{p}/{m}": {
            "context_tokens": 100000,
            "output_tokens": 24000,
            "visible_fraction": 0.5,
        }
        for p, m in (
            ("openai", "model"),
            ("anthropic", "model"),
            ("gemini", "model"),
            ("openrouter", "openrouter/free"),
            ("openrouter", "fixture/model:free"),
        )
    }
    case = copy.deepcopy(CAPTURE["cases"][name])
    build = case["build"]
    preflight = _decode(build.pop("preflight"))
    preflight = replace(
        preflight,
        source_manifest={
            **preflight.source_manifest,
            "execution_settings": reader_execution_settings(),
        },
    )
    if record_index is not None:
        build["record_ids"] = [build["record_ids"][record_index]]
    if replan:
        planning = case["planning"]
        sources = planned_sources(
            SimpleNamespace(version_label=planning["version_label"]),
            planning["text"],
            planning["first_ref"],
            planning["target"],
            (),
        )
        for source in sources:
            source.update(factual_map=True, policy_review=True)
        preflight = replace(preflight, source_snapshot=sources)
    if renumber:
        references = {
            source["source_ref"]: f"src_{index + 100:04d}"
            for index, source in enumerate(preflight.source_snapshot)
        }
        preflight = replace(
            preflight, source_snapshot=remap(preflight.source_snapshot, references)
        )
        build = remap(build, references)
    model = "openrouter/free" if provider == "openrouter" else "model"
    return _request(
        replace(preflight, provider=provider, requested_model=model), **build
    )


def _response(request):
    envelope = request.request_envelope
    items = {
        key: copy.deepcopy(item["value"])
        for key, item in envelope["source_packet"]["review_items"].items()
    }
    for key, item in items.items():
        if key.startswith("financial_items:") and len(item["text"]) > 1600:
            item["text"] = None
    return {
        "page_id": envelope["dependency_review"]["page_id"],
        "items": items,
        "record_checks": {
            key: {
                "status": "not_applicable",
                "item_ids": [],
                "reason": "The supplied record does not change this item.",
            }
            for key in envelope["dependency_review"]["record_ids"]
        },
    }


def _legacy_cache(
    name,
    provider,
    adapter,
    version,
    *,
    salted=False,
    pinned=False,
    status="dispatching",
):
    model = "openrouter/free" if provider == "openrouter" else "model"
    identities = CAPTURE["cases"][name]["identities"]
    logical = identities[f"{provider}|{model}|{adapter}|{version}"]
    dispatch_model = "fixture/model:free" if pinned else model
    fingerprint = identities[f"{provider}|{dispatch_model}|{adapter}|{version}"]
    if salted:
        fingerprint = hashlib.sha256(f"{fingerprint}:rerun:99".encode()).hexdigest()
    return BillEnhancementCallCache.objects.create(
        fingerprint=fingerprint,
        dispatch_identity=logical,
        status=status,
        diagnostic_code="provider_output_limit" if status == "failed" else "",
    )


def _prior_step(
    current,
    reservation,
    name,
    provider,
    *,
    pinned=False,
    mismatch=None,
    reader_version=None,
    active=False,
):
    old = CAPTURE["cases"][name]["request"]
    manifest = copy.deepcopy(old["source_manifest"])
    if reader_version == "missing":
        manifest.pop("execution_settings", None)
    elif reader_version is not None:
        manifest.setdefault("execution_settings", {})[
            "reader_execution_version"
        ] = reader_version
    if mismatch == "document":
        manifest["document_content_hash"] = "different-document-version"
    historical = BillEnhancement.objects.create(
        user=current.enhancement.user,
        bill=current.enhancement.bill,
        provider="other-provider" if mismatch == "provider" else provider,
        requested_model=(
            "other-model"
            if mismatch == "model"
            else "openrouter/free" if provider == "openrouter" else "model"
        ),
        reasoning_effort="none",
        prompt_version=old["prompt_version"],
        output_schema_version="1.4",
        source_packet_version=old["source_packet_version"],
        source_fingerprint="legacy-source",
        request_fingerprint=hashlib.sha256(reservation.pk.encode()).hexdigest(),
        source_manifest_json=manifest,
        source_snapshot_json=old["source_snapshot"],
        status="running" if active else "outcome_unknown",
    )
    attempt = BillEnhancementAttempt.objects.create(
        enhancement=historical,
        sequence=1,
        credential=current.credential,
        credential_revision=current.credential_revision,
        status="running" if active else "outcome_unknown",
        available_at=timezone.now(),
        lease_expires_at=timezone.now() + timedelta(minutes=10) if active else None,
        estimated_input_tokens=0,
        pinned_model="fixture/model:free" if pinned else "",
    )
    BillEnhancementStep.objects.create(
        attempt=attempt,
        step_index=0,
        stage="reader",
        request_fingerprint=reservation.pk,
        status="dispatching" if active else "failed",
        diagnostics={"logical_fingerprint": reservation.dispatch_identity},
    )


def _wrapper(attempt, request, provider, adapter, pinned):
    attempt.execution_config = {**attempt.execution_config, "adapter": adapter}
    if pinned:
        attempt.pinned_model = "fixture/model:free"
    attempt.save()
    response = _sdk_response(_response(request))
    if provider == "openrouter":
        response.model = response.model_version = "fixture/model:free"
    calls = []
    return (
        DurableReaderProvider(
            _sdk_provider(provider, response, calls), attempt, attempt.run_token, 4
        ),
        calls,
    )


@pytest.mark.django_db
@pytest.mark.parametrize("name", ["policy", "financial", "retained_remapped"])
@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("provider,adapter,salted,pinned", VARIANTS)
def test_genuine_legacy_orphan_reservation_blocks_corrected_adapter(
    settings,
    source_bill,
    enhancement_owner,
    enhancement_settings,
    name,
    version,
    provider,
    adapter,
    salted,
    pinned,
):
    with enhancement_settings:
        attempt = _running_attempt(enhancement_owner, source_bill)
        request = _current_request(settings, name, provider)
        old = CAPTURE["cases"][name]["request"]["request_envelope"]
        assert request.request_envelope["instructions"] != old["instructions"]
        historical = (
            request.legacy_dependency_request()
            if request.legacy_dependency_request
            else request
        )
        assert (
            historical.request_envelope["dependency_review"] == old["dependency_review"]
        )
        reservation = _legacy_cache(
            name, provider, adapter, version, salted=salted, pinned=pinned
        )
        wrapper, calls = _wrapper(attempt, request, provider, adapter, pinned)

        with pytest.raises(ProviderError) as error:
            wrapper.enhance_bill(api_key="offline", request=request, timeout_seconds=1)

        assert error.value.outcome_unknown
        assert error.value.citation_resolution["blocked_reservation"] == reservation.pk
        assert not calls and not attempt.steps.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("provider,adapter,salted,pinned", VARIANTS)
def test_genuine_planned_history_fences_new_planner_and_source_ids(
    settings,
    source_bill,
    enhancement_owner,
    enhancement_settings,
    version,
    provider,
    adapter,
    salted,
    pinned,
):
    with enhancement_settings:
        attempt = _running_attempt(enhancement_owner, source_bill)
        request = _current_request(
            settings, "planned", provider, replan=True, renumber=True
        )
        old = CAPTURE["cases"]["planned"]["request"]
        assert {s["context_planner_version"] for s in old["source_snapshot"]} == {1}
        assert all(s["context_planner_version"] > 1 for s in request.source_snapshot)
        assert (
            request.request_envelope["dependency_review"]
            != old["request_envelope"]["dependency_review"]
        )
        reservation = _legacy_cache(
            "planned", provider, adapter, version, salted=salted, pinned=pinned
        )
        _prior_step(attempt, reservation, "planned", provider, pinned=pinned)
        wrapper, calls = _wrapper(attempt, request, provider, adapter, pinned)

        with pytest.raises(ProviderError) as error:
            wrapper.enhance_bill(api_key="offline", request=request, timeout_seconds=1)

        assert error.value.outcome_unknown
        assert error.value.citation_resolution["blocked_reservation"] == reservation.pk
        assert not calls and not attempt.steps.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "control", ["failed", "validated", "document", "provider", "model"]
)
def test_historical_fence_does_not_block_known_outcomes_or_unrelated_work(
    settings,
    source_bill,
    enhancement_owner,
    enhancement_settings,
    control,
):
    with enhancement_settings:
        attempt = _running_attempt(enhancement_owner, source_bill)
        request = _current_request(settings, "planned", replan=True, renumber=True)
        reservation = _legacy_cache(
            "planned",
            "openai",
            "existing",
            3,
            status=control if control in {"failed", "validated"} else "dispatching",
        )
        _prior_step(attempt, reservation, "planned", "openai", mismatch=control)
        wrapper, calls = _wrapper(attempt, request, "openai", "existing", False)

        result = wrapper.enhance_bill(
            api_key="offline", request=request, timeout_seconds=1
        )

        assert result.output == _response(request)
        assert len(calls) == wrapper.paid_calls == 1


@pytest.mark.django_db
@pytest.mark.parametrize("reader_version", [11, 12, "missing", 13])
def test_document_history_fence_applies_only_before_the_migration(
    settings,
    source_bill,
    enhancement_owner,
    enhancement_settings,
    reader_version,
):
    with enhancement_settings:
        attempt = _running_attempt(enhancement_owner, source_bill)
        request = _current_request(settings, "planned", replan=True, record_index=0)
        other_page = _current_request(settings, "planned", replan=True, record_index=1)
        assert set(
            request.request_envelope["dependency_review"]["record_ids"]
        ).isdisjoint(other_page.request_envelope["dependency_review"]["record_ids"])
        other_key = call_identity(other_page)[0]
        assert other_key != call_identity(request)[0]
        reservation = BillEnhancementCallCache.objects.create(
            fingerprint=other_key, dispatch_identity=other_key, status="dispatching"
        )
        _prior_step(
            attempt,
            reservation,
            "planned",
            "openai",
            reader_version=reader_version,
            active=True,
        )
        wrapper, calls = _wrapper(attempt, request, "openai", "existing", False)

        if reader_version == 13:
            result = wrapper.enhance_bill(
                api_key="offline", request=request, timeout_seconds=1
            )
            assert result.output == _response(request)
            assert len(calls) == 1
        else:
            with pytest.raises(ProviderError) as error:
                wrapper.enhance_bill(
                    api_key="offline", request=request, timeout_seconds=1
                )
            assert error.value.outcome_unknown
            assert (
                error.value.citation_resolution["blocked_reservation"] == reservation.pk
            )
            assert not calls


@pytest.mark.parametrize("adapter", ["existing", "langchain"])
def test_genuine_legacy_map_identity_remains_unchanged(adapter):
    request = _decode(CAPTURE["map_request"])
    for version in (2, 3):
        expected = CAPTURE["map_identities"][f"openai|model|{adapter}|{version}"]
        assert (
            call_identity(request, execution_version=version, adapter=adapter)[0]
            == expected
        )


def _stage_request(settings, stage):
    from unittest.mock import Mock

    from apps.legislation.enhancements.reader_citations import (
        READER_ID_SCHEMA,
        citation_passages,
    )
    from apps.legislation.enhancements.reader_summary import summarize_review

    if stage == "dependency":
        return _current_request(settings, "planned", replan=True)
    request = _decode(CAPTURE["map_request"])
    if stage == "map":
        return request
    source = request.source_snapshot[0]
    passage = citation_passages(source)[0]
    item = {
        "text": "Public hospitals qualify.",
        "source_quotes": [
            {"source_ref": source["source_ref"], "quote": passage["text"]}
        ],
    }
    preflight = replace(
        request,
        request_envelope={
            "source_packet": {},
            "instructions": "",
            "max_output_tokens": 4000,
            "output_schema": READER_ID_SCHEMA,
        },
    )
    provider = Mock(durable=False)
    provider.enhance_bill.side_effect = RuntimeError("captured summary request")
    with pytest.raises(RuntimeError, match="captured summary request"):
        summarize_review(
            preflight, {"policy_changes": [item]}, provider, "", lambda: None, 1
        )
    return provider.enhance_bill.call_args.kwargs["request"]


@pytest.mark.django_db
@pytest.mark.parametrize("stage", ["map", "dependency", "summary"])
@pytest.mark.parametrize("revision", ["563c64c", "1365612", "acf4eba", "2327c54"])
@pytest.mark.parametrize("status", ["dispatching", "ready", "failed", "validated"])
def test_only_ambiguous_historical_dispatches_block_an_identical_wire_request(
    settings,
    source_bill,
    enhancement_owner,
    enhancement_settings,
    stage,
    revision,
    status,
):
    from unittest.mock import Mock

    with enhancement_settings:
        attempt = _running_attempt(enhancement_owner, source_bill)
        request = _stage_request(settings, stage)

        request = replace(
            request,
            source_snapshot=[
                {**source, "context_planner_version": 5}
                for source in request.source_snapshot
            ],
        )
        # Captured using each revision's planner, request builders and cache code.
        history = json.loads(
            (
                Path(__file__).parent / "fixtures/reader_dispatch_history.json"
            ).read_text()
        )
        old_key = history[revision][stage]
        reservation = BillEnhancementCallCache.objects.create(
            fingerprint=old_key,
            dispatch_identity=old_key,
            status=status,
        )
        provider = Mock()
        provider.enhance_bill.side_effect = ProviderError("test_dispatch")
        wrapper = DurableReaderProvider(provider, attempt, attempt.run_token, 4)
        with pytest.raises(ProviderError) as failure:
            wrapper.enhance_bill(api_key="offline", request=request, timeout_seconds=1)
        if status == "dispatching":
            assert (
                failure.value.citation_resolution["blocked_reservation"]
                == reservation.pk
            )
            provider.enhance_bill.assert_not_called()
        else:
            assert failure.value.category == "test_dispatch"
            provider.enhance_bill.assert_called_once()


@pytest.mark.django_db
@pytest.mark.parametrize("stage", ["map", "dependency", "summary"])
def test_unknown_dispatch_survives_future_planners_but_allows_a_different_page(
    settings,
    source_bill,
    enhancement_owner,
    enhancement_settings,
    stage,
):
    from unittest.mock import Mock

    with enhancement_settings:
        attempt = _running_attempt(enhancement_owner, source_bill)
        request = _stage_request(settings, stage)
        provider = Mock()
        provider.enhance_bill.side_effect = ProviderError(
            "outcome_unknown", outcome_unknown=True
        )
        wrapper = DurableReaderProvider(provider, attempt, attempt.run_token, 4)
        with pytest.raises(ProviderError) as first:
            wrapper.enhance_bill(api_key="offline", request=request, timeout_seconds=1)
        assert first.value.outcome_unknown
        key = attempt.steps.get().request_fingerprint
        replanned = replace(
            request,
            source_snapshot=[
                {**source, "context_planner_version": 999}
                for source in request.source_snapshot
            ],
        )
        assert call_identity(request)[0] != call_identity(replanned)[0]
        with pytest.raises(ProviderError) as retry:
            wrapper.enhance_bill(
                api_key="offline", request=replanned, timeout_seconds=1
            )
        assert retry.value.citation_resolution["blocked_reservation"] == key
        provider.enhance_bill.assert_called_once()
        other = replace(
            replanned,
            request_envelope={
                **request.request_envelope,
                "instructions": "Different page.",
            },
        )
        with pytest.raises(ProviderError) as independent:
            wrapper.enhance_bill(api_key="offline", request=other, timeout_seconds=1)
        assert independent.value.outcome_unknown
        assert provider.enhance_bill.call_count == 2
