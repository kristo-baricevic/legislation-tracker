from dataclasses import FrozenInstanceError

import pytest

from apps.ingestion.document_download import (
    extract_document_text,
    extract_text_from_xml_or_html,
)
from apps.legislation.enhancements.xml_sections import XmlSections, xml_boundaries


def _read(raw, *, flat=False):
    text = (
        extract_text_from_xml_or_html(raw, "text/html")
        if flat
        else extract_document_text(raw, "application/xml", "bill.xml")
    )
    rows = xml_boundaries(raw, text)
    by_id = {p.identity: p for p in rows.provisions}
    return text, rows, by_id


@pytest.mark.parametrize("flat", [False, True])
def test_nested_provisions_retain_exact_parent_and_reference_scope(flat):
    raw = b"""<bill><legis-body><title id="title"><enum>I</enum>
    <text>Only public hospitals qualify under this title.</text>
    <section id="s"><enum>7.</enum><header>Grants</header>
      <subsection id="a"><enum>(a)</enum><text>The Secretary shall pay only if:</text>
        <paragraph id="one"><enum>(1)</enum><text>the hospital is public; and</text></paragraph>
        <paragraph id="two"><enum>(2)</enum><text>the hospital satisfies
          <internal-xref idref="b">subsection (b)</internal-xref>.</text></paragraph>
      </subsection>
      <subsection id="b"><enum>(b)</enum><text>At least 50 patients must be served.</text></subsection>
    </section></title></legis-body></bill>"""
    text, rows, nodes = _read(raw, flat=flat)
    assert isinstance(rows, tuple) and isinstance(rows, XmlSections)
    assert [row[0] for row in rows] == ["s"]
    for child, parent in (
        ("s", "title"),
        ("a", "s"),
        ("one", "a"),
        ("two", "a"),
        ("b", "s"),
    ):
        node = nodes[child]
        assert rows.provisions[node.parent] == nodes[parent]
        assert nodes[parent].start <= node.start < node.end <= nodes[parent].end
    assert text[nodes["one"].start : nodes["one"].end].endswith(
        "the hospital is public; and"
    )
    assert "50 patients" not in text[nodes["a"].start : nodes["a"].end]
    assert nodes["two"].references == ("b",)
    assert nodes["s"].references == nodes["a"].references == ()
    assert all(
        node.section_id == "s"
        for name, node in nodes.items()
        if name not in {"title"} and node.tag != "legis-body"
    )
    with pytest.raises(FrozenInstanceError):
        nodes["a"].end = 1


@pytest.mark.parametrize("flat", [False, True])
def test_quoted_chapter_cannot_become_parent_of_following_bill_section(flat):
    raw = b"""<bill><legis-body><title id="title"><enum>I</enum>
    <section id="change"><enum>1.</enum><text>The Other Act is amended by adding:</text>
      <quoted-block id="quote"><chapter id="quoted-chapter"><enum>601</enum>
        <section id="quoted-section"><enum>2.</enum><text>Pay $5 only to residents.</text></section>
      </chapter></quoted-block>
    </section>
    <section id="report"><enum>2.</enum><text>Publish an annual report.</text></section>
    </title></legis-body></bill>"""
    text, rows, nodes = _read(raw, flat=flat)
    assert [row[0] for row in rows] == ["change", "report"]
    assert rows.provisions[nodes["report"].parent] == nodes["title"]
    assert nodes["report"].quoted_depth == 0
    for identity in ("quote", "quoted-chapter", "quoted-section"):
        assert nodes[identity].quoted_depth == 1
        assert nodes[identity].section_id == "change"
        assert (
            "Publish an annual report"
            not in text[nodes[identity].start : nodes[identity].end]
        )
    assert rows.provisions[nodes["quoted-chapter"].parent] == nodes["quote"]
    assert rows.provisions[nodes["quoted-section"].parent] == nodes["quoted-chapter"]


def test_flat_table_rows_and_contents_have_exact_independent_ranges():
    raw = b"""<bill><engrossed-amendment-body><title id="title"><enum>I</enum><toc id="toc"><toc-entry>Sec. 1. Grants.</toc-entry></toc>
      <section id="funds"><enum>1.</enum><text>Amounts are in thousands of dollars.</text>
        <table id="table"><tgroup id="group"><thead id="head">
          <row id="heading"><entry>Program</entry><entry>Amount</entry></row>
        </thead><tbody id="body">
          <row id="first"><entry>Hospital A</entry><entry>100</entry></row>
          <row id="second"><entry>Hospital B</entry><entry>200</entry></row>
        </tbody></tgroup></table>
      </section>
    </title></engrossed-amendment-body></bill>"""
    text, rows, nodes = _read(raw)
    assert text.startswith("ISec. 1. Grants.")  # No new separator invented by markers.
    assert text[nodes["toc"].start : nodes["toc"].end] == "Sec. 1. Grants."
    assert rows.provisions[nodes["toc"].parent] == nodes["title"]
    assert rows.provisions[nodes["first"].parent] == nodes["body"]
    assert rows.provisions[nodes["heading"].parent] == nodes["head"]
    assert "Hospital B" not in text[nodes["first"].start : nodes["first"].end]
    assert "Hospital A" not in text[nodes["second"].start : nodes["second"].end]
    assert text[nodes["heading"].start : nodes["heading"].end] == "ProgramAmount"
    assert all(p.tag not in {"entry", "toc-entry"} for p in rows.provisions)


@pytest.mark.parametrize("flat", [False, True])
def test_inline_quoted_text_does_not_change_normalized_citation_text(flat):
    raw = b"""<bill><legis-body><section id="s"><enum>1.</enum>
    <text>Strike <quoted-text id="old">  may  </quoted-text> and insert
      <quoted-text id="new"> shall </quoted-text>.</text>
    </section></legis-body></bill>"""
    text, rows, nodes = _read(raw, flat=flat)
    assert "Strike may and insert" in text
    assert text[nodes["old"].start : nodes["old"].end] == "may"
    assert text[nodes["new"].start : nodes["new"].end] == "shall"
    assert rows.provisions[nodes["old"].parent] == nodes["s"]


def test_same_numbered_sections_in_separate_quotes_keep_distinct_identity():
    raw = b"""<bill><engrossed-amendment-body><section id="s"><enum>1.</enum>
      <quoted-block id="q1"><section id="one"><enum>2.</enum><text>Rule one.</text></section></quoted-block>
      <quoted-block id="q2"><section id="two"><enum>2.</enum><text>Rule two.</text></section></quoted-block>
    </section></engrossed-amendment-body></bill>"""
    _, rows, nodes = _read(raw)
    assert len(rows) == 1
    assert rows.provisions[nodes["one"].parent] == nodes["q1"]
    assert rows.provisions[nodes["two"].parent] == nodes["q2"]
    assert nodes["one"].identity != nodes["two"].identity


def test_table_category_levels_follow_cals_columns_not_uppercase_text():
    raw = b"""<bill><engrossed-amendment-body><section><enum>1.</enum><table><tgroup>
      <colspec colname="service" colnum="0" coldef="txt"/>
      <colspec colname="place" colnum="2" coldef="txt"/>
      <colspec colname="amount" colnum="4" coldef="fig"/>
      <thead><row id="header"><entry namest="service" nameend="amount">Thousands of dollars</entry></row></thead>
      <tbody>
        <row id="service"><entry namest="service" nameend="place">Army</entry><entry colname="amount"/></row>
        <row id="place"><entry colname="service"/><entry colname="place">District 7</entry><entry colname="amount"/></row>
        <row id="data"><entry colname="service">PROJECT</entry><entry colname="amount">100</entry></row>
        <row id="amount"><entry colname="service"/><entry colname="place"/><entry colname="amount">100</entry></row>
        <row id="figure-note"><entry colname="amount">Not authorized</entry></row>
      </tbody>
    </tgroup></table></section></engrossed-amendment-body></bill>"""
    _, _, nodes = _read(raw)
    assert nodes["service"].table_label_level == 0
    assert nodes["place"].table_label_level == 2
    assert all(
        nodes[name].table_label_level is None
        for name in ("header", "data", "amount", "figure-note")
    )
