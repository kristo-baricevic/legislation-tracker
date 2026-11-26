"""Abbreviated legal paths retain every component and their original scope."""

from types import SimpleNamespace

import pytest
from django.test import override_settings

from apps.ingestion.document_download import extract_document_text
from apps.legislation.enhancements.reader_chunking import planned_sources
from apps.legislation.enhancements.reader_citations import citation_passages
from apps.legislation.enhancements.xml_sections import xml_boundaries
from apps.legislation.tests.test_reader_scoped_dependencies import _context, _index

PUBLIC_HOSPITAL = "Applicants must be public hospitals."
MATCHING = "Applicants must provide a 50 percent non-Federal matching contribution."


def _selected_context(sources, owner):
    selected = owner["context_quote_ids"]
    return (
        owner["quoted_text"]
        + "\n"
        + "\n".join(
            passage["text"]
            for source in sources
            if source["source_ref"] in selected
            for passage in citation_passages(source)
            if passage["quote_id"] in selected[source["source_ref"]]
        )
    )


@pytest.mark.parametrize("target", [1000, 8000])
def test_large_bill_multicomponent_abbreviation_matches_expanded_reference(target):
    padding = "Additional administrative details for application review. " * 40
    reports = "".join(
        f"<paragraph><enum>({i + 1})</enum><text>The Secretary shall publish administrative "
        f"report number {i + 1} about program operations.</text></paragraph>"
        for i in range(350)
    )
    requirements = (
        "<subsection><enum>(a)</enum><paragraph><enum>(1)</enum>"
        f"<subparagraph><enum>(A)</enum><text>{PUBLIC_HOSPITAL} {padding}"
        "</text></subparagraph></paragraph><paragraph><enum>(2)</enum>"
        f"<subparagraph><enum>(B)</enum><text>{padding}{MATCHING}"
        "</text></subparagraph></paragraph></subsection><subsection><enum>(z)</enum>"
        + reports
        + "</subsection>"
    )
    expressions = [
        "section 2(a)(1)(A) and (2)(B) of this Act",
        "section 2(a)(1)(A) and section 2(a)(2)(B) of this Act",
    ]
    for expression in expressions:
        grant = (
            "The Secretary shall award grants only to applicants that satisfy "
            + expression
            + "."
        )
        raw = (
            '<bill><engrossed-amendment-body><section id="grant"><enum>1.</enum><text>'
            + grant
            + "</text></section><section><enum>2.</enum><header>Requirements</header>"
            + requirements
            + "</section></engrossed-amendment-body></bill>"
        ).encode()
        text = extract_document_text(raw, "application/xml", "bill.xml")
        assert len(text) > 37_000
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
        context = _selected_context(sources, owner)
        assert PUBLIC_HOSPITAL in context, expression
        assert MATCHING in context, expression
        assert "report number 350" not in context
        assert not owner["unresolved_dependencies"], expression
        assert "".join(source["quoted_text"] for source in sources) == text


def _requirements(prefix=""):
    return f"""
      <section><enum>2.</enum><subsection><enum>(a)</enum>
        <paragraph><enum>(1)</enum>
          <subparagraph><enum>(A)</enum><text>{prefix} FIRST CONDITION.</text>
            <clause><enum>(i)</enum><text>{prefix} FIRST CLAUSE CONDITION.</text></clause>
          </subparagraph>
          <subparagraph><enum>(B)</enum><text>{prefix} WRONG FIRST PARAGRAPH.</text></subparagraph>
        </paragraph>
        <paragraph><enum>(2)</enum>
          <subparagraph><enum>(A)</enum><text>{prefix} RANGE FIRST.</text></subparagraph>
          <subparagraph><enum>(B)</enum><text>{prefix} MATCHING CONDITION.</text></subparagraph>
          <subparagraph><enum>(C)</enum><text>{prefix} RANGE LAST.</text></subparagraph>
        </paragraph>
      </subsection><subsection><enum>(b)</enum>
        <paragraph><enum>(1)</enum><text>{prefix} WRONG SECOND SUBSECTION.</text></paragraph>
        <paragraph><enum>(2)</enum><text>{prefix} REQUIRED SECOND SUBSECTION.</text>
          <subparagraph><enum>(B)</enum><text>{prefix} DEEP SECOND SUBSECTION.</text></subparagraph>
        </paragraph>
      </subsection></section>"""


@pytest.mark.parametrize(
    "reference, expected, excluded",
    [
        (
            "section 2(a)(1)(A) and (2)(B)",
            ["FIRST CONDITION", "MATCHING CONDITION"],
            ["WRONG FIRST PARAGRAPH", "RANGE FIRST", "RANGE LAST"],
        ),
        (
            "sections 2(a)(1)(A), (2)(A) through (2)(C)",
            ["FIRST CONDITION", "RANGE FIRST", "MATCHING CONDITION", "RANGE LAST"],
            ["WRONG FIRST PARAGRAPH", "REQUIRED SECOND SUBSECTION"],
        ),
        (
            "sections 2(a)(1)(A) and (b)(2)",
            ["FIRST CONDITION", "REQUIRED SECOND SUBSECTION"],
            ["WRONG FIRST PARAGRAPH", "WRONG SECOND SUBSECTION", "MATCHING CONDITION"],
        ),
        (
            "sections 2(a)(1)(A), (2)(B), and (b)(2)",
            ["FIRST CONDITION", "MATCHING CONDITION", "REQUIRED SECOND SUBSECTION"],
            ["WRONG FIRST PARAGRAPH", "WRONG SECOND SUBSECTION"],
        ),
    ],
)
def test_multicomponent_lists_ranges_and_subsection_changes_keep_the_legal_path(
    reference, expected, excluded
):
    index = _index(
        f'<section id="grant"><enum>1.</enum><text>Apply {reference} of this Act.</text></section>'
        + _requirements()
    )
    context, unresolved = _context(index, "grant")
    assert all(condition in context for condition in expected)
    assert all(condition not in context for condition in excluded)
    assert not unresolved


def test_multicomponent_reference_retains_external_law_qualification():
    index = _index(
        '<section id="grant"><enum>1.</enum><text>Apply section 2(a)(1)(A) and (2)(B) of the Other Act.</text></section>'
        + _requirements("WRONG LOCAL")
    )
    context, unresolved = _context(index, "grant")
    assert "WRONG LOCAL" not in context
    assert unresolved


@pytest.mark.parametrize("first", ["2(a)", "2(a)(1)"])
def test_abbreviated_continuation_can_descend_deeper_than_previous_member(first):
    index = _index(
        f'<section id="grant"><enum>1.</enum><text>Apply section {first} and (b)(2)(B) of this Act.</text></section>'
        + _requirements()
    )
    context, unresolved = _context(index, "grant")
    assert "FIRST CONDITION" in context
    assert "DEEP SECOND SUBSECTION" in context
    assert "WRONG SECOND SUBSECTION" not in context
    assert not unresolved


def test_full_subsection_suffix_takes_priority_over_partial_clause_overlap():
    index = _index(
        '<section id="grant"><enum>1.</enum><text>Apply section 2(a)(1)(A)(i) and (b)(2)(B) of this Act.</text></section>'
        + _requirements()
    )
    context, unresolved = _context(index, "grant")
    assert "FIRST CLAUSE CONDITION" in context
    assert "DEEP SECOND SUBSECTION" in context
    assert "WRONG SECOND SUBSECTION" not in context
    assert not unresolved


def test_item_subitem_suffix_does_not_rebind_to_roman_clause_levels():
    requirements = """
      <section><enum>2.</enum><subsection><enum>(a)</enum>
        <paragraph><enum>(1)</enum><subparagraph><enum>(A)</enum>
          <clause><enum>(i)</enum><subclause><enum>(I)</enum>
            <item><enum>(aa)</enum><text>FIRST ITEM REQUIREMENT.</text></item>
            <item><enum>(bb)</enum><subitem><enum>(BB)</enum>
              <text>DEEP SECOND ITEM REQUIREMENT.</text>
            </subitem></item>
          </subclause></clause>
        </subparagraph></paragraph>
      </subsection></section>"""
    for continuation in ["section 2(a)(1)(A)(i)(I)(bb)(BB)", "(bb)(BB)"]:
        index = _index(
            '<section id="grant"><enum>1.</enum><text>Apply section '
            f"2(a)(1)(A)(i)(I)(aa) and {continuation} of this Act.</text></section>"
            + requirements
        )
        context, unresolved = _context(index, "grant")
        assert "FIRST ITEM REQUIREMENT" in context, continuation
        assert "DEEP SECOND ITEM REQUIREMENT" in context, continuation
        assert not unresolved, continuation


def test_multicomponent_reference_stays_in_its_quoted_law():
    index = _index(
        _requirements("WRONG OUTER")
        + "<section><enum>3.</enum><quoted-block>"
        + '<section id="grant"><enum>1.</enum><text>Apply section 2(a)(1)(A) and (2)(B).</text></section>'
        + _requirements("CORRECT QUOTED")
        + "</quoted-block><quoted-block>"
        + _requirements("WRONG QUOTED")
        + "</quoted-block></section>"
    )
    context, unresolved = _context(index, "grant")
    assert "CORRECT QUOTED FIRST CONDITION" in context
    assert "CORRECT QUOTED MATCHING CONDITION" in context
    assert "WRONG OUTER" not in context
    assert "WRONG QUOTED" not in context
    assert not unresolved


def test_missing_multicomponent_member_remains_unresolved_without_borrowing():
    index = _index(
        '<section id="grant"><enum>1.</enum><text>Apply section 2(a)(1)(A) and (z)(2) of this Act.</text></section>'
        + _requirements()
    )
    context, unresolved = _context(index, "grant")
    assert "FIRST CONDITION" in context
    assert "REQUIRED SECOND SUBSECTION" not in context
    assert "MATCHING CONDITION" not in context
    assert unresolved


@pytest.mark.parametrize(
    "continuation,marker",
    [
        ("(b)", "SUBSECTION"),
        ("(2)", "PARAGRAPH"),
        ("(B)", "SUBPARAGRAPH"),
        ("(iv)", "CLAUSE"),
        ("(IV)", "SUBCLAUSE"),
        ("(bb)", "ITEM"),
        ("(BB)", "SUBITEM"),
        ("(iv)(IV)", "DEEP"),
    ],
)
def test_shorthand_can_ascend_from_each_numbering_family(continuation, marker):
    index = _index(
        f"""
      <section id="grant"><enum>1.</enum><text>Apply section 2(a)(1)(A)(i)(I)(aa)(AA) and {continuation} of this Act.</text></section>
      <section><enum>2.</enum><subsection><enum>(a)</enum><paragraph><enum>(1)</enum><subparagraph><enum>(A)</enum>
      <clause><enum>(i)</enum><subclause><enum>(I)</enum><item><enum>(aa)</enum>
      <subitem><enum>(AA)</enum><text>Primary condition.</text></subitem>
      <subitem><enum>(BB)</enum><text>Required SUBITEM.</text></subitem></item>
      <item><enum>(bb)</enum><text>Required ITEM.</text></item></subclause>
      <subclause><enum>(IV)</enum><text>Required SUBCLAUSE.</text></subclause></clause>
      <clause><enum>(iv)</enum><text>Required CLAUSE.</text>
      <subclause><enum>(IV)</enum><text>Required DEEP.</text></subclause></clause></subparagraph>
      <subparagraph><enum>(B)</enum><text>Required SUBPARAGRAPH.</text></subparagraph></paragraph>
      <paragraph><enum>(2)</enum><text>Required PARAGRAPH.</text></paragraph></subsection>
      <subsection><enum>(b)</enum><text>Required SUBSECTION.</text></subsection></section>"""
    )
    context, unresolved = _context(index, "grant")
    assert not unresolved
    assert "Primary condition." in context
    assert f"Required {marker}." in context


def test_repeated_kind_starts_a_new_path_in_the_same_explicit_scope():
    index = _index(
        """
      <section><enum>2.</enum><subsection id="grant"><enum>(z)</enum>
      <text>Apply subsection (a)(1)(A)(i) and subsection (i) of this section.</text></subsection>
      <subsection><enum>(a)</enum><paragraph><enum>(1)</enum><subparagraph><enum>(A)</enum>
      <clause><enum>(i)</enum><text>Applicants must be public hospitals.</text></clause>
      </subparagraph></paragraph></subsection>
      <subsection><enum>(i)</enum><text>Applicants must provide a 50 percent match.</text></subsection></section>"""
    )
    context, unresolved = _context(index, "grant")
    assert not unresolved
    assert "public hospitals" in context and "50 percent match" in context


@pytest.mark.parametrize("qualification", ["", " of this item", " of the Other Act"])
def test_subitem_qualifiers_respect_the_enclosing_item(qualification):
    index = _index(f"""
      <section><enum>2.</enum><item><enum>(aa)</enum>
      <subitem id="grant"><enum>(CC)</enum><text>Apply subitems (AA) and (BB){qualification}.</text></subitem>
      <subitem><enum>(AA)</enum><text>Applicants must be public hospitals.</text></subitem>
      <subitem><enum>(BB)</enum><text>Applicants must provide a 50 percent match.</text></subitem>
      </item></section>""")
    context, unresolved = _context(index, "grant")
    local = qualification != " of the Other Act"
    assert ("50 percent match" in context) == local
    assert bool(unresolved) != local


def test_large_section_supplies_both_explicit_subsections_at_default_ownership():
    grant = "The Secretary shall award grants only to applicants that satisfy subsection (a)(1)(A)(i) and subsection (i) of this section."
    unrelated = "".join(
        f"<paragraph><enum>({i})</enum><text>The Secretary shall publish administrative report number {i} about program operations.</text></paragraph>"
        for i in range(1, 401)
    )
    raw = f"""<bill><legis-body><section><enum>2.</enum>
      <subsection><enum>(a)</enum><paragraph><enum>(1)</enum><subparagraph><enum>(A)</enum>
      <clause><enum>(i)</enum><text>{PUBLIC_HOSPITAL}</text></clause>
      </subparagraph></paragraph></subsection>
      <subsection><enum>(d)</enum>{unrelated}</subsection>
      <subsection><enum>(i)</enum><text>{MATCHING}</text></subsection>
      <subsection><enum>(z)</enum><text>{grant}</text></subsection>
      </section></legis-body></bill>""".encode()
    text = extract_document_text(raw, "application/xml", "bill.xml")
    assert len(text) > 35000
    with override_settings(
        LLM_ENHANCEMENT_PROVIDER="openai",
        LLM_ENHANCEMENT_MODEL="gpt-5.6-luna",
        LLM_ENHANCEMENT_REASONING_EFFORT="none",
    ):
        sources = planned_sources(
            SimpleNamespace(version_label="Test"),
            text,
            1,
            8000,
            xml_boundaries(raw, text),
        )
    owner = next(source for source in sources if grant in source["quoted_text"])
    context = _selected_context(sources, owner)
    assert PUBLIC_HOSPITAL in context and MATCHING in context
    assert not owner["unresolved_dependencies"]
