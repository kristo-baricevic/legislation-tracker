"""Reference groups preserve every condition and uncertain scope stays explicit."""

from types import SimpleNamespace

import pytest
from django.test import override_settings

from apps.ingestion.document_download import extract_document_text
from apps.legislation.enhancements.reader_chunking import planned_sources
from apps.legislation.enhancements.reader_citations import citation_passages
from apps.legislation.enhancements.xml_sections import xml_boundaries
from apps.legislation.tests.test_reader_scoped_dependencies import _context, _index


@pytest.mark.parametrize("target", [1000, 8000])
@pytest.mark.parametrize(
    "reference", ["subsections (a) through (c)", "subsections (a) through (c), and (e)"]
)
def test_large_section_supplies_every_citable_condition_in_a_reference_group(
    target, reference
):
    conditions = {
        "a": "Applicants must be public hospitals.",
        "b": "Applicants must provide emergency services.",
        "c": "Applicants must provide a 50 percent non-Federal matching contribution.",
        "e": "Applicants must hold a current hospital license.",
    }

    def requirement(letter):
        return (
            f'<subsection id="{letter}"><enum>({letter})</enum><header>Requirement {letter}</header>'
            f"<text>{conditions[letter]} "
            + "Additional administrative details for application review. " * 25
            + "</text></subsection>"
        )

    reports = "".join(
        f"<paragraph><enum>({i + 1})</enum><text>The Secretary shall publish administrative "
        f"report number {i + 1} about program operations.</text></paragraph>"
        for i in range(350)
    )
    grant = f"The Secretary shall award a grant only to applicants that meet the requirements in {reference}."
    raw = (
        '<bill><engrossed-amendment-body><section id="s"><enum>1.</enum><header>Hospital grants</header>'
        + "".join(requirement(letter) for letter in "abc")
        + "<subsection><enum>(d)</enum>"
        + reports
        + "</subsection>"
        + requirement("e")
        + '<subsection id="grant"><enum>(f)</enum><text>'
        + grant
        + "</text></subsection></section></engrossed-amendment-body></bill>"
    ).encode()
    text = extract_document_text(raw, "application/xml", "bill.xml")
    with override_settings(
        LLM_ENHANCEMENT_PROVIDER="openai",
        LLM_ENHANCEMENT_MODEL="gpt-5.6-luna",
        LLM_ENHANCEMENT_REASONING_EFFORT="none",
    ):
        sources = planned_sources(
            SimpleNamespace(version_label="Test"),
            text,
            1,
            target,
            xml_boundaries(raw, text),
        )
    owner = next(source for source in sources if grant in source["quoted_text"])
    allowed = owner["context_quote_ids"]
    context = (
        owner["quoted_text"]
        + "\n"
        + "\n".join(
            passage["text"]
            for source in sources
            if source["source_ref"] in allowed
            for passage in citation_passages(source)
            if passage["quote_id"] in allowed[source["source_ref"]]
        )
    )
    for letter in "abce" if "and (e)" in reference else "abc":
        assert conditions[letter] in context
    assert "report number 350" not in context
    assert not owner["unresolved_dependencies"]
    assert "".join(source["quoted_text"] for source in sources) == text


@pytest.mark.parametrize(
    "reference",
    [
        "subsections (a) through (c), and (e)",
        "subsections (a) to (c) or (e)",
        "subsections (a)–(c), (e)",
        "subsections (a)-(c) and (e)",
        "subsections (a) through subsection (c), and (e)",
        "subsections (a) through (c), inclusive, and (e)",
        "subsections (a) through (c) (inclusive), and (e)",
        "subsections (a), (b), (c), and (e)",
    ],
)
def test_mixed_lists_ranges_and_inclusive_modifiers_keep_all_members(reference):
    requirements = "".join(
        f"<subsection><enum>({letter})</enum><text>CONDITION {letter}.</text></subsection>"
        for letter in "abcdef"
    )
    index = _index(
        f'<section><enum>1.</enum>{requirements}<subsection id="grant"><enum>(g)</enum>'
        f"<text>Apply {reference} of this section.</text></subsection></section>"
    )
    context, unresolved = _context(index, "grant")
    assert all(f"CONDITION {letter}." in context for letter in "abce")
    assert all(f"CONDITION {letter}." not in context for letter in "df")
    assert not unresolved


@pytest.mark.parametrize(
    "kind, parent, labels",
    [
        ("paragraph", "subsection", ["1", "2", "3"]),
        ("subparagraph", "paragraph", ["A", "B", "C"]),
        ("clause", "subparagraph", ["i", "ii", "iii", "iv"]),
        ("subclause", "clause", ["I", "II", "III", "IV"]),
        ("item", "subclause", ["aa", "bb", "cc"]),
    ],
)
def test_relative_ranges_follow_the_provision_numbering_family(kind, parent, labels):
    requirements = "".join(
        f"<{kind}><enum>({label})</enum><text>CONDITION {label}.</text></{kind}>"
        for label in labels
    )
    index = _index(
        f"<section><enum>1.</enum><{parent}><enum>(z)</enum>{requirements}"
        f'<{kind} id="grant"><enum>(zz)</enum><text>Apply {kind}s '
        f"({labels[0]}) through ({labels[-1]}).</text></{kind}></{parent}></section>"
    )
    context, unresolved = _context(index, "grant")
    assert all(f"CONDITION {label}." in context for label in labels)
    assert not unresolved


@pytest.mark.parametrize("expression", ["2 through 4", "2–4", "2-4", "2 to 4"])
def test_section_ranges_include_intervening_sections_and_inserted_labels(expression):
    sections = "".join(
        f"<section><enum>{label}.</enum><text>CONDITION {label}.</text></section>"
        for label in ["2", "2A", "3", "4", "5"]
    )
    index = _index(
        f'<section id="grant"><enum>1.</enum><text>Apply sections {expression} of this Act.</text></section>{sections}'
    )
    context, unresolved = _context(index, "grant")
    assert all(f"CONDITION {label}." in context for label in ["2", "2A", "3", "4"])
    assert "CONDITION 5." not in context
    assert not unresolved


@pytest.mark.parametrize("plural", [False, True])
def test_compact_hyphen_keeps_existing_literal_section_and_ambiguity(plural):
    reference = "sections 2-4 and 2-5" if plural else "section 2-4"
    index = _index(f"""
      <section id="grant"><enum>1.</enum><text>Apply {reference} of this Act.</text></section>
      <section><enum>2-4.</enum><text>FIRST HYPHENATED CONDITION.</text></section>
      <section><enum>2-5.</enum><text>SECOND HYPHENATED CONDITION.</text></section>
      <section><enum>2.</enum><text>RANGE TWO.</text></section>
      <section><enum>3.</enum><text>RANGE THREE.</text></section>
      <section><enum>4.</enum><text>RANGE FOUR.</text></section>
      <section><enum>5.</enum><text>RANGE FIVE.</text></section>""")
    context, unresolved = _context(index, "grant")
    assert "FIRST HYPHENATED CONDITION" in context
    if plural:
        assert "SECOND HYPHENATED CONDITION" in context
        assert "RANGE THREE" in context
        assert unresolved
    else:
        assert "RANGE THREE" not in context
        assert not unresolved


def test_shortened_nested_range_and_new_subsection_keep_their_legal_levels():
    index = _index(
        """
      <section id="grant"><enum>1.</enum><text>Apply sections 2(a)(1)(A) through (C), and (b) of this Act.</text></section>
      <section><enum>2.</enum><subsection><enum>(a)</enum><paragraph><enum>(1)</enum>
        <subparagraph><enum>(A)</enum><text>FIRST CONDITION.</text></subparagraph>
        <subparagraph><enum>(B)</enum><text>SECOND CONDITION.</text></subparagraph>
        <subparagraph><enum>(C)</enum><text>THIRD CONDITION.</text></subparagraph>
      </paragraph></subsection><subsection><enum>(b)</enum><text>REQUIRED SUBSECTION CONDITION.</text></subsection></section>"""
    )
    context, unresolved = _context(index, "grant")
    assert all(
        value in context
        for value in [
            "FIRST CONDITION",
            "SECOND CONDITION",
            "THIRD CONDITION",
            "REQUIRED SUBSECTION CONDITION",
        ]
    )
    assert not unresolved


def test_shortened_lowercase_subsection_never_rebinds_to_uppercase_subparagraph():
    index = _index(
        """
      <section id="grant"><enum>1.</enum><text>Apply sections 2(a)(1)(A) and (b) of this Act.</text></section>
      <section><enum>2.</enum><subsection><enum>(a)</enum><paragraph><enum>(1)</enum>
        <subparagraph><enum>(A)</enum><text>FIRST CONDITION.</text></subparagraph>
        <subparagraph><enum>(B)</enum><text>WRONG CHILD CONDITION.</text></subparagraph>
      </paragraph></subsection><subsection><enum>(b)</enum><text>REQUIRED SUBSECTION CONDITION.</text></subsection></section>"""
    )
    context, unresolved = _context(index, "grant")
    assert "FIRST CONDITION" in context
    assert "REQUIRED SUBSECTION CONDITION" in context
    assert "WRONG CHILD CONDITION" not in context
    assert not unresolved


@pytest.mark.parametrize(
    "labels, reference",
    [
        (["a", "c"], "subsections (a) through (c)"),
        (["a", "b"], "subsections (a) through (c)"),
        (["b", "c"], "subsections (a) through (c)"),
        (["a", "b", "b", "c"], "subsections (a) through (c)"),
        (["a", "b", "c"], "subsections (c) through (a)"),
        (["a", "b", "c"], "subsections (a) thru (c)"),
        (["a", "b", "c"], "subsections (a) et seq."),
        (["a", "b", "c"], "subsections (a) through"),
    ],
)
def test_incomplete_or_ambiguous_range_always_retains_an_obligation(labels, reference):
    requirements = "".join(
        f"<subsection><enum>({label})</enum><text>CONDITION {label}.</text></subsection>"
        for label in labels
    )
    index = _index(
        f'<section><enum>1.</enum>{requirements}<subsection id="grant"><enum>(g)</enum><text>Apply {reference}.</text></subsection></section>'
    )
    _, unresolved = _context(index, "grant")
    assert unresolved
    assert any("subsections" in value for value in unresolved)


def test_missing_range_member_cannot_be_borrowed_from_another_section():
    index = _index(
        """
      <section><enum>1.</enum>
        <subsection><enum>(a)</enum><text>LOCAL FIRST.</text></subsection>
        <subsection><enum>(c)</enum><text>LOCAL LAST.</text></subsection>
        <subsection id="grant"><enum>(d)</enum><text>Apply subsections (a) through (c).</text></subsection>
      </section><section><enum>2.</enum><subsection><enum>(b)</enum><text>WRONG SECTION CONDITION.</text></subsection></section>"""
    )
    context, unresolved = _context(index, "grant")
    assert "WRONG SECTION CONDITION" not in context
    assert unresolved


@pytest.mark.parametrize(
    "modifier", ["", ", inclusive,", " (inclusive)", " (as amended)"]
)
def test_external_qualification_is_shared_by_every_range_member(modifier):
    sections = "".join(
        f"<section><enum>{number}.</enum><text>WRONG LOCAL {number}.</text></section>"
        for number in range(2, 5)
    )
    index = _index(
        f'<section id="grant"><enum>1.</enum><text>Apply sections 2 through 4{modifier} of the Other Act.</text></section>{sections}'
    )
    context, unresolved = _context(index, "grant")
    assert "WRONG LOCAL" not in context
    assert unresolved


def test_explicit_this_section_qualifier_does_not_select_same_named_subsection_children():
    def requirements(prefix):
        return "".join(
            f"<paragraph><enum>({number})</enum><text>{prefix} {number}.</text></paragraph>"
            for number in range(1, 4)
        )

    index = _index(
        "<section><enum>1.</enum>"
        + requirements("SECTION CONDITION")
        + "<subsection><enum>(a)</enum>"
        + requirements("WRONG SUBSECTION CONDITION")
        + '<paragraph id="grant"><enum>(4)</enum><text>Apply paragraphs (1) through (3) of this section.</text></paragraph></subsection></section>'
    )
    context, unresolved = _context(index, "grant")
    assert all(f"SECTION CONDITION {number}." in context for number in range(1, 4))
    assert "WRONG SUBSECTION CONDITION" not in context
    assert not unresolved


def test_quoted_range_members_do_not_cross_between_repeated_section_scopes():
    def requirements(prefix):
        return "".join(
            f"<subsection><enum>({letter})</enum><text>{prefix} {letter}.</text></subsection>"
            for letter in "abc"
        )

    index = _index(
        "<section><enum>1.</enum>"
        + requirements("OUTER CONDITION")
        + "<quoted-block><section><enum>2.</enum>"
        + requirements("RIGHT QUOTED CONDITION")
        + '<subsection id="grant"><enum>(d)</enum><text>Apply subsections (a) through (c).</text></subsection></section></quoted-block>'
        + "<quoted-block><section><enum>2.</enum>"
        + requirements("WRONG QUOTED CONDITION")
        + "</section></quoted-block></section>"
    )
    context, unresolved = _context(index, "grant")
    assert all(f"RIGHT QUOTED CONDITION {letter}." in context for letter in "abc")
    assert "WRONG QUOTED CONDITION" not in context
    assert "OUTER CONDITION" not in context
    assert not unresolved
