from dataclasses import replace
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.legislation.enhancements.providers.base import ProviderError
from apps.legislation.enhancements.reader_sizing import split_reader_request
from apps.legislation.enhancements.source_packet import build_enhancement_preflight
from apps.legislation.tests.test_enhancement_service import (
    enhancement_owner,
    enhancement_settings,
    source_bill,
)
from apps.legislation.tests.test_enhancement_tasks import _pending_attempt
from apps.legislation.tests.test_reader_enhancement_pipeline import install_reader


def test_source_output_budget_scales_with_owned_text_and_preserves_context(settings):
    from types import SimpleNamespace

    from apps.legislation.enhancements.reader_citations import citation_passages
    from apps.legislation.enhancements.reader_sizing import (
        select_review_units,
        source_output_allowance,
    )

    source = {
        "source_ref": "src_0001",
        "quoted_text": "\n".join(
            f"The agency must provide program {i} with $100,000, subject to eligibility rules. "
            * 4
            for i in range(12)
        ),
        "policy_review": True,
    }
    ids = [p["quote_id"] for p in citation_passages(source) if p["quote_id"]]
    p = SimpleNamespace(
        source_snapshot=[source],
        request_envelope={
            "source_review": True,
            "source_packet": {
                "sources": [{"citation_passages": citation_passages(source)}]
            },
            "instructions": "",
            "max_output_tokens": 24000,
        },
    )
    # Use a real frozen request so replacements exercise production behavior.
    from apps.legislation.enhancements.types import EnhancementPreflight

    p = EnhancementPreflight(
        **{
            **{
                k: ""
                for k in (
                    "provider",
                    "requested_model",
                    "reasoning_effort",
                    "prompt_version",
                    "output_schema_version",
                    "source_packet_version",
                    "source_fingerprint",
                    "request_fingerprint",
                )
            },
            "source_manifest": {},
            "source_snapshot": p.source_snapshot,
            "request_envelope": p.request_envelope,
            "request_bytes": b"",
            "estimated_input_tokens": 0,
            "truncated": False,
        }
    )
    child = select_review_units(p, ids[:2])
    assert source_output_allowance(child.source_snapshot) < source_output_allowance(
        [source]
    )
    assert child.source_snapshot[0]["quoted_text"] == source["quoted_text"]
    assert child.request_envelope["source_packet"]["sources"][0][
        "citation_passages"
    ] == citation_passages(source)
    assert child.source_snapshot[0]["review_quote_ids"] == ids[:2]


def test_model_capacity_includes_input_output_and_transport_headroom(settings):
    from apps.legislation.enhancements.reader_capacity import fits

    settings.LLM_READER_MODEL_CAPACITIES = {
        "test/model": {"context_tokens": 10000, "output_tokens": 8000}
    }
    assert fits(
        {"max_output_tokens": 8000, "data": "small"}, provider="test", model="model"
    )
    assert not fits(
        {"max_output_tokens": 8000, "data": "x" * 2000}, provider="test", model="model"
    )
    assert not fits(
        {"max_output_tokens": 9000, "data": ""}, provider="test", model="model"
    )


@pytest.mark.django_db
def test_indivisible_truncation_gets_one_bounded_output_increase(
    source_bill, enhancement_settings
):
    from apps.legislation.enhancements.reader_sizing import recover_output_limit

    install_reader(source_bill, count=0)
    with enhancement_settings:
        plan = build_enhancement_preflight(source_bill)
        request = next(
            r for r in plan.reader_batches if r.request_envelope.get("source_review")
        )
        recovered = recover_output_limit(request)
        assert len(recovered) == 1
        assert recovered[0].source_snapshot == request.source_snapshot
        assert (
            recovered[0].request_envelope["max_output_tokens"]
            > request.request_envelope["max_output_tokens"]
        )
        assert recover_output_limit(recovered[0]) == ()


@pytest.mark.django_db
def test_full_source_planning_accounts_for_every_owned_passage(
    source_bill, enhancement_settings, settings
):
    from collections import Counter

    from apps.legislation.enhancements.reader_capacity import fits
    from apps.legislation.enhancements.reader_discovery import policy_passages

    document = source_bill.documents.get()
    document.extracted_text = "SEC. 1. Grants\n" + "\n".join(
        f"Grant program {i} shall receive $100,000 for eligible schools. " * 6
        for i in range(12)
    )
    document.save()
    install_reader(source_bill, count=0)
    with enhancement_settings:
        settings.LLM_READER_MAX_OUTPUT_TOKENS = 8000
        settings.LLM_READER_MAX_CALLS = 0
        plan = build_enhancement_preflight(source_bill)
        expected = policy_passages(
            [s for s in plan.source_snapshot if s.get("discovery_source")]
        )
        actual = Counter(
            i
            for r in plan.reader_batches
            if r.request_envelope.get("source_review")
            for i in policy_passages(r.source_snapshot)
        )
        assert set(actual) == set(expected)
        assert all(n == 1 for n in actual.values())
        assert all(fits(r.request_envelope) for r in plan.reader_batches)
        assert len(plan.reader_batches) > 1


def test_partial_review_keeps_only_valid_independent_ownership_groups():
    from types import SimpleNamespace

    from apps.legislation.enhancements.reader_citations import citation_passages
    from apps.legislation.enhancements.reader_partial import validated_components

    source = {
        "source_ref": "src_0001",
        "quoted_text": "The agency shall publish an annual report. "
        + "Report content. " * 45
        + "\nThe agency shall publish a public registry. "
        + "Registry content. " * 20,
        "policy_review": True,
    }
    ids = [p["quote_id"] for p in citation_passages(source) if p["quote_id"]]
    assert len(ids) == 2
    q = lambda i: {"source_ref": "src_0001", "quote_id": ids[i]}
    output = {
        "financial_items": [],
        "additional_changes": [],
        "money_checks": {},
        "policy_checks": {f"src_0001:{i}": "explained" for i in ids},
        "policy_changes": [
            {
                "title": "Annual report",
                "text": "The agency must publish an annual report.",
                "source_quotes": [q(0)],
            },
            {"title": "Registry", "text": "unfinished", "source_quotes": [q(1)]},
        ],
    }
    valid, pending = validated_components(output, [source])
    assert pending == [ids[1]]
    assert len(valid) == 1 and valid[0][0] == [ids[0]]
    # A shared citation joins the groups; retaining half could lose a condition.
    output["policy_changes"][1]["source_quotes"].append(q(0))
    valid, pending = validated_components(output, [source])
    assert valid == [] and pending == ids


@pytest.mark.django_db(transaction=True)
def test_mixed_recovery_retains_work_across_deliveries_and_confirmed_pause(
    source_bill, enhancement_owner, enhancement_settings, settings
):
    from collections import Counter

    from apps.legislation.enhancements.providers.base import (
        ProviderResult,
        ProviderUsage,
    )
    from apps.legislation.enhancements.reader_batches import execute_reader_batches
    from apps.legislation.enhancements.reader_citations import citation_passages
    from apps.legislation.enhancements.reader_steps import (
        DurableReaderProvider,
        ReaderBudgetPaused,
        ReaderDeliveryComplete,
    )
    from apps.legislation.enhancements.service import retry_enhancement_attempt
    from apps.legislation.tests.test_enhancement_service import _confirmation

    document = source_bill.documents.get()
    document.extracted_text = "SEC. 1. Reports\n" + "\n".join(
        f"The agency shall publish the {name} report. "
        + (f"{name} report details. " * 28)
        for name in ("education", "housing", "agriculture", "transportation")
    )
    document.save()
    install_reader(source_bill, count=0)
    seen = Counter()
    truncated = partial = False

    class Provider:
        def enhance_bill(self, *, request, **kwargs):
            nonlocal truncated, partial
            source = request.source_snapshot[0]
            ids = source.get("review_quote_ids") or [
                p["quote_id"] for p in citation_passages(source) if p["quote_id"]
            ]
            key = (bool(request.request_envelope.get("source_review")), tuple(ids))
            seen[key] += 1
            if request.request_envelope.get("source_review"):
                if not truncated:
                    truncated = True
                    raise ProviderError(
                        "invalid_output",
                        validation_code="provider_output_limit",
                        usage=ProviderUsage(10, 100, 110),
                    )
                rows = [
                    {
                        "title": "Agency reports",
                        "text": "The agency must publish a report.",
                        "source_quotes": [
                            {"source_ref": source["source_ref"], "quote_id": i}
                        ],
                    }
                    for i in ids
                ]
                if len(ids) > 1 and not partial:
                    partial = True
                    rows[-1]["text"] = "unfinished"
                output = {
                    "financial_items": [],
                    "additional_changes": [],
                    "money_checks": {},
                    "policy_changes": rows,
                    "policy_checks": {
                        f"{source['source_ref']}:{i}": "explained" for i in ids
                    },
                }
            else:
                q = request.request_envelope["source_packet"]["sources"][0][
                    "citation_passages"
                ][0]["quote_id"]
                output = {
                    "schema_version": "1.4",
                    "summary": [
                        {
                            "text": "The agency must publish reports.",
                            "source_quotes": [
                                {"source_ref": source["source_ref"], "quote_id": q}
                            ],
                        }
                    ],
                    "explanations": [],
                }
            return ProviderResult(output, ProviderUsage(10, 20, 30), "offline", "test")

    with enhancement_settings:
        settings.LLM_READER_CALLS_PER_DELIVERY = 1
        p = build_enhancement_preflight(source_bill)
        a = _pending_attempt(enhancement_owner, source_bill)
        a.status, a.run_token, a.lease_expires_at = (
            "running",
            "lease",
            timezone.now() + timedelta(minutes=10),
        )
        a.save()
        provider = Provider()
        paused = False
        for delivery in range(20):
            try:
                result = execute_reader_batches(
                    p,
                    DurableReaderProvider(
                        provider, a, a.run_token, 2 if not paused else 20
                    ),
                    "offline",
                    lambda *_: None,
                )
                break
            except ReaderDeliveryComplete:
                continue
            except ReaderBudgetPaused:
                assert not paused
                assert a.work_units.filter(status="validated").exists()
                a.status = "paused"
                a.save(update_fields=["status"])
                a.enhancement.status = "paused"
                a.enhancement.save(update_fields=["status"])
                a = retry_enhancement_attempt(
                    user=enhancement_owner,
                    bill=source_bill,
                    enhancement_id=a.enhancement_id,
                    confirmed=_confirmation(source_bill, a.credential),
                ).attempt
                a.status, a.run_token, a.lease_expires_at = (
                    "running",
                    "new-lease",
                    timezone.now() + timedelta(minutes=10),
                )
                a.save()
                paused = True
        else:
            pytest.fail("Recovery did not finish within the finite test work tree")
        assert truncated and partial and paused
        assert all(count == 1 for count in seen.values()), seen
        assert result.output["summary"]
        review = result.output["source_review"]
        from apps.legislation.enhancements.reader_discovery import policy_passages

        expected = policy_passages(
            [s for s in p.source_snapshot if s.get("discovery_source")]
        )
        assert set(review["policy_checks"]) == set(expected)
        assert len(review["policy_drafts"]) == len(expected)


@pytest.mark.django_db
def test_work_plan_remembers_splits_and_completed_siblings_after_restart(
    source_bill, enhancement_owner, enhancement_settings
):
    from apps.legislation.enhancements.reader_work import ReaderWorkPlan

    install_reader(source_bill)
    with enhancement_settings:
        p = build_enhancement_preflight(source_bill)
        a = _pending_attempt(enhancement_owner, source_bill)
    a.status, a.run_token = "running", "lease"
    a.lease_expires_at = timezone.now() + timedelta(minutes=10)
    a.save()
    plan = ReaderWorkPlan(a, "lease", p)
    initial = plan.initialize([(1, p.reader_batches[0])])
    parent = initial[0][2]
    children = split_reader_request(p.reader_batches[0])
    assert len(children) == 2
    nodes = plan.expand(parent, 1, children, reason="provider_output_limit")
    plan.complete(nodes[0][2], {"summary": [], "explanations": []})
    restarted = ReaderWorkPlan(a, "lease", p)
    restored = restarted.initialize([(1, p.reader_batches[0])])
    assert [row[2] for row in restored] == [row[2] for row in nodes]
    assert restarted.saved_result(nodes[0][2]) == {"summary": [], "explanations": []}
    assert restarted.saved_result(nodes[1][2]) is None
    assert parent not in [row[2] for row in restored]
    # A stale worker cannot overwrite the next worker's work tree.
    a.run_token = "next-lease"
    a.save(update_fields=["run_token"])
    with pytest.raises(ProviderError):
        plan.complete(nodes[1][2], {})


@pytest.mark.django_db
def test_dispatch_budget_is_not_charged_for_a_cached_result(
    source_bill, enhancement_owner, enhancement_settings
):
    from apps.legislation.enhancements.providers.base import (
        ProviderResult,
        ProviderUsage,
    )
    from apps.legislation.enhancements.reader_steps import (
        DurableReaderProvider,
        ReaderBudgetPaused,
    )

    install_reader(source_bill, count=0)
    with enhancement_settings:
        p = build_enhancement_preflight(source_bill)
        a = _pending_attempt(enhancement_owner, source_bill)
    refs = {s["source_ref"] for s in p.request_envelope["source_packet"]["sources"]}
    p = replace(
        p, source_snapshot=[s for s in p.source_snapshot if s["source_ref"] in refs]
    )
    a.status, a.run_token, a.lease_expires_at = (
        "running",
        "lease",
        timezone.now() + timedelta(minutes=10),
    )
    a.save()
    sent = []

    class Provider:
        def enhance_bill(self, **kwargs):
            sent.append(kwargs["request"])
            return ProviderResult(
                {
                    "schema_version": "1.4",
                    "explanations": [],
                    "summary": [
                        {
                            "text": "Requires a report.",
                            "source_quotes": [
                                {
                                    "source_ref": p.source_snapshot[0]["source_ref"],
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

    provider = DurableReaderProvider(Provider(), a, "lease", 1)
    provider.enhance_bill(api_key="offline", request=p, timeout_seconds=1)
    assert (
        provider.enhance_bill(
            api_key="offline", request=p, timeout_seconds=1
        ).usage.total_tokens
        == 0
    )
    different = replace(
        p, request_envelope={**p.request_envelope, "instructions": "Another request"}
    )
    with pytest.raises(ReaderBudgetPaused):
        provider.enhance_bill(api_key="offline", request=different, timeout_seconds=1)
    assert len(sent) == 1
    assert a.steps.count() == 1
    # Token authorization is independent of the number of requests remaining.
    token_limited = replace(
        different,
        source_manifest={
            **p.source_manifest,
            "budget": {**p.source_manifest["budget"], "maximum_output": 5},
        },
    )
    with pytest.raises(ReaderBudgetPaused):
        DurableReaderProvider(provider.provider, a, "lease", 10).enhance_bill(
            api_key="offline", request=token_limited, timeout_seconds=1
        )
    assert len(sent) == 1 and a.steps.count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("router", [False, True])
def test_partial_cache_survives_checkpoint_crash_and_remaps_citations(
    source_bill, enhancement_owner, enhancement_settings, router, monkeypatch
):
    from apps.legislation.enhancements.providers.base import (
        ProviderResult,
        ProviderUsage,
    )
    from apps.legislation.enhancements.reader_cache import remap
    from apps.legislation.enhancements.reader_citations import citation_passages
    from apps.legislation.enhancements.reader_partial import PartialReviewReady
    from apps.legislation.enhancements.reader_steps import DurableReaderProvider

    document = source_bill.documents.get()
    document.extracted_text = (
        "The agency shall publish an annual report. "
        + "Report content. " * 45
        + "\nThe agency shall publish a public registry. "
        + "Registry content. " * 20
    )
    document.save()
    install_reader(source_bill, count=0)
    with enhancement_settings:
        plan = build_enhancement_preflight(source_bill)
        request = next(
            r for r in plan.reader_batches if r.request_envelope.get("source_review")
        )
        a = _pending_attempt(enhancement_owner, source_bill)
    if router:
        request = replace(
            request,
            provider="openrouter",
            requested_model="openrouter/free",
            request_envelope={
                **request.request_envelope,
                "provider": "openrouter",
                "requested_model": "openrouter/free",
            },
        )
    a.status, a.run_token, a.lease_expires_at = (
        "running",
        "lease",
        timezone.now() + timedelta(minutes=10),
    )
    a.save()
    sent = []

    class Provider:
        def enhance_bill(self, **kwargs):
            sent.append(kwargs["request"])
            source = request.source_snapshot[0]
            ids = [p["quote_id"] for p in citation_passages(source) if p["quote_id"]]
            return ProviderResult(
                {
                    "financial_items": [],
                    "additional_changes": [],
                    "money_checks": {},
                    "policy_changes": [
                        {
                            "title": "Report",
                            "text": (
                                "The agency must publish a report."
                                if i == 0
                                else "unfinished"
                            ),
                            "source_quotes": [
                                {"source_ref": source["source_ref"], "quote_id": qid}
                            ],
                        }
                        for i, qid in enumerate(ids)
                    ],
                    "policy_checks": {
                        f"{source['source_ref']}:{qid}": "explained" for qid in ids
                    },
                },
                ProviderUsage(10, 20, 30),
                "offline",
                "test:free" if router else "test",
            )

    provider = Provider()
    with pytest.raises(PartialReviewReady) as first:
        DurableReaderProvider(provider, a, "lease", 10).enhance_bill(
            api_key="offline", request=request, timeout_seconds=1
        )
    # Restart before the caller writes the work-node children, at zero remaining calls.
    mapping = {request.source_snapshot[0]["source_ref"]: "src_0099"}
    renamed = replace(
        request,
        source_snapshot=remap(request.source_snapshot, mapping),
        request_envelope=remap(request.request_envelope, mapping),
    )
    with pytest.raises(PartialReviewReady) as cached:
        DurableReaderProvider(provider, a, "lease", 0).enhance_bill(
            api_key="offline", request=renamed, timeout_seconds=1
        )
    assert len(sent) == 1
    assert cached.value.usage.total_tokens == 0
    assert cached.value.parts == remap(first.value.parts, mapping)
    if router:
        a.refresh_from_db()
        assert a.pinned_model == "test:free"
        a.status = "paused"
        a.save(update_fields=["status"])
        a.status = "running"
        a.pk, a.sequence, a.pinned_model = None, a.sequence + 1, ""
        a.save()
        with pytest.raises(PartialReviewReady):
            DurableReaderProvider(provider, a, "lease", 0).enhance_bill(
                api_key="offline", request=renamed, timeout_seconds=1
            )
        a.refresh_from_db()
        assert a.pinned_model == "test:free"
        assert len(sent) == 1

    # A stricter current validator must not republish an old partial result or
    # crash outside the recovery path. With no calls left, pause for more budget.
    from apps.legislation.enhancements.diagnostics import output_error
    from apps.legislation.enhancements.reader_steps import ReaderBudgetPaused

    a.status = "paused"
    a.save(update_fields=["status"])
    a.status, a.pk, a.sequence = "running", None, a.sequence + 1
    a.save()

    def reject_old_copy(*args, **kwargs):
        raise output_error("reader_amount_conflict", ["policy_changes"])

    monkeypatch.setattr(
        "apps.legislation.enhancements.reader_steps._validate_response", reject_old_copy
    )
    with pytest.raises(ReaderBudgetPaused):
        DurableReaderProvider(provider, a, "lease", 0).enhance_bill(
            api_key="offline", request=renamed, timeout_seconds=1
        )
    assert len(sent) == 1


@pytest.mark.django_db(transaction=True)
def test_worker_pauses_and_keeps_plan_when_dispatch_budget_runs_out(
    source_bill, enhancement_owner, enhancement_settings, monkeypatch
):
    from apps.legislation.enhancements.reader_steps import ReaderBudgetPaused
    from apps.legislation.enhancements.service import retry_allowed
    from apps.legislation.tasks import run_bill_enhancement_attempt

    install_reader(source_bill)

    class Provider:
        def enhance_bill(self, **kwargs):
            pytest.fail("The budget must stop dispatch before the provider is called")

    from apps.legislation.enhancements.reader_steps import DurableReaderProvider

    monkeypatch.setattr(
        "apps.legislation.enhancements.reader_steps.DurableReaderProvider",
        lambda p, a, token, maximum: DurableReaderProvider(p, a, token, 0),
    )
    monkeypatch.setattr("apps.legislation.tasks.get_provider", lambda _: Provider())
    with enhancement_settings:
        a = _pending_attempt(enhancement_owner, source_bill)
        result = run_bill_enhancement_attempt(a.pk, a.dispatch_token)
    a.refresh_from_db()
    assert result["status"] == "paused"
    assert a.status == "paused"
    assert a.failure_category == "budget_exhausted"
    assert retry_allowed(a)
    assert a.work_units.filter(status="pending").exists()
    assert a.result_json is None


@pytest.mark.django_db
def test_reconstructing_completed_direct_summary_keeps_resolved_citations(
    source_bill, enhancement_owner, enhancement_settings
):
    from apps.legislation.enhancements.providers.base import (
        ProviderResult,
        ProviderUsage,
    )
    from apps.legislation.enhancements.reader_batches import execute_reader_batches
    from apps.legislation.enhancements.reader_discovery import policy_passages
    from apps.legislation.enhancements.reader_steps import DurableReaderProvider

    install_reader(source_bill, count=0)
    calls = []

    class Provider:
        def enhance_bill(self, *, request, **kwargs):
            calls.append(request)
            source = request.source_snapshot[0]
            if request.request_envelope.get("source_review"):
                output = {
                    "financial_items": [],
                    "additional_changes": [],
                    "policy_changes": [],
                    "money_checks": {},
                    "policy_checks": {
                        i: "context" for i in policy_passages(request.source_snapshot)
                    },
                }
            else:
                output = {
                    "schema_version": "1.4",
                    "explanations": [],
                    "summary": [
                        {
                            "text": "Requires a report.",
                            "source_quotes": [
                                {
                                    "source_ref": source["source_ref"],
                                    "quote_id": "p0001",
                                }
                            ],
                        }
                    ],
                }
            return ProviderResult(output, ProviderUsage(10, 20, 30), "offline", "test")

    with enhancement_settings:
        plan = build_enhancement_preflight(source_bill)
        a = _pending_attempt(enhancement_owner, source_bill)
        a.status, a.run_token, a.lease_expires_at = (
            "running",
            "lease",
            timezone.now() + timedelta(minutes=10),
        )
        a.save()
        first = execute_reader_batches(
            plan,
            DurableReaderProvider(Provider(), a, "lease", 10),
            "offline",
            lambda *_: None,
        )
        second = execute_reader_batches(
            plan,
            DurableReaderProvider(Provider(), a, "lease", 0),
            "offline",
            lambda *_: None,
        )
    assert len(calls) == 2
    assert first.output == second.output
