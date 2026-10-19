import copy
import hashlib

import pytest
from jsonschema import ValidationError

from apps.legislation.enhancements import citations
from apps.legislation.enhancements.providers.base import (
    ProviderError,
    ProviderResult,
    ProviderUsage,
)
from apps.legislation.enhancements.schema import validate_enhancement_output


def source(ref, text, start=0):
    return dict(
        source_ref=ref,
        quoted_text=text,
        start_char=start,
        end_char=start + len(text),
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
    )


def result(quote="Funds shall be provided.", ref="src_0001"):
    return ProviderResult(
        output=dict(
            schema_version="1.2",
            overview=[
                dict(
                    text="The program receives funding.",
                    source_refs=[ref],
                    source_quotes=[dict(source_ref=ref, quote=quote)],
                )
            ],
            key_impacts=[],
            obligations=[],
            funding_and_timing=[],
            uncertain_language=[],
        ),
        usage=ProviderUsage(10, 5, 15),
        response_id="original",
        resolved_model="test",
    )


def resolve(*args, **kwargs):
    # Import through module so the first red run fails on the missing behavior.
    return citations.resolve_citations(*args, **kwargs)


def test_wrong_reference_is_corrected_without_changing_claim_or_original():
    original = result()
    before = copy.deepcopy(original.output)
    sources = [
        source("src_0001", "Other text."),
        source("src_0002", "Funds\nshall be provided.", 20),
    ]
    fixed = resolve(original, sources)
    assert original.output == before
    assert fixed.output["overview"][0]["text"] == before["overview"][0]["text"]
    assert fixed.output["overview"][0]["source_refs"] == ["src_0002"]
    assert (
        fixed.citation_resolution["corrections"][0]["original"]["source_ref"]
        == "src_0001"
    )
    assert fixed.citation_resolution["corrections"][0]["start_char"] == 20
    validate_enhancement_output(fixed.output, sources)


def test_unknown_reference_can_only_be_repaired_from_verified_snapshot():
    sources = [source("src_0001", "Funds shall be provided.")]
    fixed = resolve(result(ref="src_9999"), sources)
    validate_enhancement_output(fixed.output, sources)
    sources[0]["text_sha256"] = "invalid"
    unchanged = resolve(result(ref="src_9999"), sources)
    assert unchanged.output["overview"][0]["source_refs"] == ["src_9999"]


def test_repairs_cannot_add_claim_edits_or_duplicate_ids():
    sources = [
        source(
            "src_0001",
            "Schools: Funds shall be provided. Roads: Funds shall be provided.",
        )
    ]
    for patches in [
        [
            dict(
                id="overview/0/0",
                candidate_id="candidate_0001",
                text="Altered claim",
            )
        ],
        [
            dict(
                id="overview/0/0",
                candidate_id="candidate_0001",
            )
        ]
        * 2,
    ]:
        fixed = resolve(
            result(),
            sources,
            repair=lambda _, patches=patches: ProviderResult(
                {"repairs": patches}, ProviderUsage(4, 3, 7), "repair", "test"
            ),
        )
        assert fixed.output == result().output
        assert fixed.usage.total_tokens == 22


def test_overlap_is_one_location_but_distinct_positions_are_not():
    sources = [
        source("src_0001", "Other text."),
        source("src_0002", "Funds shall be provided.", 20),
        source("src_0003", "Before. Funds shall be provided.", 12),
    ]
    fixed = resolve(result(), sources)
    validate_enhancement_output(fixed.output, sources)
    sources[2] = source("src_0003", "Funds shall be provided.", 100)
    ambiguous = resolve(result(), sources)
    with pytest.raises(ValidationError):
        validate_enhancement_output(ambiguous.output, sources)


def test_repair_is_single_targeted_call_and_usage_is_combined():
    sources = [
        source(
            "src_0001",
            "Schools: Funds shall be provided. Roads: Funds shall be provided.",
        )
    ]
    calls = []

    def repair(payload):
        calls.append(payload)
        return ProviderResult(
            output={
                "repairs": [
                    dict(
                        id="overview/0/0",
                        candidate_id="candidate_0001",
                    )
                ]
            },
            usage=ProviderUsage(4, 3, 7),
            response_id="repair",
            resolved_model="test",
        )

    fixed = resolve(result(), sources, repair=repair)
    validate_enhancement_output(fixed.output, sources)
    assert len(calls) == 1
    assert len(calls[0]["citations"]) == 1
    assert fixed.usage == ProviderUsage(14, 8, 22)
    assert fixed.citation_resolution["repair"]["response_id"] == "repair"


@pytest.mark.parametrize("replacement", ["Roads: $200.", "Funds shall be provided."])
def test_repair_cannot_change_quote_meaning_or_leave_ambiguity(replacement):
    sources = [
        source(
            "src_0001", "Funds shall be provided. Funds shall be provided. Roads: $200."
        )
    ]
    calls = []

    def repair(payload):
        calls.append(payload)
        return ProviderResult(
            output={
                "repairs": [
                    dict(id="overview/0/0", source_ref="src_0001", quote=replacement)
                ]
            },
            usage=ProviderUsage(4, 3, 7),
            response_id="repair",
            resolved_model="test",
        )

    fixed = resolve(result(), sources, repair=repair)
    with pytest.raises(ValidationError):
        validate_enhancement_output(fixed.output, sources)
    assert fixed.usage.total_tokens == 22
    assert len(calls) == 1


def test_missing_quote_is_not_invented_or_sent_for_paid_repair():
    def repair(payload):
        pytest.fail("No source candidates: do not ask the provider to invent evidence")

    fixed = resolve(result("$900"), [source("src_0001", "$100")], repair=repair)
    with pytest.raises(ValidationError):
        validate_enhancement_output(fixed.output, [source("src_0001", "$100")])


@pytest.mark.parametrize("text", ["$1000", "$100,000", "$100.50"])
def test_partial_amount_cannot_be_accepted_as_a_quote(text):
    sources = [source("src_0001", text)]
    fixed = resolve(result("$100"), sources)
    with pytest.raises(ValidationError):
        validate_enhancement_output(fixed.output, sources)


def test_repair_timeout_retains_original_usage_and_audit():
    def repair(payload):
        raise ProviderError("outcome_unknown", outcome_unknown=True)

    with pytest.raises(ProviderError) as error:
        resolve(
            result(),
            [source("src_0001", "Funds shall be provided. Funds shall be provided.")],
            repair=repair,
        )
    assert error.value.citation_resolution["initial_usage"]["total_tokens"] == 15
    assert error.value.usage.total_tokens is None


def test_repair_budget_skips_call_without_losing_initial_usage():
    def repair(payload):
        pytest.fail("Oversize repair must not call provider")

    fixed = resolve(
        result(),
        [source("src_0001", "Funds shall be provided. Funds shall be provided.")],
        repair=repair,
        max_request_bytes=1,
    )
    assert fixed.usage.total_tokens == 15
    assert fixed.citation_resolution["repair"]["status"] == "budget_exceeded"
