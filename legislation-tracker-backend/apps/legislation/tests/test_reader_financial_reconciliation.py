"""Recovered financial rules join reconciliation before summary/publication."""

import copy
import hashlib
from dataclasses import replace
from types import SimpleNamespace

import pytest
from jsonschema import ValidationError

from apps.legislation.enhancements.providers.base import ProviderResult, ProviderUsage
from apps.legislation.enhancements.reader_batches import execute_reader_batches
from apps.legislation.enhancements.reader_citations import (
    READER_ID_SCHEMA,
    citation_passages,
)
from apps.legislation.enhancements.reader_discovery import (
    money_candidates,
    policy_passages,
    retain_missing_financial_rules,
    validate_source_review,
)
from apps.legislation.enhancements.reader_reconciliation import (
    reconcile_review,
    validate_dependency_review,
    validate_reconciliation,
)
from apps.legislation.tests.test_reader_reconciliation import Provider, _fixture


def _financial_plan(settings, *, long_source=False, source_lines=300):
    plan, review = _fixture(settings, count=2)
    if long_source:
        owner = plan.source_snapshot[0]
        owner["quoted_text"] = "\n".join(
            f"Applicants in category {i} must pay the first fee instead of the second fee."
            for i in range(source_lines)
        )
        position = 0
        for source in plan.source_snapshot:
            source["start_char"] = position
            position += len(source["quoted_text"])
            source["end_char"] = position
            source["text_sha256"] = hashlib.sha256(
                source["quoted_text"].encode()
            ).hexdigest()
        review["policy_changes"][0].update(
            title="Pay the first fee",
            text="Applicants must pay the first fee instead of the second fee.",
            source_quotes=[
                {
                    "source_ref": owner["source_ref"],
                    "quote": citation_passages(owner)[0]["text"],
                }
            ],
        )
        settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES = 100_000
        settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS = 100_000
    owner = plan.source_snapshot[0]
    targets = [
        {
            "kind": "financial_item",
            "target_id": "financial-rule",
            "evidence_ranges": [(owner["start_char"], owner["end_char"])],
            "facts": {"item": {"financial_action": "fee"}},
        }
    ]
    # Real preflight snapshots retain overlapping summary/target contexts and
    # independently owned discovery sources. Known NLP targets belong to the
    # target context, not to a discovery owner.
    context = {
        key: copy.deepcopy(owner[key])
        for key in ("start_char", "end_char", "quoted_text", "text_sha256")
    }
    main_source = {**context, "source_ref": "src_9000"}
    target_source = {
        **context,
        "source_ref": "src_9001",
        "reader_targets": targets,
    }
    original_records = {row["record_id"]: row for row in review["factual_records"]}
    review["factual_records"] = [
        original_records.get(
            key,
            {"record_id": key, "claims": [], "definitions": [], "references": []},
        )
        for source in plan.source_snapshot
        for passage in citation_passages(source)
        if passage["quote_id"]
        for key in [f"{source['source_ref']}:{passage['quote_id']}"]
    ]
    first_id = review["factual_records"][0]["record_id"]
    review["factual_records"][0]["claims"] = [
        {
            "actor": "Applicants" if long_source else "Public hospitals",
            "action": "Pay the first fee" if long_source else "Apply for grants",
            "modality": "required" if long_source else "permitted",
            "affected_people": [],
            "timing": [],
            "money": [],
            "conditions": None,
            "exceptions": [],
            "evidence_ids": [first_id],
        }
    ]
    review["policy_checks"] = {
        key: "explained" if key == first_id else "context"
        for key in policy_passages(plan.source_snapshot)
    }
    review["money_checks"] = {
        key: "not_financial" for key in money_candidates(plan.source_snapshot)
    }
    explanation = {
        "target_id": "financial-rule",
        "status": "explained",
        "text": review["policy_changes"][0]["text"],
        "unresolved_reason": None,
        "source_quotes": copy.deepcopy(review["policy_changes"][0]["source_quotes"]),
    }
    for quote in explanation["source_quotes"]:
        quote["source_ref"] = target_source["source_ref"]
    return (
        replace(
            plan,
            source_snapshot=[main_source, target_source, *plan.source_snapshot],
            source_manifest={
                "budget": {"maximum_calls": 100, "dependency_call_reserve": 80}
            },
            request_envelope={
                "instructions": "Summarize all validated findings.",
                "source_packet": {
                    "sources": [{"source_ref": main_source["source_ref"]}]
                },
                "output_schema": copy.deepcopy(READER_ID_SCHEMA),
                "max_output_tokens": 4000,
            },
            reader_reuse={"source_review": review, "explanations": [explanation]},
        ),
        review,
    )


class FinancialProvider(Provider):
    def __init__(self, *, long_source=False):
        super().__init__(self._leave_unrelated_fee_unchanged if long_source else None)
        self.summaries = []

    @staticmethod
    def _leave_unrelated_fee_unchanged(output, request):
        output["items"] = {
            key: copy.deepcopy(item["value"])
            for key, item in request.request_envelope["source_packet"][
                "review_items"
            ].items()
        }
        for key, item in output["items"].items():
            if key.startswith("financial_items:") and len(item["text"]) > 1600:
                item["text"] = None
        for check in output["record_checks"].values():
            check.update(
                status="not_applicable",
                item_ids=[],
                reason="Hospital definitions do not govern the application fee.",
            )

    def enhance_bill(self, *, request, **kwargs):
        if request.request_envelope.get("dependency_review"):
            return super().enhance_bill(request=request, **kwargs)
        findings = request.request_envelope["source_packet"]["validated_changes"]
        self.summaries.append(copy.deepcopy(findings))
        finding = findings[0]
        return ProviderResult(
            {
                "schema_version": "1.4",
                "explanations": [],
                "summary": [
                    {
                        "text": (
                            "Applicants must pay the required fee."
                            if "fee" in finding["text"]
                            else "Qualifying public hospitals may apply for grants."
                        ),
                        "source_quotes": finding["source_quotes"][:1],
                    }
                ],
            },
            ProviderUsage(10, 20, 30),
            "summary",
            "model",
        )


@pytest.mark.parametrize("long_source", [False, True])
def test_execution_recovers_financial_inventory_before_reconciliation_and_summary(
    settings, long_source
):
    plan, original = _financial_plan(settings, long_source=long_source)
    provider = FinancialProvider(long_source=long_source)
    result = execute_reader_batches(plan, provider, "", lambda *_: None)
    review = result.output["source_review"]
    assert original["financial_items"] == []
    assert len(review["financial_items"]) == 1
    metadata = review["dependency_review"]
    assert "financial_items:0" in metadata["base_items"]
    assert any(
        "financial_items:0" in receipt["descriptor"]["item_ids"]
        for receipt in metadata["pages"]
    )
    final_text = review["financial_items"][0]["text"]
    assert any(
        finding["text"] == final_text
        for summary in provider.summaries
        for finding in summary
    )
    if long_source:
        assert len(final_text) > 1600
        owner = next(s for s in plan.source_snapshot if s.get("discovery_source"))
        assert final_text == owner["quoted_text"]
        assert len(review["financial_items"][0]["source_quotes"]) > 24
        assert all(
            request.request_envelope["max_output_tokens"] <= 24_000
            for request in provider.requests
        )
    else:
        assert "providing emergency care" in final_text
    validate_source_review(review, plan.source_snapshot)


def test_final_validation_keeps_financial_targets_outside_discovery_sources(settings):
    plan, review = _financial_plan(settings, long_source=True, source_lines=80)
    assert all(
        not source.get("reader_targets")
        for source in plan.source_snapshot
        if source.get("discovery_source")
    )
    retain_missing_financial_rules(review, plan.source_snapshot)
    assert 1600 < len(review["financial_items"][0]["text"].encode()) < 8000
    result, _, calls = reconcile_review(
        plan, review, FinancialProvider(long_source=True), "", lambda: None, 100
    )
    assert calls > 0
    assert validate_reconciliation(result, plan.source_snapshot) == {0}
    validate_source_review(result, plan.source_snapshot)


@pytest.mark.parametrize(
    "tamper", ["extra_record", "duplicate_record", "context_citation"]
)
def test_full_snapshot_does_not_expand_discovery_record_or_citation_ownership(
    settings, tamper
):
    plan, review = _financial_plan(settings, long_source=True, source_lines=80)
    retain_missing_financial_rules(review, plan.source_snapshot)
    result, _, _ = reconcile_review(
        plan, review, FinancialProvider(long_source=True), "", lambda: None, 100
    )
    context = next(s for s in plan.source_snapshot if s.get("reader_targets"))
    if tamper == "extra_record":
        quote_id = next(
            p["quote_id"] for p in citation_passages(context) if p["quote_id"]
        )
        result["factual_records"].append(
            {
                "record_id": f"{context['source_ref']}:{quote_id}",
                "claims": [],
                "definitions": [],
                "references": [],
            }
        )
    elif tamper == "duplicate_record":
        result["factual_records"][-1] = copy.deepcopy(result["factual_records"][0])
    else:
        # The context contains identical quotation text, but it is not a
        # discovery owner and cannot replace the original citation identity.
        result["financial_items"][0]["source_quotes"][0]["source_ref"] = context[
            "source_ref"
        ]
    with pytest.raises(ValidationError):
        validate_source_review(result, plan.source_snapshot)


def test_long_recovered_rule_does_not_allow_long_generated_rewrites(settings):
    plan, review = _financial_plan(settings, long_source=True)
    retain_missing_financial_rules(review, plan.source_snapshot)
    provider = FinancialProvider(long_source=True)
    result, _, _ = reconcile_review(plan, review, provider, "", lambda: None, 100)
    validate_source_review(result, plan.source_snapshot)
    request, output = provider.requests[0], copy.deepcopy(provider.outputs[0])
    for check in output["record_checks"].values():
        check.update(status="applies", item_ids=["financial_items:0"], reason=None)
    item = output["items"]["financial_items:0"]
    item["text"] = request.request_envelope["source_packet"]["review_items"][
        "financial_items:0"
    ]["value"]["text"].replace("first", "other")
    for key in output["record_checks"]:
        source_ref, quote_id = key.split(":", 1)
        item["source_quotes"].append({"source_ref": source_ref, "quote_id": quote_id})
    with pytest.raises(ValidationError):
        validate_dependency_review(output, request)


def test_long_recovered_base_is_verified_against_original_source(settings):
    plan, review = _financial_plan(settings, long_source=True)
    retain_missing_financial_rules(review, plan.source_snapshot)
    review["financial_items"][0]["text"] = review["financial_items"][0]["text"].replace(
        "first", "other"
    )
    with pytest.raises(ValidationError):
        reconcile_review(
            plan, review, FinancialProvider(long_source=True), "", lambda: None, 100
        )


def test_long_source_row_retains_verified_provenance_when_citations_grow(settings):
    plan, review = _financial_plan(settings, long_source=True)
    retain_missing_financial_rules(review, plan.source_snapshot)
    original = copy.deepcopy(review["financial_items"][0])

    def retain_text_add_evidence(output, request):
        FinancialProvider._leave_unrelated_fee_unchanged(output, request)
        for key, check in output["record_checks"].items():
            check.update(status="applies", item_ids=["financial_items:0"], reason=None)
            source_ref, quote_id = key.split(":", 1)
            output["items"]["financial_items:0"]["source_quotes"].append(
                {"source_ref": source_ref, "quote_id": quote_id}
            )

    result, _, _ = reconcile_review(
        plan, review, Provider(retain_text_add_evidence), "", lambda: None, 100
    )
    retained = result["financial_items"][0]
    assert retained["text"] == original["text"]
    assert len(retained["source_quotes"]) > len(original["source_quotes"])
    validate_source_review(result, plan.source_snapshot)
    # The receipt-validated source exception must not exempt other prose fields.
    result["financial_items"][0]["label"] = "x" * 81
    with pytest.raises(ValidationError):
        validate_source_review(result, plan.source_snapshot)


def test_cached_summary_without_receipts_reconstructs_financial_inventory(
    settings, monkeypatch
):
    plan, review = _financial_plan(settings)
    for source in plan.source_snapshot:
        source.pop("deferred_context_source_refs", None)
        source.pop("deferred_context_quote_ids", None)
    plan.source_manifest["budget"]["dependency_call_reserve"] = 0
    summary = [
        {
            "text": "Qualifying public hospitals may apply for grants.",
            "source_quotes": copy.deepcopy(
                review["policy_changes"][0]["source_quotes"]
            ),
        }
    ]

    class SavedSummaryPlan:
        def __init__(self, *_):
            pass

        def initialize(self, initial):
            return [(index, request, "saved-main") for index, request in initial]

        def saved_result(self, _):
            return {"summary": summary}

    monkeypatch.setattr(
        "apps.legislation.enhancements.reader_work.ReaderWorkPlan", SavedSummaryPlan
    )
    provider = SimpleNamespace(
        durable=True, attempt=None, run_token="run", progress=lambda: {}
    )
    result = execute_reader_batches(plan, provider, "", lambda *_: None)
    assert result.output["summary"] == summary
    assert len(result.output["source_review"]["financial_items"]) == 1
    validate_source_review(result.output["source_review"], plan.source_snapshot)
