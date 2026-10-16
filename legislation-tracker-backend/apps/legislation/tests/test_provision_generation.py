from apps.legislation.enhancements.providers.base import ProviderResult, ProviderUsage
from apps.legislation.evaluation import provision_generation as generation

from .test_coverage_candidate import prepare


def test_every_provision_has_its_own_explanation_and_evidence():
    request, inventory = prepare()

    def generate(req):
        return ProviderResult(
            output={
                "provisions": {
                    inventory[0]["id"]: {
                        "status": "explained",
                        "text": "Anyone who knowingly discloses records must pay a fine of up to $10,000.",
                        "reason": "",
                        "source_quotes": [
                            {
                                "source_ref": "src_0001",
                                "quote": "A person shall be fined up to $10,000 for knowingly disclosing records.",
                            }
                        ],
                    }
                }
            },
            usage=ProviderUsage(10, 20, 30),
            response_id="test",
            resolved_model="test",
        )

    report = generation.run(request, inventory, generate)
    assert report["provider_calls"] == 1
    assert report["coverage"][0]["status"] == "needs_semantic_review"
    assert report["release_gate"] == "blocked"
    assert report["provisions"][0]["text"].startswith("Anyone")


def test_missing_provision_cannot_hide_in_overall_summary():
    request, inventory = prepare()
    report = generation.run(
        request,
        inventory,
        lambda req: ProviderResult(
            output={"provisions": {}},
            usage=ProviderUsage(1, 1, 2),
            response_id="test",
            resolved_model="test",
        ),
    )
    assert report["release_gate"] == "fail"
    assert report["attempts"][0]["validation_error"] == "coverage_response_invalid"


def test_four_passes_partition_ids_without_dropping_full_source_context():
    request, inventory = prepare()
    rows = [dict(inventory[0], id=f"item_{i}") for i in range(31)]
    batches = generation.requests(request, rows)
    assert len(batches) == 4
    assert all(len(items) <= 8 for _, items in batches)
    ids = [r["id"] for req, items in batches for r in items]
    assert ids == [f"item_{i}" for i in range(31)]
    for req, items in batches:
        assert req.source_snapshot == request.source_snapshot
        assert (
            req.request_envelope["source_packet"]["sources"]
            == request.request_envelope["source_packet"]["sources"]
        )
        assert set(
            req.request_envelope["output_schema"]["properties"]["provisions"][
                "required"
            ]
        ) == {r["id"] for r in items}


def test_oversized_inventory_is_rejected_before_spending():
    import pytest

    from apps.legislation.enhancements.source_packet import PreflightUnavailable

    request, inventory = prepare()
    rows = [dict(inventory[0], id=f"item_{i}") for i in range(33)]
    with pytest.raises(PreflightUnavailable):
        generation.run(request, rows, lambda req: pytest.fail("must not dispatch"))


def test_provider_receives_provision_contract_not_legacy_summary_schema():
    import json

    from apps.legislation.enhancements.providers.openai import OpenAIEnhancementProvider

    from .test_enhancement_openai_provider import (
        FakeClientFactory,
        FakeResponses,
        _completed_response,
    )

    request, inventory = prepare()
    response = _completed_response()
    response.output_text = json.dumps({"provisions": {}})
    transport = FakeResponses(result=response)
    provider = OpenAIEnhancementProvider(client_factory=FakeClientFactory(transport))
    generation.run(
        request,
        inventory,
        lambda req: provider.enhance_bill(
            api_key="test", request=req, timeout_seconds=10
        ),
    )
    sent = transport.calls[0]
    assert sent["text"]["format"]["schema"]["required"] == ["provisions"]
    assert (
        json.loads(sent["input"])["source_packet"]["coverage_checklist"][0]["id"]
        == inventory[0]["id"]
    )


def test_quote_spanning_chunks_is_split_without_changing_the_explanation():
    import hashlib

    row = {
        "start_char": 0,
        "end_char": 29,
        "source_text": "A fee is required. It is $25.",
    }
    text = row["source_text"]
    sources = []
    for i, (start, end) in enumerate(((0, 18), (19, len(text)))):
        raw = text[start:end]
        sources.append(
            {
                "source_ref": f"src_{i}",
                "start_char": start,
                "end_char": end,
                "quoted_text": raw,
                "text_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            }
        )
    quote = {"source_ref": "src_0", "quote": text}
    repaired, audit = generation.resolve_quote(quote, row, sources)
    assert repaired == [
        {"source_ref": "src_0", "quote": "A fee is required."},
        {"source_ref": "src_1", "quote": "It is $25."},
    ]
    assert audit["method"] == "source_span_split"


def test_quote_split_refuses_missing_substantive_source():
    row = {"start_char": 0, "source_text": "A fee is required unless waived."}
    sources = [
        {
            "source_ref": "src_0",
            "start_char": 0,
            "end_char": 17,
            "quoted_text": "A fee is required",
        },
        {
            "source_ref": "src_1",
            "start_char": 25,
            "end_char": 32,
            "quoted_text": "waived.",
        },
    ]
    quote = {"source_ref": "src_0", "quote": row["source_text"]}
    assert generation.resolve_quote(quote, row, sources) == ([quote], None)


def test_quote_split_does_not_rewrite_a_substantive_difference():
    row = {
        "start_char": 0,
        "source_text": "The Secretary of Homeland Security must report.",
    }
    quote = {"source_ref": "src_0", "quote": "The Secretary of State must report."}
    assert generation.resolve_quote(quote, row, []) == ([quote], None)
