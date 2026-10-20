from types import SimpleNamespace

import pytest

from apps.legislation.enhancements.providers.base import ProviderResult, ProviderUsage
from apps.legislation.enhancements.source_packet import PreflightUnavailable
from apps.legislation.evaluation import coverage_candidate as candidate


def prepare():
    bill = SimpleNamespace(
        id=1,
        jurisdiction="federal",
        session=119,
        bill_number="HR 1",
        title="Records Act",
        status="introduced",
        introduced_at=None,
    )
    return candidate.prepare(
        bill,
        "SEC. 1. PENALTY\nA person shall be fined up to $10,000 for knowingly disclosing records.",
        "IH",
    )


def result(text):
    return ProviderResult(
        output={
            "schema_version": "1.3",
            "glossary": [],
            "overview": [],
            "key_impacts": [],
            "obligations": [],
            "funding_and_timing": [
                {
                    "kind": "funding",
                    "text": text,
                    "source_refs": ["src_0001"],
                    "source_quotes": [
                        {
                            "source_ref": "src_0001",
                            "quote": "A person shall be fined up to $10,000 for knowingly disclosing records.",
                        }
                    ],
                }
            ],
            "uncertain_language": [],
        },
        usage=ProviderUsage(100, 50, 150),
        response_id="test",
        resolved_model="test",
    )


def test_missing_amount_triggers_one_correction_and_counts_both_calls():
    request, inventory = prepare()
    outputs = iter(
        [
            result("A fine applies."),
            result("A fine of up to $10,000 applies for knowingly disclosing records."),
        ]
    )

    def generate(request):
        response = next(outputs)
        response.output["coverage_response"] = {
            inventory[0]["id"]: {
                "status": "explained",
                "output_paths": ["funding_and_timing/0"],
                "reason": "",
            }
        }
        return response

    report = candidate.run(request, inventory, generate)
    assert report["provider_calls"] == 2
    assert report["usage"] == {
        "input_tokens": 200,
        "output_tokens": 100,
        "total_tokens": 300,
    }
    assert report["initial_coverage"][0]["status"] == "missing_amount"
    assert report["coverage"][0]["status"] == "needs_semantic_review"
    assert report["release_gate"] == "blocked"


def test_persistent_omission_stops_after_one_correction():
    request, inventory = prepare()
    report = candidate.run(
        request, inventory, lambda request: result("A fine applies.")
    )
    assert report["provider_calls"] == 2
    assert report["release_gate"] == "fail"
    assert report["coverage"][0]["status"] == "missing_amount"


def test_preparation_fingerprints_checklist_and_rejects_oversize(settings):
    request, inventory = prepare()
    assert (
        request.request_envelope["source_packet"]["coverage_checklist"][0]["id"]
        == inventory[0]["id"]
    )
    settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS = 1
    with pytest.raises(PreflightUnavailable):
        prepare()


def test_failed_correction_retains_initial_usage():
    from apps.legislation.enhancements.providers.base import ProviderError

    request, inventory = prepare()
    responses = iter([result("A fine applies."), ProviderError("provider_unavailable")])

    def generate(request):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    report = candidate.run(request, inventory, generate)
    assert report["provider_calls"] == 2
    assert report["release_gate"] == "fail"
    assert report["attempts"][0]["usage"]["input_tokens"] == 100
    assert report["attempts"][1]["failure_category"] == "provider_unavailable"
    assert report["usage"]["input_tokens"] is None


def test_correction_keeps_prior_prose_and_rechecks_the_entire_output():
    request, inventory = prepare()
    seen = []

    def generate(request):
        seen.append(request)
        return result("A fine applies.")

    candidate.run(request, inventory, generate)
    previous = seen[1].request_envelope["source_packet"]["previous_explanations"][
        "funding_and_timing"
    ][0]
    assert previous["text"] == "A fine applies."
    assert "source_quotes" not in previous
    assert seen[0].request_fingerprint != seen[1].request_fingerprint


def test_correction_that_exceeds_budget_makes_no_second_call(settings):
    request, inventory = prepare()
    settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES = len(request.request_bytes)
    report = candidate.run(
        request, inventory, lambda request: result("A fine applies.")
    )
    assert report["provider_calls"] == 1
    assert report["correction_not_run"] == "request_too_large"
    assert report["release_gate"] == "fail"


def test_quote_failure_does_not_suppress_other_coverage_findings():
    request, inventory = prepare()
    bad = result("There is a fine.")
    bad.output["funding_and_timing"][0]["source_quotes"][0]["quote"] = "Not in the bill"
    report = candidate.run(request, inventory, lambda request: bad)
    assert report["initial_coverage"][0]["status"] == "missing_explanation"
    assert report["release_gate"] == "fail"


def test_schema_failure_retains_specific_safe_diagnostic():
    request, inventory = prepare()
    bad = result("x" * 601)
    report = candidate.run(request, inventory, lambda request: bad)
    assert report["attempts"][0]["validation_detail"]["code"] == "schema_maxLength"
    assert (
        report["attempts"][0]["validation_detail"]["path"]
        == "/funding_and_timing/0/text"
    )


def test_provider_receives_correction_findings_and_prior_prose():
    import json

    from apps.legislation.enhancements.providers.openai import OpenAIEnhancementProvider

    from .test_enhancement_openai_provider import (
        FakeClientFactory,
        FakeResponses,
        _completed_response,
    )

    request, inventory = prepare()
    response = _completed_response()
    response.output_text = json.dumps(result("There is a fine.").output)
    transport = FakeResponses(result=response)
    provider = OpenAIEnhancementProvider(client_factory=FakeClientFactory(transport))
    candidate.run(
        request,
        inventory,
        lambda req: provider.enhance_bill(
            api_key="test", request=req, timeout_seconds=10
        ),
    )
    sent = json.loads(transport.calls[1]["input"])["source_packet"]
    schema = transport.calls[0]["text"]["format"]["schema"]
    assert "coverage_response" in schema["required"]
    assert schema["properties"]["coverage_response"]["required"] == [inventory[0]["id"]]
    assert sent["coverage_findings"]["rows"][0]["status"] == "missing_amount"
    assert (
        sent["previous_explanations"]["funding_and_timing"][0]["text"]
        == "There is a fine."
    )


def test_missing_required_coverage_response_is_rejected():
    request, inventory = prepare()
    response = result("The fine is up to $10,000.")
    report = candidate.run(request, inventory, lambda request: response)
    assert report["release_gate"] == "fail"
    assert report["attempts"][0]["coverage_error"] == "coverage_response_invalid"
    assert report["provider_calls"] == 2


@pytest.mark.parametrize("path", ["overview/0", "funding_and_timing/999"])
def test_mapping_to_missing_or_unrelated_explanation_is_rejected(path):
    request, inventory = prepare()
    response = result("The fine is up to $10,000.")
    response.output["coverage_response"] = {
        inventory[0]["id"]: {
            "status": "explained",
            "output_paths": [path],
            "reason": "",
        }
    }
    report = candidate.run(request, inventory, lambda request: response)
    assert report["release_gate"] == "fail"
    assert report["coverage"][0]["status"] == "missing_explanation"


def test_explicit_unresolved_entry_is_retained_but_never_approved():
    request, inventory = prepare()
    response = result("The fine is up to $10,000.")
    response.output["coverage_response"] = {
        inventory[0]["id"]: {
            "status": "unresolved",
            "output_paths": [],
            "reason": "The scope of liability needs legal review.",
        }
    }
    report = candidate.run(request, inventory, lambda request: response)
    assert report["release_gate"] == "blocked"
    assert report["coverage"][0]["status"] == "unresolved"
    assert (
        report["coverage"][0]["reason"] == "The scope of liability needs legal review."
    )


@pytest.mark.parametrize(
    "entry",
    [
        {"status": "explained", "output_paths": [], "reason": ""},
        {"status": "unresolved", "output_paths": [], "reason": "  "},
        {
            "status": "unresolved",
            "output_paths": ["funding_and_timing/0"],
            "reason": "Unknown",
        },
        {
            "status": "explained",
            "output_paths": ["funding_and_timing/0", "funding_and_timing/0"],
            "reason": "",
        },
    ],
)
def test_contradictory_or_empty_coverage_entries_fail(entry):
    request, inventory = prepare()
    response = result("The fine is up to $10,000.")
    response.output["coverage_response"] = {inventory[0]["id"]: entry}
    report = candidate.run(request, inventory, lambda request: response)
    assert report["release_gate"] == "fail"
    assert report["attempts"][0]["coverage_error"] == "coverage_response_invalid"


def test_mapped_explanation_cannot_borrow_amount_from_an_unmapped_claim():
    import copy

    request, inventory = prepare()
    response = result("A fine applies.")
    other = copy.deepcopy(response.output["funding_and_timing"][0])
    other["text"] = "The fine is up to $10,000."
    response.output["funding_and_timing"].append(other)
    response.output["coverage_response"] = {
        inventory[0]["id"]: {
            "status": "explained",
            "output_paths": ["funding_and_timing/0"],
            "reason": "",
        }
    }
    report = candidate.run(request, inventory, lambda request: response)
    assert report["release_gate"] == "fail"
    assert report["coverage"][0]["status"] == "missing_amount"


def test_correction_can_drop_prior_draft_without_dropping_source_or_findings(settings):
    request, inventory = prepare()
    draft = result("A fine applies.").output
    draft["overview"] = [{"text": "x" * 20000}]
    settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES = len(request.request_bytes) + 3000
    fixed = candidate._correction(
        request,
        [
            {
                "id": inventory[0]["id"],
                "status": "missing_amount",
                "missing_amounts": ["$10,000"],
            }
        ],
        None,
        draft,
    )
    packet = fixed.request_envelope["source_packet"]
    assert packet["sources"] == request.request_envelope["source_packet"]["sources"]
    assert packet["coverage_findings"]["rows"][0]["missing_amounts"] == ["$10,000"]
    assert packet["previous_explanations_omitted"] is True
