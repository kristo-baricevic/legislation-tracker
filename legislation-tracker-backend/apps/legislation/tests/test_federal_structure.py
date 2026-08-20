import pytest

from apps.legislation.extraction.federal_structure import (
    parse_federal_structure,
    sentence_spans,
)
from apps.legislation.extraction.types import ExpectedExtractionRejection


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

    assert [(section.level, section.label, section.heading) for section in sections] == [
        ("title", "Title I", "GENERAL PROVISIONS"),
        ("subtitle", "Subtitle A", "Administration"),
        ("part", "Part I", "PROGRAMS"),
        ("section", "Sec. 101A-1", "Establishment"),
        ("subdivision", "(a)", "In General"),
        ("subdivision", "(1)", "Requirements"),
        ("subdivision", "(A)", "Priority"),
        ("subdivision", "(i)", "Timing"),
        ("section", "Section 102", "REPORTS AND OVERSIGHT"),
    ]
    assert sections[3].parent_label == "Part I"
    assert sections[4].parent_label == "Sec. 101A-1"
    assert sections[-1].parent_label == "Part I"
    for section in sections:
        assert source[section.span.start_char : section.span.end_char] == section.span.text


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


def test_expected_rejection_accepts_only_approved_reasons():
    rejection = ExpectedExtractionRejection("missing_source_text")
    assert rejection.reason == "missing_source_text"

    with pytest.raises(ValueError, match="Unsupported extraction rejection reason"):
        ExpectedExtractionRejection("surprising_error")
