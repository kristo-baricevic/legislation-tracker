import pytest

from apps.legislation.extraction.federal_structure import (
    parse_federal_structure,
    sentence_spans,
)
from apps.legislation.extraction.types import ExpectedExtractionRejection

FULL_HIERARCHY_SOURCE = """DIVISION A—PUBLIC HEALTH
TITLE I—GENERAL PROVISIONS
SUBCHAPTER A—PROGRAM ADMINISTRATION
ACCOUNT 001—RURAL HEALTH
SEC. 101. REPORTING
(a) IN GENERAL.—
(1) REQUIREMENTS.—
(A) REPORT.—
(i) DEADLINE.—The Secretary shall publish a report.
"""


def test_parse_federal_structure_preserves_offsets_and_hierarchy():
    source = """  TITLE I—GENERAL PROVISIONS
SUBTITLE A Administration
PART I—PROGRAMS
SEC. 101A-1. Establishment
(a) In General.—The Secretary shall establish a program.
(1) Requirements.—The program shall serve rural areas.
(A) Priority.—Priority shall be given to hospitals.
(i) Timing.—Implementation begins immediately.
SECTION 102.
REPORTS AND OVERSIGHT
The Secretary shall publish a report.
"""

    sections = parse_federal_structure(source)

    assert [
        (section.level, section.label, section.heading) for section in sections
    ] == [
        ("title", "Title I", "GENERAL PROVISIONS"),
        ("subtitle", "Subtitle A", "Administration"),
        ("part", "Part I", "PROGRAMS"),
        ("section", "Sec. 101A-1", "Establishment"),
        ("subsection", "(a)", "In General"),
        ("paragraph", "(1)", "Requirements"),
        ("subparagraph", "(A)", "Priority"),
        ("clause", "(i)", "Timing"),
        ("section", "Section 102", "REPORTS AND OVERSIGHT"),
    ]
    assert sections[3].parent_label == "Part I"
    assert sections[4].parent_label == "Sec. 101A-1"
    assert sections[-1].parent_label == "Part I"
    for section in sections:
        assert (
            source[section.span.start_char : section.span.end_char] == section.span.text
        )


def test_sentence_spans_preserve_repeated_unicode_and_terminal_text():
    source = """SEC. 2. Reports
The Director’s office shall report—without delay. The Director’s office shall report—without delay.
Final report without punctuation"""
    section = parse_federal_structure(source)[0]

    sentences = sentence_spans(section, source)

    assert [sentence.text for sentence in sentences] == [
        "The Director’s office shall report—without delay.",
        "The Director’s office shall report—without delay.",
        "Final report without punctuation",
    ]
    assert sentences[0].start_char != sentences[1].start_char
    for sentence in sentences:
        assert source[sentence.start_char : sentence.end_char] == sentence.text


def test_parse_federal_structure_rejects_unstructured_text():
    with pytest.raises(ExpectedExtractionRejection) as exc_info:
        parse_federal_structure("This bill creates a program.")

    assert exc_info.value.reason == "unrecognized_federal_structure"


def test_parse_federal_structure_supports_container_heading_on_next_line():
    source = """TITLE II
HEALTH PROGRAMS
SECTION 201. DUTIES
The Secretary shall administer the program.
"""

    sections = parse_federal_structure(source)

    assert sections[0].level == "title"
    assert sections[0].label == "Title II"
    assert sections[0].heading == "HEALTH PROGRAMS"
    assert sections[1].parent_label == "Title II"
    for section in sections:
        assert (
            source[section.span.start_char : section.span.end_char] == section.span.text
        )


def test_structure_preserves_division_account_and_nested_provisions():
    sections = parse_federal_structure(FULL_HIERARCHY_SOURCE)
    clause = next(section for section in sections if section.label == "(i)")

    assert [item.level for item in clause.path] == [
        "division",
        "title",
        "subchapter",
        "account",
        "section",
        "subsection",
        "paragraph",
        "subparagraph",
        "clause",
    ]
    assert clause.source_id == f"section-{clause.span.start_char}"
    assert len({section.source_id for section in sections}) == len(sections)
    assert [item.label for item in clause.path] == [
        "Division A",
        "Title I",
        "Subchapter A",
        "Account 001",
        "Sec. 101",
        "(a)",
        "(1)",
        "(A)",
        "(i)",
    ]


def test_structure_normalizes_constitution_article_as_an_article_parent():
    source = """CONSTITUTION-ARTICLE I—LEGISLATURE
SEC. 1. POWERS
Congress shall make laws.
"""

    sections = parse_federal_structure(source)

    assert [(section.level, section.label) for section in sections] == [
        ("article", "Article I"),
        ("section", "Sec. 1"),
    ]
    assert [item.level for item in sections[-1].path] == ["article", "section"]
    assert sections[-1].parent_label == "Article I"


def test_container_heading_does_not_jump_across_a_blank_line():
    source = """TITLE II

SECTION 201. DUTIES
The Secretary shall administer the program.
"""

    sections = parse_federal_structure(source)

    assert sections[0].label == "Title II"
    assert sections[0].heading is None
    assert sections[1].label == "Section 201"


def test_container_does_not_treat_the_next_structural_marker_as_its_heading():
    source = """TITLE II
SECTION 201. DUTIES
The Secretary shall administer the program.
"""

    sections = parse_federal_structure(source)

    assert sections[0].label == "Title II"
    assert sections[0].heading is None
    assert sections[1].label == "Section 201"


def test_expected_rejection_accepts_only_approved_reasons():
    rejection = ExpectedExtractionRejection("missing_source_text")
    assert rejection.reason == "missing_source_text"

    with pytest.raises(ValueError, match="Unsupported extraction rejection reason"):
        ExpectedExtractionRejection("surprising_error")
