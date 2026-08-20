from apps.legislation.extraction.renderer import render_contract
from apps.legislation.extraction.types import (
    ExtractedClaim,
    SourceSpan,
    StructuralSection,
)


def make_claim(category, fields, source, text, rule_id, section_label="Sec. 2"):
    start = source.index(text)
    return ExtractedClaim(
        category=category,
        fields=fields,
        section_label=section_label,
        evidence=(SourceSpan(text, start, start + len(text)),),
        rule_id=rule_id,
    )


def test_render_contract_uses_controlled_templates_and_exact_evidence_paths():
    requirement = "The Secretary shall publish a report."
    funding = "There is appropriated $25,000,000 for fiscal year 2027."
    timeline = "Not later than 90 days after enactment, the report is due."
    definition = 'The term "covered entity" means a rural hospital.'
    applicability = "The program applies to rural hospitals."
    amendment = 'In section 5, replace "old" with "new".'
    source = (
        f"{requirement}\n{funding}\n{timeline}\n{definition}\n"
        f"{applicability}\n{amendment}"
    )
    section = StructuralSection(
        label="Sec. 2",
        heading="Program",
        level="section",
        span=SourceSpan(source, 0, len(source)),
        parent_label=None,
    )
    claims = (
        make_claim(
            "requirements",
            {
                "modality": "required",
                "actor": "The Secretary",
                "action": "publish a report",
                "object": None,
                "conditions": [],
            },
            source,
            requirement,
            "modality.shall.v1",
        ),
        make_claim(
            "funding_items",
            {
                "amount": "25000000.00",
                "amount_type": "specified",
                "currency": "USD",
                "fiscal_years": [2027],
                "purpose": None,
            },
            source,
            funding,
            "funding.appropriation.v1",
        ),
        make_claim(
            "timeline_items",
            {
                "timeline_type": "relative",
                "date": None,
                "relative_value": 90,
                "relative_unit": "days",
                "trigger": "enactment",
            },
            source,
            timeline,
            "timeline.relative_deadline.v1",
        ),
        make_claim(
            "definitions",
            {
                "term": "covered entity",
                "definition": "a rural hospital",
                "definition_type": "means",
            },
            source,
            definition,
            "definition.term_means.v1",
        ),
        make_claim(
            "applicability",
            {
                "subject": "The program",
                "scope": "rural hospitals",
                "applicability_type": "applies",
            },
            source,
            applicability,
            "applicability.applies.v1",
        ),
        make_claim(
            "amendment_operations",
            {
                "target": "section 5",
                "operation": "replace",
                "removed_text": "old",
                "inserted_text": "new",
            },
            source,
            amendment,
            "amendment.replace.v1",
        ),
    )

    result = render_contract(
        title="Test Act",
        version_label="Introduced",
        sections=(section,),
        claims=claims,
        source_text=source,
    )

    contract = result.contract_json
    assert contract["requirements"][0]["display_text"] == (
        "The Secretary is required to publish a report."
    )
    assert contract["funding_items"][0]["display_text"] == (
        "Funding of $25,000,000.00 is specified for fiscal year 2027."
    )
    assert contract["timeline_items"][0]["display_text"] == (
        "A deadline occurs 90 days after enactment."
    )
    assert contract["definitions"][0]["display_text"] == (
        '“covered entity” means a rural hospital.'
    )
    assert contract["applicability"][0]["display_text"] == (
        "The program applies to rural hospitals."
    )
    assert contract["amendment_operations"][0]["display_text"] == (
        "section 5 replaces “old” with “new”."
    )
    assert contract["plain_summary"] == (
        "The Secretary is required to publish a report. "
        "Funding of $25,000,000.00 is specified for fiscal year 2027. "
        "A deadline occurs 90 days after enactment."
    )
    assert len(contract["key_provisions"]) == 6
    paths = [candidate.field_path for candidate in result.evidence]
    assert paths.count("plain_summary") == 3
    assert "key_provisions[0].text" in paths
    assert "requirements[0].display_text" in paths
    assert "definitions[0].term" in paths
    assert "definitions[0].display_text" in paths
    assert result == render_contract(
        title="Test Act",
        version_label="Introduced",
        sections=(section,),
        claims=claims,
        source_text=source,
    )


def test_render_contract_deduplicates_then_caps_categories_deterministically():
    sentences = [f"Agency {index} shall report." for index in range(101)]
    source = " ".join(sentences)
    section = StructuralSection(
        label="Sec. 3",
        heading="Reports",
        level="section",
        span=SourceSpan(source, 0, len(source)),
        parent_label=None,
    )
    claims = tuple(
        make_claim(
            "requirements",
            {
                "modality": "required",
                "actor": f"Agency {index}",
                "action": "report",
                "object": None,
                "conditions": [],
            },
            source,
            sentence,
            "modality.shall.v1",
            "Sec. 3",
        )
        for index, sentence in enumerate(sentences)
    )

    result = render_contract(
        title="Reports Act",
        version_label="Introduced",
        sections=(section,),
        claims=claims + (claims[0],),
        source_text=source,
    )

    assert len(result.contract_json["requirements"]) == 100
    assert len(result.contract_json["key_provisions"]) == 10
    assert result.contract_json["extraction"]["warnings"] == [
        "item_limit_reached:requirements"
    ]


def test_render_amendment_omits_missing_optional_payloads():
    source = "Section 5 is replaced."
    section = StructuralSection(
        label="Sec. 2",
        heading="Amendment",
        level="section",
        span=SourceSpan(source, 0, len(source)),
        parent_label=None,
    )
    claim = make_claim(
        "amendment_operations",
        {
            "target": "section 5",
            "operation": "replace",
            "removed_text": None,
            "inserted_text": None,
        },
        source,
        source,
        "amendment.replace.v1",
    )

    result = render_contract(
        title="Amendment Act",
        version_label="Introduced",
        sections=(section,),
        claims=(claim,),
        source_text=source,
    )

    display = result.contract_json["amendment_operations"][0]["display_text"]
    assert display == "section 5 is replaced."
    assert "None" not in display
