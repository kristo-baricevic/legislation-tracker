"""Deferred facts are paged completely, cited, and gated before publication."""

import copy
import hashlib

import pytest
from jsonschema import ValidationError

from apps.legislation.enhancements.providers.base import (
    ProviderError,
    ProviderResult,
    ProviderUsage,
)
from apps.legislation.enhancements.reader_capacity import fits
from apps.legislation.enhancements.reader_reconciliation import (
    reconcile_review,
    reconciliation_call_bound,
    validate_dependency_review,
    validate_reconciliation,
)
from apps.legislation.enhancements.source_packet import canonical_json_bytes
from apps.legislation.enhancements.types import EnhancementPreflight


def _fixture(settings, count=12):
    settings.LLM_READER_MODEL_CAPACITIES = {
        "test/model": {"context_tokens": 100000, "output_tokens": 24000}
    }
    settings.LLM_READER_MAX_OUTPUT_TOKENS = 24000
    settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES = 14000
    settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS = 14000
    texts = ["Qualifying public hospitals may apply for grants.\n"] + [
        f"Term {i} means the designated agency's eligible facilities. "
        + "The term retains its stated scope and does not change unrelated programs. "
        * 5
        + (
            "Only public hospitals providing emergency care qualify.\n"
            if i == count
            else "\n"
        )
        for i in range(1, count + 1)
    ]
    sources, records = [], []
    position = 0
    for index, text in enumerate(texts, 1):
        ref = f"src_{index:04d}"
        sources.append(
            {
                "source_ref": ref,
                "quoted_text": text,
                "start_char": position,
                "end_char": position + len(text),
                "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "factual_map": True,
                "discovery_source": True,
                "policy_review": True,
            }
        )
        position += len(text)
        key = f"{ref}:p0001"
        records.append(
            {
                "record_id": key,
                "claims": [],
                "definitions": (
                    [
                        {
                            "term": (
                                "qualifying hospital"
                                if index == count + 1
                                else f"Term {index}"
                            ),
                            "meaning": text,
                            "scope": "this section",
                            "evidence_ids": [key],
                        }
                    ]
                    if index > 1
                    else []
                ),
                "references": [],
            }
        )
    sources[0]["deferred_context_source_refs"] = [s["source_ref"] for s in sources[1:]]
    sources[0]["deferred_context_quote_ids"] = {
        s["source_ref"]: ["p0001"] for s in sources[1:]
    }
    review = {
        "reviewed_sources": [s["source_ref"] for s in sources],
        "financial_items": [],
        "additional_changes": [],
        "money_checks": {},
        "policy_changes": [
            {
                "title": "Hospital grants",
                "text": "Qualifying public hospitals may apply for grants.",
                "source_quotes": [
                    {"source_ref": sources[0]["source_ref"], "quote": texts[0]}
                ],
            }
        ],
        "policy_checks": {},
        "factual_records": records,
    }
    preflight = EnhancementPreflight(
        provider="test",
        requested_model="model",
        reasoning_effort="",
        prompt_version="test",
        output_schema_version="test",
        source_packet_version="test",
        source_fingerprint="source",
        request_fingerprint="request",
        source_manifest={},
        source_snapshot=sources,
        request_envelope={
            "instructions": "",
            "source_packet": {},
            "max_output_tokens": 4000,
        },
        request_bytes=b"",
        estimated_input_tokens=0,
        truncated=False,
    )
    return preflight, review


class Provider:
    def __init__(self, transform=None):
        self.requests = []
        self.outputs = []
        self.transform = transform

    def enhance_bill(self, *, request, **kwargs):
        self.requests.append(request)
        packet = request.request_envelope["source_packet"]
        descriptor = request.request_envelope["dependency_review"]
        output = {
            "page_id": descriptor["page_id"],
            "items": {
                key: copy.deepcopy(item["value"])
                for key, item in packet["review_items"].items()
            },
            "record_checks": {},
        }
        for record in packet["dependency_records"]:
            applicable = any(
                d["term"] == "qualifying hospital" for d in record["definitions"]
            )
            output["record_checks"][record["record_id"]] = {
                "status": (
                    "applies" if applicable and output["items"] else "not_applicable"
                ),
                "item_ids": list(output["items"]) if applicable else [],
                "reason": (
                    None
                    if applicable and output["items"]
                    else "This definition does not change the supplied finding."
                ),
            }
            if applicable:
                ref, quote_id = record["record_id"].split(":", 1)
                for item in output["items"].values():
                    item["text"] = (
                        "Public hospitals providing emergency care may apply for grants."
                    )
                    quote = {"source_ref": ref, "quote_id": quote_id}
                    if quote not in item["source_quotes"]:
                        item["source_quotes"].append(quote)
        if self.transform:
            self.transform(output, request)
        self.outputs.append(copy.deepcopy(output))
        return ProviderResult(output, ProviderUsage(10, 20, 30), "response", "model")


def test_pages_consume_every_typed_record_and_preserve_distant_condition(settings):
    preflight, review = _fixture(settings)
    original = copy.deepcopy(review)
    provider = Provider()
    checkpoints = []
    result, response, calls = reconcile_review(
        preflight,
        review,
        provider,
        "",
        lambda: checkpoints.append(True),
        reconciliation_call_bound(preflight.source_snapshot),
    )
    assert calls == len(provider.requests) > 1
    assert len(checkpoints) == calls * 2
    assert response.usage.total_tokens == calls * 30
    assert review == original
    assert result["factual_records"] == original["factual_records"]
    assert "providing emergency care" in result["policy_changes"][0]["text"]
    assert result["policy_changes"][0]["source_quotes"][-1]["source_ref"] == "src_0013"
    assert all(
        fits(r.request_envelope, provider="test", model="model")
        for r in provider.requests
    )
    checked = [
        record_id
        for r in provider.requests
        for record_id in r.request_envelope["dependency_review"]["record_ids"]
    ]
    assert checked == [
        record["record_id"] for record in original["factual_records"][1:]
    ]
    validate_reconciliation(result, preflight.source_snapshot)
    # The durable cache keeps raw quote IDs. Local hydration never mutates them.
    assert all(
        "quote_id" in q
        for output in provider.outputs
        for item in output["items"].values()
        for q in item["source_quotes"]
    )


@pytest.mark.parametrize(
    "failure",
    ["missing_record", "wrong_page", "wrong_owner", "unresolved", "unexplained_change"],
)
def test_incomplete_or_unowned_pages_stop_without_retry(settings, failure):
    preflight, review = _fixture(settings, count=2)

    def transform(output, request):
        if failure == "missing_record":
            output["record_checks"].pop(next(iter(output["record_checks"])))
        elif failure == "wrong_page":
            output["page_id"] = "a different owner's page"
        elif failure == "wrong_owner":
            next(iter(output["items"].values()))["source_quotes"].reverse()
        elif failure == "unresolved":
            for check in output["record_checks"].values():
                check.update(
                    status="unresolved",
                    item_ids=[],
                    reason="An external condition is unresolved.",
                )
            for key, value in request.request_envelope["source_packet"][
                "review_items"
            ].items():
                output["items"][key] = copy.deepcopy(value["value"])
        else:
            for check in output["record_checks"].values():
                check.update(status="not_applicable", item_ids=[], reason="No change.")

    provider = Provider(transform)
    with pytest.raises(ProviderError):
        reconcile_review(preflight, review, provider, "", lambda: None, 100)
    assert len(provider.requests) == 1
    assert "dependency_review" not in review


@pytest.mark.parametrize(
    "tamper", ["missing", "duplicate", "fact", "owner", "prose", "evidence"]
)
def test_receipts_bind_complete_edges_facts_and_original_evidence(settings, tamper):
    preflight, review = _fixture(settings)
    result, _, _ = reconcile_review(
        preflight, review, Provider(), "", lambda: None, 100
    )
    sources = copy.deepcopy(preflight.source_snapshot)
    if tamper == "missing":
        result["dependency_review"]["pages"].pop()
    elif tamper == "duplicate":
        result["dependency_review"]["pages"].append(
            result["dependency_review"]["pages"][0]
        )
    elif tamper == "fact":
        result["factual_records"][-1]["definitions"][0][
            "meaning"
        ] = "Private hospitals qualify."
    elif tamper == "owner":
        result["dependency_review"]["pages"][0]["descriptor"][
            "owner_source_ref"
        ] = "src_0002"
    elif tamper == "evidence":
        sources[-1]["quoted_text"] = sources[-1]["quoted_text"].replace(
            "Only public hospitals", "All private hospitals"
        )
    else:
        result["policy_changes"][0]["text"] = "Every hospital receives a grant."
    with pytest.raises(ValidationError):
        validate_reconciliation(result, sources)


def test_later_page_cannot_erase_an_earlier_citation(settings):
    preflight, review = _fixture(settings)
    review["factual_records"][1]["definitions"][0]["term"] = "qualifying hospital"

    def erase(output, request):
        if (
            request.request_envelope["dependency_review"]["record_ids"][0]
            != "src_0002:p0001"
        ):
            next(iter(output["items"].values()))["source_quotes"] = [
                q
                for q in next(iter(output["items"].values()))["source_quotes"]
                if q["source_ref"] != "src_0002"
            ]

    provider = Provider(erase)
    result, _, _ = reconcile_review(preflight, review, provider, "", lambda: None, 100)
    assert len(provider.requests) > 1
    assert "src_0002" in {
        q["source_ref"] for q in result["policy_changes"][0]["source_quotes"]
    }
    validate_reconciliation(result, preflight.source_snapshot)


def test_no_reader_item_still_requires_every_dependency_receipt(settings):
    preflight, review = _fixture(settings, count=3)
    review["policy_changes"] = []
    result, _, calls = reconcile_review(
        preflight, review, Provider(), "", lambda: None, 100
    )
    assert calls
    assert result["policy_changes"] == []
    validate_reconciliation(result, preflight.source_snapshot)
    result["dependency_review"]["pages"].clear()
    with pytest.raises(ValidationError):
        validate_reconciliation(result, preflight.source_snapshot)


def test_call_reservation_stops_before_dispatch(settings):
    preflight, review = _fixture(settings, count=2)
    provider = Provider()
    with pytest.raises(ProviderError):
        reconcile_review(preflight, review, provider, "", lambda: None, 0)
    assert not provider.requests


def test_validated_review_reuse_needs_no_paid_page_and_rechecks_receipts(settings):
    preflight, review = _fixture(settings, count=2)
    result, _, _ = reconcile_review(
        preflight, review, Provider(), "", lambda: None, 100
    )
    provider = Provider()
    reused, usage, calls = reconcile_review(
        preflight, result, provider, "", lambda: None, 0
    )
    assert reused == result
    assert calls == 0
    assert usage.usage.total_tokens == 0
    assert not provider.requests


def test_response_validation_does_not_rewrite_provider_cache(settings):
    preflight, review = _fixture(settings, count=2)
    provider = Provider()
    reconcile_review(preflight, review, provider, "", lambda: None, 100)
    request, output = provider.requests[0], provider.outputs[0]
    original = canonical_json_bytes(output)
    resolved = validate_dependency_review(output, request)
    assert canonical_json_bytes(output) == original
    assert "quote" in next(iter(resolved["items"].values()))["source_quotes"][0]
    assert "quote_id" in next(iter(output["items"].values()))["source_quotes"][0]


def test_oversized_owner_group_splits_whole_items_and_checks_every_edge(settings):
    preflight, review = _fixture(settings, count=3)
    template = review["policy_changes"][0]
    review["policy_changes"] = [
        {**copy.deepcopy(template), "title": f"Hospital program {number}"}
        for number in range(20)
    ]
    provider = Provider()
    result, _, calls = reconcile_review(
        preflight, review, provider, "", lambda: None, 100
    )
    assert calls > 1
    covered = [
        (item_id, record_id)
        for request in provider.requests
        for item_id in request.request_envelope["dependency_review"]["item_ids"]
        for record_id in request.request_envelope["dependency_review"]["record_ids"]
    ]
    assert len(covered) == len(set(covered)) == 20 * 3
    assert len(result["policy_changes"]) == 20
    assert all(
        "providing emergency care" in item["text"] for item in result["policy_changes"]
    )
    validate_reconciliation(result, preflight.source_snapshot)


def test_receipts_do_not_flatten_nested_condition_or_exception_records(settings):
    preflight, review = _fixture(settings, count=3)
    key = review["factual_records"][-1]["record_id"]
    condition = {
        "operator": "all",
        "children": [
            {
                "operator": "leaf",
                "text": "The hospital is public.",
                "evidence_ids": [key],
            },
            {
                "operator": "any",
                "children": [
                    {
                        "operator": "leaf",
                        "text": "The hospital provides emergency care.",
                        "evidence_ids": [key],
                    },
                    {
                        "operator": "leaf",
                        "text": "The stated exception applies.",
                        "evidence_ids": [key],
                    },
                ],
            },
        ],
    }
    claim = {
        "actor": "Public hospitals",
        "action": "Apply for grants",
        "modality": "permitted",
        "affected_people": [],
        "timing": [],
        "money": [],
        "conditions": condition,
        "exceptions": [
            {
                "operator": "leaf",
                "text": "The stated exception applies.",
                "evidence_ids": [key],
            }
        ],
        "evidence_ids": [key],
    }
    review["factual_records"][-1]["claims"] = [claim]
    result, _, _ = reconcile_review(
        preflight, review, Provider(), "", lambda: None, 100
    )
    assert result["factual_records"][-1]["claims"] == [claim]
    assert result["factual_records"][-1]["claims"][0]["conditions"] == condition


def test_policy_presentation_grouping_preserves_draft_receipt_positions(settings):
    from apps.legislation.enhancements.policy_compilation import group_policy_drafts

    preflight, review = _fixture(settings, count=2)
    review["policy_changes"].append(copy.deepcopy(review["policy_changes"][0]))
    result, _, _ = reconcile_review(
        preflight, review, Provider(), "", lambda: None, 100
    )
    result["policy_drafts"] = copy.deepcopy(result["policy_changes"])
    result["policy_changes"] = group_policy_drafts(preflight, result["policy_drafts"])
    assert len(result["policy_drafts"]) == 2
    assert len(result["policy_changes"]) == 1
    validate_reconciliation(result, preflight.source_snapshot)
    result["policy_drafts"][1]["text"] = "Private hospitals may apply for grants."
    with pytest.raises(ValidationError):
        validate_reconciliation(result, preflight.source_snapshot)


def test_applicable_history_over_100kb_is_retained_without_resending_it(settings):
    preflight, review = _fixture(settings, count=300)
    settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES = 100000
    settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS = 100000
    settings.LLM_READER_MODEL_CAPACITIES = {
        "test/model": {"context_tokens": 200000, "output_tokens": 24000}
    }
    cursor = 0
    evidence = {}
    for index, (source, record) in enumerate(
        zip(preflight.source_snapshot, review["factual_records"], strict=True)
    ):
        if index:
            # Every page genuinely supports the same material eligibility rule;
            # the short explanation can retain that rule while the full mapped
            # source inventory remains separately inspectable.
            text = (
                f"SEC. {index}. Hospital eligibility. "
                "A qualifying hospital is a public hospital providing emergency care. "
                + "The definition applies to applications for the hospital grant program and preserves the public hospital and emergency care requirements. "
                * 4
            )
            assert len(text) < 800
            source["quoted_text"] = text
            source["text_sha256"] = hashlib.sha256(text.encode()).hexdigest()
            record["definitions"][0].update(term="qualifying hospital", meaning=text)
        source["start_char"] = cursor
        cursor += len(source["quoted_text"])
        source["end_char"] = cursor
        evidence[record["record_id"]] = source["quoted_text"]
    original_facts = copy.deepcopy(review["factual_records"])
    provider = Provider()
    result, _, calls = reconcile_review(
        preflight,
        review,
        provider,
        "",
        lambda: None,
        reconciliation_call_bound(preflight.source_snapshot),
    )
    assert calls > 5
    assert result["factual_records"] == original_facts
    assert len(result["policy_changes"][0]["source_quotes"]) == 301
    assert sum(len(text.encode()) for text in evidence.values()) > 190000
    for request in provider.requests:
        descriptor = request.request_envelope["dependency_review"]
        packet = request.request_envelope["source_packet"]
        supplied = {
            f"{source['source_ref']}:{passage['quote_id']}"
            for source in packet["sources"]
            for passage in source["citation_passages"]
        }
        assert not descriptor["retained_evidence_ids"]
        assert (
            len(packet["review_items"]["policy_changes:0"]["value"]["source_quotes"])
            == 1
        )
        assert supplied == set(descriptor["record_ids"]) | {"src_0001:p0001"}
        assert (
            sum(
                len(passage["text"].encode())
                for source in packet["sources"]
                for passage in source["citation_passages"]
            )
            < 25000
        )
        assert len(request.request_bytes) <= 100000
        assert fits(request.request_envelope, provider="test", model="model")
    validate_reconciliation(result, preflight.source_snapshot)


def test_truncated_dependency_pages_split_complete_record_edges(settings):
    preflight, review = _fixture(settings, count=4)
    settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES = 100000
    settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS = 100000

    class Truncated(Provider):
        def __init__(self):
            super().__init__()
            self.attempts = []

        def enhance_bill(self, *, request, **kwargs):
            self.attempts.append(request)
            if len(request.request_envelope["dependency_review"]["record_ids"]) > 1:
                raise ProviderError(
                    "invalid_output",
                    validation_code="provider_output_limit",
                    usage=ProviderUsage(11, 40, 51),
                )
            return super().enhance_bill(request=request, **kwargs)

    provider = Truncated()
    result, response, calls = reconcile_review(
        preflight, review, provider, "", lambda: None, 100
    )
    assert calls == len(provider.attempts) == 7
    assert response.usage.total_tokens == 3 * 51 + 4 * 30
    assert len(result["dependency_review"]["pages"]) == 4
    assert "providing emergency care" in result["policy_changes"][0]["text"]
    validate_reconciliation(result, preflight.source_snapshot)


def test_truncated_single_record_splits_reader_items_without_losing_edges(settings):
    preflight, review = _fixture(settings, count=1)
    settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES = 100000
    settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS = 100000
    review["policy_changes"] *= 4

    class Truncated(Provider):
        def __init__(self):
            super().__init__()
            self.attempts = []

        def enhance_bill(self, *, request, **kwargs):
            self.attempts.append(request)
            if len(request.request_envelope["dependency_review"]["item_ids"]) > 1:
                raise ProviderError(
                    "invalid_output", validation_code="provider_output_limit"
                )
            return super().enhance_bill(request=request, **kwargs)

    provider = Truncated()
    result, _, calls = reconcile_review(
        preflight, review, provider, "", lambda: None, 100
    )
    assert calls == len(provider.attempts) == 7
    assert len(result["policy_changes"]) == 4
    assert all(
        "providing emergency care" in item["text"] for item in result["policy_changes"]
    )
    checked = [
        (item_id, record_id)
        for page in result["dependency_review"]["pages"]
        for item_id in page["descriptor"]["item_ids"]
        for record_id in page["descriptor"]["record_ids"]
    ]
    assert len(checked) == len(set(checked)) == 4
    validate_reconciliation(result, preflight.source_snapshot)


@pytest.mark.parametrize("stop", ["recover", "capacity", "budget", "unknown"])
def test_indivisible_dependency_output_recovery_is_bounded(settings, stop):
    from apps.legislation.enhancements.reader_cache import call_identity

    preflight, review = _fixture(settings, count=1)
    settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES = 100000
    settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS = 100000

    class Truncated(Provider):
        def __init__(self):
            super().__init__()
            self.attempts = []

        def enhance_bill(self, *, request, **kwargs):
            self.attempts.append(request)
            if stop != "recover" or len(self.attempts) == 1:
                raise ProviderError(
                    "invalid_output",
                    validation_code="provider_output_limit",
                    outcome_unknown=stop == "unknown",
                    usage=ProviderUsage(11, 40, 51),
                )
            return super().enhance_bill(request=request, **kwargs)

    provider = Truncated()
    bound = reconciliation_call_bound(preflight.source_snapshot)
    if stop == "recover":
        result, response, calls = reconcile_review(
            preflight, review, provider, "", lambda: None, bound
        )
        assert calls == 2
        assert response.usage.total_tokens == 51 + 30
        validate_reconciliation(result, preflight.source_snapshot)
    else:
        with pytest.raises(ProviderError) as caught:
            reconcile_review(
                preflight,
                review,
                provider,
                "",
                lambda: None,
                2 if stop == "budget" else bound,
            )
        assert caught.value.usage.total_tokens == len(provider.attempts) * 51
        if stop == "budget":
            assert caught.value.category == "request_too_large"
            assert len(provider.attempts) == 2
        else:
            assert caught.value.validation_code == "provider_output_limit"
        if stop == "unknown":
            assert len(provider.attempts) == 1
        if stop == "capacity":
            assert provider.attempts[-1].request_envelope["max_output_tokens"] == 24000
            assert len(provider.attempts) <= bound
    budgets = [
        request.request_envelope["max_output_tokens"] for request in provider.attempts
    ]
    assert budgets == sorted(set(budgets))
    assert len({call_identity(request)[0] for request in provider.attempts}) == len(
        budgets
    )
    # Output growth changes dispatch identity, not the evidence/edge receipt.
    assert (
        len(
            {
                request.request_envelope["dependency_review"]["page_id"]
                for request in provider.attempts
            }
        )
        == 1
    )
    assert all(
        fits(request.request_envelope, provider="test", model="model")
        for request in provider.attempts
    )
