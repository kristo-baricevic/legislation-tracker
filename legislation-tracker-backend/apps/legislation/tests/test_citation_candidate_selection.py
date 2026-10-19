import copy
import json

import pytest
from jsonschema import ValidationError

from apps.legislation.enhancements.citations import (
    REPAIR_INSTRUCTIONS,
    REPAIR_SCHEMA,
    citation_spans,
    resolve_citations,
)
from apps.legislation.enhancements.providers.base import ProviderResult, ProviderUsage
from apps.legislation.enhancements.schema import validate_enhancement_output

from .test_citation_resolution import result, source


def selection(path, candidate):
    return ProviderResult(
        {"repairs": [{"id": path, "candidate_id": candidate}]},
        ProviderUsage(4, 3, 7),
        "repair",
        "test",
    )


def test_model_selects_verified_excerpt_instead_of_rewriting_official():
    original = "bring an action against the Secretary of Homeland Security."
    sources = [
        source(
            "src_0001",
            "Detention: "
            + original
            + " Visas: bring an action against the Secretary of State. Release: "
            + original,
        )
    ]

    def repair(payload):
        assert "candidates" in payload
        item = payload["citations"][0]
        allowed = [
            c
            for c in payload["candidates"]
            if c["candidate_id"] in item["candidate_ids"]
        ]
        assert len(allowed) == 2
        assert all(original in c["quote"] for c in allowed)
        assert all(
            len(citation_spans(sources[0]["quoted_text"], c["quote"])) == 1
            for c in allowed
        )
        return selection(item["id"], allowed[0]["candidate_id"])

    fixed = resolve_citations(result(original), sources, repair=repair)
    validate_enhancement_output(fixed.output, sources)
    assert original in fixed.output["overview"][0]["source_quotes"][0]["quote"]


def test_repeated_claims_share_candidate_text_once():
    original = result()
    original.output["overview"].append(copy.deepcopy(original.output["overview"][0]))
    sources = [
        source(
            "src_0001",
            "Schools: Funds shall be provided. Roads: Funds shall be provided.",
        )
    ]

    def repair(payload):
        assert len(payload["candidates"]) == 2
        assert (
            payload["citations"][0]["candidate_ids"]
            == payload["citations"][1]["candidate_ids"]
        )
        assert all("candidates" not in c for c in payload["citations"])
        return ProviderResult(
            {
                "repairs": [
                    dict(id=c["id"], candidate_id=c["candidate_ids"][0])
                    for c in payload["citations"]
                ]
            },
            ProviderUsage(4, 3, 7),
            "repair",
            "test",
        )

    fixed = resolve_citations(original, sources, repair=repair)
    validate_enhancement_output(fixed.output, sources)


def test_candidate_from_other_quote_cannot_be_selected():
    original = result("DHS shall report.")
    other = result("State shall report.").output["overview"][0]
    original.output["overview"].append(other)
    sources = [
        source(
            "src_0001",
            "A: DHS shall report. B: DHS shall report. C: State shall report. D: State shall report.",
        )
    ]

    def repair(payload):
        own = set(payload["citations"][0]["candidate_ids"])
        foreign = next(
            x for x in payload["citations"][1]["candidate_ids"] if x not in own
        )
        return selection("overview/0/0", foreign)

    fixed = resolve_citations(original, sources, repair=repair)
    with pytest.raises(ValidationError):
        validate_enhancement_output(fixed.output, sources)
    assert fixed.citation_resolution["corrections"] == []


def test_saved_s5_fits_production_cap_and_never_offers_changed_official():
    from apps.legislation.evaluation.whole_bill import ROOT

    saved = json.loads((ROOT / "ai-baseline-2026-10-15-funded.json").read_text())
    row = next(r for r in saved["results"] if r["case_id"] == "BILLS-119s5enr")
    calls = []

    def repair(payload):
        calls.append(payload)
        encoded = json.dumps(
            dict(input=payload, instructions=REPAIR_INSTRUCTIONS, schema=REPAIR_SCHEMA),
            ensure_ascii=False,
        ).encode()
        assert len(encoded) <= row["estimated_input_tokens_upper_bound"]
        claim = next(c for c in payload["citations"] if c["id"] == "obligations/2/3")
        candidates = [
            c
            for c in payload["candidates"]
            if c["candidate_id"] in claim["candidate_ids"]
        ]
        assert len(candidates) == 2
        assert all("Secretary of Homeland Security" in c["quote"] for c in candidates)
        # Mechanical replay: selecting an allowed occurrence must preserve wording.
        # This does not award semantic correctness to the selection.
        return ProviderResult(
            {
                "repairs": [
                    dict(id=c["id"], candidate_id=c["candidate_ids"][0])
                    for c in payload["citations"]
                ]
            },
            ProviderUsage(4, 3, 7),
            "repair",
            "test",
        )

    fixed = resolve_citations(
        ProviderResult(row["output"], ProviderUsage(**row["usage"]), "", "test"),
        row["source_snapshot"],
        repair=repair,
        max_request_bytes=row["estimated_input_tokens_upper_bound"],
    )
    assert len(calls) == 1
    validate_enhancement_output(fixed.output, row["source_snapshot"])
