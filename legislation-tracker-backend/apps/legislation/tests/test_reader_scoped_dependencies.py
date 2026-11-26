"""Meaning-changing context must survive narrowing an oversized legal unit."""

import pytest

from apps.ingestion.document_download import extract_document_text
from apps.legislation.enhancements.reader_dependencies import DependencyIndex
from apps.legislation.enhancements.xml_sections import xml_boundaries


def _index(body):
    raw = f"<bill><engrossed-amendment-body>{body}</engrossed-amendment-body></bill>".encode()
    text = extract_document_text(raw, "application/xml", "bill.xml")
    return DependencyIndex(text, xml_boundaries(raw, text))


def _context(index, identity):
    number = next(i for i, node in enumerate(index.nodes) if node.identity == identity)
    node = index.nodes[number]
    ranges, unresolved = index.required(node.start, node.end, number)
    return "\n".join(index.text[a:b] for a, b in ranges), unresolved


def test_definition_inherits_its_parent_title_scope():
    index = _index("""
      <title><enum>I</enum>
        <section id="defs"><enum>1.</enum><header>Terms</header>
          <subsection><enum>(a)</enum><header>Definitions</header>
            <text>In this title:</text>
            <paragraph><enum>(1)</enum><text>The term eligible hospital means
              a public hospital that serves veterans.</text></paragraph>
          </subsection>
        </section>
        <section id="pay"><enum>2.</enum><text>The Secretary shall pay each
          eligible hospital $100.</text></section>
      </title>
      <title><enum>II</enum>
        <section id="unrelated"><enum>3.</enum><text>The Secretary shall pay
          each eligible hospital $200.</text></section>
      </title>""")
    relevant, _ = _context(index, "pay")
    unrelated, _ = _context(index, "unrelated")
    assert "public hospital that serves veterans" in relevant
    assert "public hospital that serves veterans" not in unrelated


def test_referenced_subsection_keeps_its_own_sections_qualification():
    index = _index("""
      <section id="pay"><enum>1.</enum><text>Subject to section 2(a) of this Act,
        pay $100.</text></section>
      <section><enum>2.</enum>
        <subsection id="a"><enum>(a)</enum><text>Public hospitals qualify.</text></subsection>
        <subsection id="b"><enum>(b)</enum><text>No funds under this section may
          be used for lobbying.</text></subsection>
      </section>""")
    context, _ = _context(index, "pay")
    assert "Public hospitals qualify" in context
    assert "be used for lobbying" in context


def test_plural_section_references_keep_every_qualifying_section():
    index = _index("""
      <section id="pay"><enum>1.</enum><text>Subject to sections 2 and 3 of this Act,
        pay $100.</text></section>
      <section><enum>2.</enum><text>Only residents qualify.</text></section>
      <section><enum>3.</enum><text>Applicants must be enrolled.</text></section>""")
    context, unresolved = _context(index, "pay")
    assert "Only residents qualify" in context
    assert "Applicants must be enrolled" in context
    assert not unresolved


def test_table_row_keeps_column_units_and_current_category_heading():
    index = _index("""
      <section><enum>1.</enum>
        <table><tgroup>
          <thead><row><entry>Program</entry><entry>Thousands of dollars</entry></row></thead>
          <tbody>
            <row id="category"><entry>Hospital construction</entry><entry></entry></row>
            <row id="row"><entry>Veterans hospital</entry><entry>100</entry></row>
            <row id="next-category"><entry>Road construction</entry><entry></entry></row>
            <row id="unrelated"><entry>Interstate bridge</entry><entry>200</entry></row>
          </tbody>
        </tgroup></table>
      </section>""")
    context, _ = _context(index, "row")
    assert "Veterans hospital" in context
    assert "Thousands of dollars" in context
    assert "Hospital construction" in context
    assert "Road construction" not in context
    assert "Interstate bridge" not in context


def test_quoted_chapter_never_governs_the_next_bill_section():
    index = _index("""
      <title><enum>I</enum>
        <section id="change"><enum>1.</enum><text>The Other Act is amended by adding:</text>
          <quoted-block><chapter><enum>601</enum>
            <text>Only AMENDED PERSONS qualify under this chapter.</text>
            <section><enum>2.</enum><text>Pay $5.</text></section>
          </chapter></quoted-block>
        </section>
        <section id="report"><enum>2.</enum><text>Publish an annual report.</text></section>
      </title>""")
    context, _ = _context(index, "report")
    assert "Publish an annual report" in context
    assert "AMENDED PERSONS" not in context
    assert "Pay $5" not in context


def test_enactment_date_does_not_make_a_local_sunset_global():
    index = _index("""
      <section id="pay"><enum>1.</enum><text>Pay veterans $100.</text></section>
      <section id="pilot"><enum>2.</enum>
        <subsection id="authority"><enum>(a)</enum><text>The Secretary may
          establish the UNRELATED PILOT program.</text></subsection>
        <subsection><enum>(b)</enum><text>The authority under subsection (a) shall
          terminate five years after the date of enactment of this Act.</text></subsection>
      </section>""")
    context, _ = _context(index, "pay")
    assert "Pay veterans $100" in context
    assert "UNRELATED PILOT" not in context
    assert "terminate five years" not in context


def test_text_section_heading_does_not_reinsert_its_entire_large_section():
    text = "SECTION 1. REPORTS\n" + "\n".join(
        f"({i}) The Secretary shall publish report number {i} for all public hospitals."
        for i in range(1, 600)
    )
    index = DependencyIndex(text, ())
    owner = next(
        owner
        for owner in index.ownership_units()
        if "report number 1 " in text[owner[0] : owner[1]]
    )
    ranges, unresolved = index.required(*owner)
    context = "\n".join(text[a:b] for a, b in ranges)
    assert "report number 1 " in context
    assert "report number 599 " not in context
    assert not unresolved


def test_external_decimal_section_is_not_rebound_to_bill_section_two():
    index = _index(
        """
      <section id="pay"><enum>1.</enum><text>The term contract has the meaning
        given in section 2.101 of the Federal Acquisition Regulation.</text></section>
      <section id="contents"><enum>2.</enum><text>UNRELATED BILL CONTENTS.</text></section>"""
    )
    context, unresolved = _context(index, "pay")
    assert "UNRELATED BILL CONTENTS" not in context
    assert unresolved


def test_external_amendment_subsection_reference_is_not_current_bill_scope():
    index = _index("""
      <section><enum>1.</enum>
        <subsection id="a"><enum>(a)</enum><text>UNRELATED NEW BILL PROGRAM.</text></subsection>
        <subsection><enum>(b)</enum><text>Section 10 of the Other Act is amended:</text>
          <paragraph id="change"><enum>(1)</enum><text>in subsection (a), by
            striking hospital and inserting clinic.</text></paragraph>
        </subsection>
      </section>""")
    context, unresolved = _context(index, "change")
    assert "striking hospital" in context
    assert "UNRELATED NEW BILL PROGRAM" not in context
    assert unresolved


def test_specific_amendments_effective_date_is_not_an_act_wide_condition():
    index = _index("""
      <section id="pay"><enum>1.</enum><text>Pay veterans $100.</text></section>
      <section><enum>2.</enum>
        <subsection><enum>(a)</enum><text>UNRELATED CONFORMING CHANGES.</text></subsection>
        <subsection><enum>(b)</enum><text>The amendments made by section 3 of this Act
          shall take effect immediately after the amendments made by subsection (a).</text></subsection>
      </section>
      <section><enum>3.</enum><text>OTHER UNRELATED CHANGES.</text></section>""")
    context, _ = _context(index, "pay")
    assert "UNRELATED CONFORMING CHANGES" not in context
    assert "OTHER UNRELATED CHANGES" not in context
    assert "shall take effect" not in context


def test_reference_to_this_act_does_not_widen_a_local_definition():
    index = _index(
        """
      <section><enum>1.</enum>
        <subsection><enum>(a)</enum><text>For purposes of this subsection:</text>
          <paragraph><enum>(1)</enum><text>The term eligible person means a
            PRIVATE DISTRICT resident described in section 3 of this Act.</text></paragraph>
        </subsection>
      </section>
      <section id="pay"><enum>2.</enum><text>Pay each eligible person $100.</text></section>
      <section><enum>3.</enum><text>The private district is the eastern district.</text></section>"""
    )
    context, _ = _context(index, "pay")
    assert "PRIVATE DISTRICT" not in context
    assert "eastern district" not in context


def test_repeal_list_keeps_the_inherited_external_statute_scope():
    index = _index(
        """
      <section id="repeal"><enum>1.</enum><header>Repeals</header>
        <subsection><enum>(a)</enum><text>The following provisions are hereby repealed:</text>
          <paragraph><enum>(1)</enum><text>Of the Other Authorization Act
            (Public Law 107-314):</text>
            <subparagraph><enum>(A)</enum><text>section 804 (10 U.S.C. 4571 note).</text></subparagraph>
          </paragraph>
        </subsection>
      </section>
      <section><enum>804.</enum><text>UNRELATED CURRENT BILL CONTRACTS.</text></section>"""
    )
    context, unresolved = _context(index, "repeal")
    assert "Other Authorization Act" in context
    assert "UNRELATED CURRENT BILL CONTRACTS" not in context
    assert unresolved


def test_funding_table_rows_inherit_the_authorization_and_fiscal_year():
    rows = "".join(
        f'<row id="funding-{i}"><entry>Program {i} for acquisition and development '
        f"of hospital equipment across the district</entry><entry>{i + 100}</entry></row>"
        for i in range(400)
    )
    index = _index(f"""
      <section id="authorization"><enum>201.</enum><header>Authorization of appropriations</header>
        <text>Funds are hereby authorized to be appropriated for fiscal year 2026
          for research and development, as specified in the funding table in section 4201.</text>
      </section>
      <section id="funding"><enum>4201.</enum><header>Research and development</header>
        <table id="table"><tgroup><thead>
          <row><entry>Program</entry><entry>Amounts in thousands of dollars</entry></row>
        </thead><tbody>{rows}</tbody></tgroup></table>
      </section>""")
    table = next(node for node in index.nodes if node.identity == "table")
    assert table.end - table.start > 30_000

    authorization, _ = _context(index, "authorization")
    row, _ = _context(index, "funding-120")
    assert "4201." in authorization
    assert "Research and development" in authorization
    assert "Amounts in thousands of dollars" in authorization
    assert "Program 399 for acquisition" not in authorization
    assert "Funds are hereby authorized to be appropriated" in row
    assert "fiscal year 2026" in row
    assert "Amounts in thousands of dollars" in row
    assert "Program 120 for acquisition" in row
    assert "Program 399 for acquisition" not in row

    # Table rows remain independently owned, including the rows omitted from
    # the author's operation-level request. Narrowing does not remove coverage.
    owned = "".join(index.text[a:b] for a, b, _ in index.ownership_units())
    assert owned == index.text
    assert "Program 399 for acquisition" in owned


def test_amendment_operation_reference_preserves_identity_without_all_new_law():
    inserted = "".join(
        f"<section><enum>{6100 + i}.</enum><header>Program {i}</header>"
        f"<text>NEW CODE PROVISION {i}: "
        + "The agency shall publish a report. " * 30
        + "</text></section>"
        for i in range(60)
    )
    index = _index(f"""
      <section><enum>3111.</enum><header>Recodification</header>
        <subsection id="amendment"><enum>(a)</enum><header>Insertion</header>
          <text>Title 10, United States Code, is amended by adding at the end
            the following new chapter:</text>
          <quoted-block><chapter><enum>601</enum><header>New programs</header>
            {inserted}
          </chapter></quoted-block>
        </subsection>
        <subsection id="savings"><enum>(b)</enum><header>Savings provision</header>
          <text>Each order under a law amended by subsection (a) remains in effect
            until modified or revoked in accordance with applicable law.</text>
        </subsection>
      </section>""")
    amendment = next(node for node in index.nodes if node.identity == "amendment")
    assert amendment.end - amendment.start > 30_000
    savings, _ = _context(index, "savings")
    assert "Title 10, United States Code, is amended by adding at the end" in savings
    assert "the following new chapter" in savings
    assert (
        "Each order under a law amended by subsection (a) remains in effect" in savings
    )
    assert "until modified or revoked in accordance with applicable law" in savings
    assert "NEW CODE PROVISION 59" not in savings
    owned = "".join(index.text[a:b] for a, b, _ in index.ownership_units())
    assert owned == index.text
    assert "NEW CODE PROVISION 59" in owned


def test_operative_eligibility_reference_is_not_narrowed_to_an_introduction():
    conditions = "".join(
        f"<paragraph><enum>({i + 1})</enum><text>CONDITION {i}: The applicant "
        f"must have completed the required district certification procedure "
        f"for program {i}.</text></paragraph>"
        for i in range(400)
    )
    index = _index(f"""
      <section><enum>1.</enum>
        <subsection id="eligibility"><enum>(a)</enum>
          <text>An applicant qualifies only if all of the following conditions
            are satisfied:</text>{conditions}
        </subsection>
        <subsection id="payment"><enum>(b)</enum>
          <text>Subject to subsection (a), the Secretary shall pay the applicant $100.</text>
        </subsection>
      </section>""")
    eligibility = next(node for node in index.nodes if node.identity == "eligibility")
    assert eligibility.end - eligibility.start > 30_000
    context, _ = _context(index, "payment")
    assert "only if all of the following conditions" in context
    assert "CONDITION 0:" in context
    assert "CONDITION 399:" in context


@pytest.mark.parametrize(
    "action",
    [
        "The Secretary may award grants under",
        "The Secretary shall make payments pursuant to",
        "Applicants are entitled to grants under",
    ],
)
def test_as_added_reference_keeps_restrictions_on_the_referenced_authority(action):
    index = _index(f"""
      <section id="insertion"><enum>1.</enum>
        <text>Title 10, United States Code, is amended by adding:</text>
        <quoted-block>
          <section><enum>6100.</enum>
            <text>The Secretary may award grants only to public hospitals
              that provide emergency care.</text>
          </section>
        </quoted-block>
      </section>
      <section id="grants"><enum>2.</enum>
        <text>{action} section 6100 of title 10, United States Code,
          as added by section 1 of this Act.</text>
      </section>""")
    context, _ = _context(index, "grants")
    assert "only to public hospitals" in context
    assert "that provide emergency care" in context


def test_amended_provision_reference_can_still_supply_operative_conditions():
    index = _index("""
      <section><enum>1.</enum>
        <subsection><enum>(a)</enum>
          <text>Section 6100 of title 10, United States Code, is amended by inserting:</text>
          <quoted-block><text>Grants may be awarded only to public hospitals
            that provide emergency care.</text></quoted-block>
        </subsection>
        <subsection id="payment"><enum>(b)</enum>
          <text>The Secretary shall make payments subject to the provision
            amended by subsection (a).</text>
        </subsection>
      </section>""")
    context, _ = _context(index, "payment")
    assert "only to public hospitals" in context
    assert "that provide emergency care" in context


def test_eligibility_table_reference_is_not_just_an_authorization_identity():
    index = _index("""
      <section id="payment"><enum>1.</enum>
        <text>The Secretary may pay County A $100 only if County A is listed
          as eligible in the table in section 2.</text>
      </section>
      <section><enum>2.</enum><header>Eligible counties</header>
        <table><tgroup><thead><row><entry>County</entry><entry>Status</entry></row></thead>
          <tbody><row><entry>County A</entry><entry>NOT ELIGIBLE</entry></row></tbody>
        </tgroup></table>
      </section>""")
    context, _ = _context(index, "payment")
    assert "County A" in context
    assert "NOT ELIGIBLE" in context


def test_table_rows_inherit_only_the_active_service_and_location():
    index = _index("""
      <section><enum>4601.</enum><header>Military construction</header>
        <table><tgroup>
          <colspec colname="service" colnum="0" coldef="txt"/>
          <colspec colname="location" colnum="2" coldef="txt"/>
          <colspec colname="amount" colnum="4" coldef="fig"/>
          <thead><row><entry namest="service" nameend="amount">Amounts in thousands of dollars</entry></row></thead>
          <tbody>
            <row><entry namest="service" nameend="location">Army account</entry><entry colname="amount"/></row>
            <row><entry colname="service"/><entry colname="location">Alabama</entry><entry colname="amount"/></row>
            <row><entry colname="service"/><entry colname="location">Training facility</entry><entry colname="amount">100</entry></row>
            <row><entry colname="service"/><entry colname="location">Alaska</entry><entry colname="amount"/></row>
            <row id="army-project"><entry colname="service"/><entry colname="location">Hospital construction</entry><entry colname="amount">200</entry></row>
            <row><entry namest="service" nameend="location">Navy account</entry><entry colname="amount"/></row>
            <row id="navy-first"><entry colname="service"/><entry colname="location">Reserve project</entry><entry colname="amount">300</entry></row>
            <row><entry colname="service"/><entry colname="location">Guam</entry><entry colname="amount"/></row>
            <row id="navy-project"><entry colname="service"/><entry colname="location">Shipyard improvements</entry><entry colname="amount">400</entry></row>
          </tbody>
        </tgroup></table>
      </section>""")
    army, _ = _context(index, "army-project")
    navy_first, _ = _context(index, "navy-first")
    navy, _ = _context(index, "navy-project")
    assert "Army account" in army and "Alaska" in army
    assert "Alabama" not in army and "Navy account" not in army
    assert "Navy account" in navy_first
    assert all(
        old not in navy_first for old in ("Army account", "Alabama", "Alaska", "Guam")
    )
    assert "Navy account" in navy and "Guam" in navy
    assert all(old not in navy for old in ("Army account", "Alabama", "Alaska"))
    for context in (army, navy_first, navy):
        assert "Amounts in thousands of dollars" in context


@pytest.mark.parametrize(
    "tag,attributes,external",
    [
        ("external-xref", 'legal-doc="usc" parsable-cite="usc/10/2"', True),
        ("internal-xref", 'idref="restriction"', False),
    ],
)
def test_xml_reference_authority_overrides_colliding_section_label(
    tag, attributes, external
):
    index = _index(
        f"""
      <section id="grant"><enum>1.</enum><text>Grants are subject to
        <{tag} {attributes}>section 2</{tag}>.</text></section>
      <section id="restriction"><enum>2.</enum><text>Only hospitals in Alaska qualify.</text></section>"""
    )
    context, unresolved = _context(index, "grant")
    assert ("Only hospitals in Alaska qualify" in context) is not external
    assert bool(unresolved) is external
    if external:
        assert any("usc/10/2" in ref for ref in unresolved)


@pytest.mark.parametrize("target", ["1", "2"])
def test_cross_section_incoming_rule_governs_only_referenced_grant(target):
    index = _index(f"""
      <section id="grant"><enum>1.</enum><text>Award hospital grants.</text></section>
      <section><enum>2.</enum><text>Award school grants.</text></section>
      <section><enum>3.</enum><text>Only public hospitals may receive grants
        under section {target} of this Act.</text></section>""")
    context, _ = _context(index, "grant")
    assert ("Only public hospitals" in context) == (target == "1")


@pytest.mark.parametrize("inherited", [True, False])
@pytest.mark.parametrize("scope", ["subparagraph", "paragraph"])
def test_declared_definition_scope_controls_sibling(inherited, scope):
    intro = f"For purposes of this {scope}, "
    meaning = "the term eligible hospital means a hospital in Alaska."
    content = (
        f"<text>{intro}</text><clause><enum>(i)</enum><text>{meaning}</text></clause>"
        if inherited
        else f"<text>{intro}{meaning}</text>"
    )
    index = _index(f"""
      <section><enum>1.</enum><paragraph><enum>(1)</enum>
      <subparagraph><enum>(A)</enum>{content}</subparagraph>
      <subparagraph id="applicant"><enum>(B)</enum><text>Award grants to each eligible hospital.</text></subparagraph>
      </paragraph></section>""")
    context, _ = _context(index, "applicant")
    assert ("hospital in Alaska" in context) == (scope == "paragraph")


def test_missing_scope_cannot_apply_an_unrelated_restriction_to_the_entire_act():
    index = _index(
        """
      <section id="grant"><enum>1.</enum><text>Award hospital grants.</text></section>
      <section id="pilot"><enum>2.</enum><text>Only Alaska hospitals are eligible under this subparagraph.</text></section>"""
    )
    grant, _ = _context(index, "grant")
    _, missing = _context(index, "pilot")
    assert "Alaska" not in grant
    assert "this subparagraph" in missing
