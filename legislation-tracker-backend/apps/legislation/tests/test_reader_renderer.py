import pytest

from apps.legislation.extraction.reader_renderer import (
    render_reader_claim,
    split_evidence_span,
)
from apps.legislation.extraction.types import (
    ExtractedClaim,
    ExtractionWarning,
    SourceSpan,
)


def claim(category: str, fields: dict[str, object]) -> ExtractedClaim:
    evidence = SourceSpan(
        "[[Page 4]] The source provision.",
        10,
        43,
    )
    return ExtractedClaim(
        category=category,
        fields=fields,
        section_label="Sec. 2",
        evidence=(evidence,),
        rule_id="test.rule.v1",
        source_id="section-0",
        section_id="section-0",
    )


@pytest.mark.parametrize(
    ("item", "kind", "display_text", "actor", "action", "effect"),
    [
        (
            claim(
                "requirements",
                {
                    "modality": "required",
                    "actor": "the Secretary",
                    "action": "publish a report",
                    "object": "annual compliance",
                    "conditions": [],
                },
            ),
            "requirement",
            "Requires the Secretary to publish a report.",
            "the Secretary",
            "publish a report",
            "annual compliance",
        ),
        (
            claim(
                "requirements",
                {
                    "modality": "prohibited",
                    "actor": "the Secretary",
                    "action": "disclose patient records",
                    "object": None,
                    "conditions": [],
                },
            ),
            "prohibition",
            "Prohibits the Secretary from disclosing patient records.",
            "the Secretary",
            "disclose patient records",
            None,
        ),
        (
            claim(
                "requirements",
                {
                    "modality": "permitted",
                    "actor": "the Secretary",
                    "action": "issue grants",
                    "object": None,
                    "conditions": [],
                },
            ),
            "permission",
            "Allows the Secretary to issue grants.",
            "the Secretary",
            "issue grants",
            None,
        ),
        (
            claim(
                "amendment_operations",
                {
                    "target": "section 5 of the Act",
                    "operation": "replace",
                    "removed_text": "old text",
                    "inserted_text": "new text",
                },
            ),
            "amendment",
            "Changes section 5 of the Act by replacing “old text” with “new text”.",
            None,
            "replace",
            "new text",
        ),
        (
            claim(
                "applicability",
                {
                    "subject": "the reporting rule",
                    "scope": "covered entities",
                    "applicability_type": "applies",
                },
            ),
            "applicability",
            "Applies the reporting rule to covered entities.",
            "the reporting rule",
            "apply",
            "covered entities",
        ),
        (
            claim(
                "financial_items",
                {
                    "financial_action": "appropriation",
                    "direction": "increase",
                    "amount": "500000000.00",
                    "amount_type": "specified",
                    "currency": "USD",
                    "fiscal_years": [2026],
                    "purpose": "rural hospital grants",
                    "source_account": None,
                    "destination_account": None,
                },
            ),
            "financial",
            "Appropriates $500,000,000.00 for rural hospital grants for fiscal year 2026.",
            None,
            "appropriation",
            "rural hospital grants",
        ),
        (
            claim(
                "timeline_items",
                {
                    "timeline_type": "relative",
                    "date": None,
                    "relative_value": 30,
                    "relative_unit": "days",
                    "trigger": "enactment",
                },
            ),
            "timeline",
            "Sets a deadline 30 days after enactment.",
            None,
            "relative",
            "enactment",
        ),
        (
            claim(
                "definitions",
                {
                    "term": "covered entity",
                    "definition": "a rural hospital",
                    "definition_type": "means",
                },
            ),
            "definition",
            "Defines “covered entity” to mean a rural hospital.",
            None,
            "define",
            "a rural hospital",
        ),
    ],
)
def test_reader_claim_templates_use_validated_structured_fields(
    item, kind, display_text, actor, action, effect
):
    rendered = render_reader_claim(item)

    assert not isinstance(rendered, ExtractionWarning)
    assert rendered.kind == kind
    assert rendered.display_text == display_text
    assert rendered.actor == actor
    assert rendered.action == action
    assert rendered.effect == effect
    assert rendered.display_text.endswith(".")
    assert "[[" not in rendered.display_text


@pytest.mark.parametrize(
    "item",
    [
        claim(
            "requirements",
            {
                "modality": "required",
                "actor": None,
                "action": "publish a report",
                "object": None,
                "conditions": [],
            },
        ),
        claim(
            "amendment_operations",
            {
                "target": None,
                "operation": "amend",
                "removed_text": None,
                "inserted_text": None,
            },
        ),
    ],
)
def test_reader_claim_templates_return_typed_warnings_for_missing_slots(item):
    rendered = render_reader_claim(item)

    assert isinstance(rendered, ExtractionWarning)
    assert rendered.code == "reader_required_slot_missing"
    assert rendered.evidence == item.evidence


def test_long_evidence_chunks_reconstruct_exact_source():
    span = SourceSpan(text="x" * 9_001, start_char=100, end_char=9_101)

    chunks = split_evidence_span(span)

    assert all(len(chunk.text) <= 4_000 for chunk in chunks)
    assert "".join(chunk.text for chunk in chunks) == span.text
    assert [(chunk.start_char, chunk.end_char) for chunk in chunks] == [
        (100, 4_100),
        (4_100, 8_100),
        (8_100, 9_101),
    ]
