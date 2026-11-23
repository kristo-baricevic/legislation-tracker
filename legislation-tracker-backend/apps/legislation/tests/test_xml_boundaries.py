import pytest
from pathlib import Path

from apps.ingestion.document_download import extract_document_text
from apps.legislation.enhancements.source_graph import build_source_graph, audit_graph


@pytest.mark.parametrize('body', ['legis-body', 'engrossed-amendment-body'])
def test_s2296_contents_only_section_wrapper_is_not_an_operative_section(body):
    from apps.legislation.enhancements.xml_sections import xml_boundaries
    raw = f'''<bill><{body}>
    <section id="before"><enum>725.</enum><text>Publish a report.</text></section>
    <section id="contents" section-type="undesignated-section"><toc>
      <toc-entry level="section">Sec. 801. Acquisition policy.</toc-entry>
    </toc></section>
    <section id="after"><enum>801.</enum><text>Provide grants.</text></section>
    </{body}></bill>'''.encode()
    text = extract_document_text(raw, 'application/xml', 'bill.xml')
    rows = xml_boundaries(raw, text)
    assert [r[0] for r in rows] == ['before', 'after']
    assert 'Publish a report.' in text[rows[0][1]:rows[0][2]]
    assert 'Provide grants.' in text[rows[1][1]:rows[1][2]]
    assert rows[0][2] <= rows[1][1]


def test_section_with_contents_and_operative_text_is_not_discarded():
    from apps.legislation.enhancements.xml_sections import xml_boundaries
    raw = b'<bill><legis-body><section id="mixed"><enum>1.</enum><toc><toc-entry>Contents</toc-entry></toc><text>Provide $100 for schools.</text></section></legis-body></bill>'
    text = extract_document_text(raw, 'application/xml', 'bill.xml')
    rows = xml_boundaries(raw, text)
    assert [r[0] for r in rows] == ['mixed']
    assert '$100' in text[rows[0][1]:rows[0][2]]


@pytest.mark.parametrize("body", ["legis-body", "engrossed-amendment-body"])
def test_xml_sections_own_quoted_amendments_not_contents_or_adjacent_headers(body):
    from apps.legislation.enhancements.xml_sections import xml_boundaries
    xml = f"""<bill><{body}><title><enum>I</enum><toc><toc-entry>Sec. 1. Grants</toc-entry></toc>
    <section id="a"><enum>1.</enum><header>Grants</header><text>Pay $5.</text>
    <quoted-block><amendment-body><section id="quoted"><enum>99.</enum><text>Pay $4.</text></section></amendment-body></quoted-block></section>
    </title><title><enum>II</enum><section id="b"><enum>1.</enum><header>Dates</header>
    <text>Starts in May.</text></section></title></{body}><attestation>Signed</attestation></bill>""".encode()
    text = extract_document_text(xml, "application/xml", "bill.xml")
    boundaries = xml_boundaries(xml, text)
    g = build_source_graph("different-bill", "IH", text, xml_sections=boundaries)
    assert [row[0] for row in boundaries] == ["a", "b"]
    assert len(g.units) == 2 and not audit_graph(g, text)
    parts = [g.passages[u.own_passage_ids[0]].text for u in g.units]
    assert "$4" in parts[0] and "II" not in parts[0]
    assert "Starts in May" in parts[1] and "Signed" not in parts[1]
    with pytest.raises(ValueError):
        xml_boundaries(xml, "changed " + text)


def test_s1071_eah_18343_real_sections_survive_split_number_and_heading():
    from apps.legislation.enhancements.xml_sections import xml_boundaries
    raw = (Path(__file__).parent / "fixtures/xml_inventory/s1071_eah_excerpt.xml").read_bytes()
    text = extract_document_text(raw, "application/xml", "bill.xml")
    rows = xml_boundaries(raw, text)
    assert [(r[0], r[3]) for r in rows] == [
        ("H3B4EED465B8A4B8D8A9335595DB1BFDA", "Sec. 8805"),
        ("H08AE0501C5214B949D629D2130697AF4", "Sec. 8806")]
    graph = build_source_graph("18343", "Engrossed Amendment House", text, xml_sections=rows)
    parts = [graph.passages[u.own_passage_ids[0]].text for u in graph.units]
    assert len(parts) == 2
    assert parts[0].startswith("8805.\nBriefing") and "Disinterment" not in parts[0]
    assert parts[1].startswith("8806.\nDisinterment")


def test_older_flattened_legis_body_text_keeps_its_existing_citation_offsets():
    from apps.legislation.enhancements.xml_sections import xml_boundaries
    raw = b"<bill><legis-body><section id='s'><enum>12.</enum><header>Grants</header><text>Pay $5.</text></section></legis-body></bill>"
    text = "12.\nGrants\nPay $5."
    assert xml_boundaries(raw, text) == (("s", 0, len(text), "Sec. 12", "Grants"),)


def test_missing_object_blocks_preflight_without_a_server_error(monkeypatch):
    from types import SimpleNamespace
    from botocore.exceptions import ClientError
    from apps.legislation.enhancements import xml_sections
    from apps.legislation.enhancements.source_packet import PreflightUnavailable
    def missing(*args):
        raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
    monkeypatch.setattr(xml_sections.default_storage, "open", missing)
    doc = SimpleNamespace(object_storage_key="bill.xml", file_size_bytes=100)
    with pytest.raises(PreflightUnavailable) as error:
        xml_sections.stored_xml_sections(doc, "bill")
    assert error.value.reason == "source_unavailable"
