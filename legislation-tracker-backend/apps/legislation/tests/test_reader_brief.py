from apps.legislation.extraction.federal_structure import parse_federal_structure
from apps.legislation.extraction.financial_rules import extract_financial_claims
from apps.legislation.extraction.legal_rules import extract_claims
from apps.legislation.extraction.reader_brief import build_reader_brief
from apps.legislation.extraction.types import ExtractedClaim, SourceSpan


def reader_claims(source: str):
    legacy_claims = tuple(
        item
        for item in extract_claims(source, parse_federal_structure(source))
        if item.category != "funding_items"
    )
    return legacy_claims + extract_financial_claims(
        source, parse_federal_structure(source)
    )


def test_same_section_alone_does_not_create_line_level_financial_link():
    source = """SEC. 240. HEALTH PROGRAMS
The Secretary shall establish the Rural Grant Program.
The Secretary shall establish the Clinic Loan Program.
There is appropriated $5,000,000 for implementation.
"""
    sections = parse_federal_structure(source)

    brief = build_reader_brief(reader_claims(source), sections)

    financial_id = f"financial-{source.index('There is appropriated')}-1"
    assert all(item.exact_financial_refs == () for item in brief.line_items[:2])
    assert brief.section_groups[0].section_financial_refs == (financial_id,)


def test_shared_clause_creates_an_exact_financial_link():
    source = """SEC. 241. GRANTS
The Secretary shall allocate $20,000,000 for rural hospital grants.
"""
    sections = parse_federal_structure(source)

    brief = build_reader_brief(reader_claims(source), sections)

    assert len(brief.line_items) == 1
    assert brief.line_items[0].kind == "requirement"
    assert brief.line_items[0].exact_financial_refs == (
        f"financial-{source.index('The Secretary')}-1",
    )
    assert brief.section_groups[0].section_financial_refs == ()


def test_shared_evidence_must_identify_exactly_one_reader_line():
    source = "SEC. 241. SHARED CLAUSE\nOne source clause.\n"
    sections = parse_federal_structure(source)
    section = sections[0]
    start = source.index("One source")
    span = SourceSpan(source[start:].strip(), start, len(source) - 1)

    def requirement(action: str) -> ExtractedClaim:
        return ExtractedClaim(
            category="requirements",
            fields={
                "modality": "required",
                "actor": "the Secretary",
                "action": action,
                "object": None,
                "conditions": [],
            },
            section_label=section.label,
            evidence=(span,),
            rule_id="test.requirement.v1",
            source_id=section.source_id,
            section_id=section.source_id,
            section_path=section.path,
        )

    financial = ExtractedClaim(
        category="financial_items",
        fields={
            "financial_action": "allocation",
            "direction": "increase",
            "amount": "5000000.00",
            "amount_type": "specified",
            "currency": "USD",
            "fiscal_years": [],
            "purpose": None,
            "source_account": None,
            "destination_account": None,
        },
        section_label=section.label,
        evidence=(span,),
        rule_id="test.financial.v1",
        source_id=section.source_id,
        section_id=section.source_id,
        section_path=section.path,
    )

    brief = build_reader_brief(
        (
            requirement("establish Program A"),
            requirement("establish Program B"),
            financial,
        ),
        sections,
    )

    assert all(item.exact_financial_refs == () for item in brief.line_items)
    assert brief.section_groups[0].section_financial_refs == (f"financial-{start}-1",)


def test_explicit_unique_purpose_reference_creates_an_exact_financial_link():
    source = """SEC. 242. PROGRAMS
The Secretary shall establish the Rural Hospital Grants program.
The Secretary shall establish the Clinic Loans program.
There is appropriated $9,000,000 for rural hospital grants.
"""
    sections = parse_federal_structure(source)

    brief = build_reader_brief(reader_claims(source), sections)

    assert len(brief.line_items[0].exact_financial_refs) == 1
    assert brief.line_items[1].exact_financial_refs == ()
    assert brief.section_groups[0].section_financial_refs == ()


def test_timeline_only_section_creates_a_standalone_reader_line():
    source = """SEC. 243. EFFECTIVE DATE
This section takes effect on January 1, 2028.
"""
    sections = parse_federal_structure(source)

    brief = build_reader_brief(reader_claims(source), sections)

    assert len(brief.line_items) == 1
    assert brief.line_items[0].kind == "timeline"
    assert brief.line_items[0].timeline_refs == (
        f"timeline-{source.index('This section')}-1",
    )
    assert brief.section_groups[0].section_timeline_refs == ()


def test_financial_only_section_creates_a_standalone_reader_line():
    source = """SEC. 244. RESCISSION
$3,000,000 in unobligated balances is hereby rescinded.
"""
    sections = parse_federal_structure(source)

    brief = build_reader_brief(reader_claims(source), sections)

    assert len(brief.line_items) == 1
    assert brief.line_items[0].kind == "financial"
    assert brief.line_items[0].exact_financial_refs == (
        f"financial-{source.index('$3,000,000')}-1",
    )
    assert brief.section_groups[0].section_financial_refs == ()


def test_each_unassociated_money_and_timeline_item_gets_a_standalone_line():
    source = """SEC. 244A. STANDALONE ITEMS
$3,000,000 in unobligated balances is hereby rescinded.
$2,000,000 in budget authority is hereby canceled.
This section takes effect on January 1, 2028.
This program takes effect on February 1, 2028.
"""
    sections = parse_federal_structure(source)

    brief = build_reader_brief(reader_claims(source), sections)

    assert [item.kind for item in brief.line_items] == [
        "financial",
        "financial",
        "timeline",
        "timeline",
    ]
    assert all(
        len(item.exact_financial_refs) == 1
        for item in brief.line_items
        if item.kind == "financial"
    )
    assert all(
        len(item.timeline_refs) == 1
        for item in brief.line_items
        if item.kind == "timeline"
    )
    assert brief.section_groups[0].section_financial_refs == ()
    assert brief.section_groups[0].section_timeline_refs == ()


def test_unrenderable_financial_claim_warns_without_counting_or_linking():
    source = """SEC. 244B. VALID MONEY
$3,000,000 in unobligated balances is hereby rescinded.
"""
    sections = parse_federal_structure(source)
    valid = extract_financial_claims(source, sections)[0]
    malformed = ExtractedClaim(
        category="financial_items",
        fields={
            **valid.fields,
            "financial_action": "transfer",
            "direction": "neutral_transfer",
            "destination_account": None,
        },
        section_label=valid.section_label,
        evidence=valid.evidence,
        rule_id="test.malformed_financial.v1",
        source_id=valid.source_id,
        section_id=valid.section_id,
        section_path=valid.section_path,
    )

    brief = build_reader_brief((malformed, valid), sections)

    assert [item.id for item in brief.financial_items] == [
        f"financial-{valid.evidence[0].start_char}-1"
    ]
    assert brief.reader_stats.financial_item_count == 1
    assert brief.line_items[0].exact_financial_refs == (brief.financial_items[0].id,)
    assert [warning.code for warning in brief.warnings] == [
        "reader_required_slot_missing"
    ]


def test_definitions_link_only_by_exact_normalized_term_occurrence():
    source = """SEC. 245. REQUIREMENTS
The Secretary shall provide assistance to each covered entity.
The Secretary shall cover entities in the annual report.
SEC. 246. DEFINITIONS
The term “covered entity” means a rural hospital.
"""
    sections = parse_federal_structure(source)

    brief = build_reader_brief(reader_claims(source), sections)

    definition_id = f"definition-{source.index('The term')}-1"
    assert brief.line_items[0].definition_refs == (definition_id,)
    assert brief.line_items[1].definition_refs == ()


def test_reader_brief_is_source_ordered_and_reports_complete_counts():
    source = """SEC. 247. COMPLETE READER
The Secretary shall publish a report not later than 30 days after enactment.
There is appropriated $1,000,000 for the reporting program.
"""
    sections = parse_federal_structure(source)

    brief = build_reader_brief(reader_claims(source), sections)

    assert [item.id for item in brief.line_items] == sorted(
        (item.id for item in brief.line_items),
        key=lambda item_id: int(item_id.rsplit("-", 2)[-2]),
    )
    assert brief.reader_stats.line_item_count == len(brief.line_items)
    assert brief.reader_stats.financial_item_count == 1
    assert brief.reader_stats.timeline_item_count == 1
    assert brief.reader_stats.definition_item_count == 0
    assert brief.reader_stats.section_group_count == 1
    assert brief.orientation.purpose_clause is None
    assert brief.orientation.purpose_line_item_id is None
    assert "1 financial provision" in brief.coverage_note
    assert "1 deadline or effective date" in brief.coverage_note


def test_explicit_statutory_purpose_becomes_evidence_backed_orientation():
    source = """SEC. 1. PURPOSE
The purpose of this Act is to improve access to rural health care.
SEC. 2. REPORT
The Secretary shall publish an annual report.
"""
    sections = parse_federal_structure(source)

    brief = build_reader_brief(reader_claims(source), sections)

    assert brief.orientation.purpose_clause == (
        "This bill aims to improve access to rural health care."
    )
    assert brief.orientation.purpose_line_item_id is not None
    purpose_line = next(
        item
        for item in brief.line_items
        if item.id == brief.orientation.purpose_line_item_id
    )
    assert purpose_line.kind == "purpose"
    assert purpose_line.display_text == brief.orientation.purpose_clause
    assert purpose_line.evidence[0].text == (
        "The purpose of this Act is to improve access to rural health care."
    )
    assert (
        source[purpose_line.evidence[0].start_char : purpose_line.evidence[0].end_char]
        == purpose_line.evidence[0].text
    )


def test_quoted_prior_law_purpose_does_not_become_bill_orientation():
    source = """SEC. 1. AMENDMENT
Section 2 of prior law is amended by inserting [[QUOTED_BLOCK_START]]The purpose of this Act is to replace the former program.[[QUOTED_BLOCK_END]].
SEC. 2. REPORT
The Secretary shall publish an annual report.
"""
    sections = parse_federal_structure(source)

    brief = build_reader_brief(reader_claims(source), sections)

    assert brief.orientation.purpose_clause is None
    assert brief.orientation.purpose_line_item_id is None
    assert all(item.kind != "purpose" for item in brief.line_items)


def test_missing_required_slots_never_create_section_number_only_lines():
    source = "SEC. 248. AMENDMENT\nSection 5 is amended.\n"
    sections = parse_federal_structure(source)
    claims = list(reader_claims(source))
    claims[0] = claims[0].__class__(
        **{**claims[0].__dict__, "fields": {**claims[0].fields, "target": None}}
    )

    brief = build_reader_brief(tuple(claims), sections)

    assert brief.line_items == ()
    assert brief.warnings[0].code == "reader_required_slot_missing"
