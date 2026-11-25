"""Immutable rendered offsets, rather than XML sibling order, own source text."""

from types import SimpleNamespace

import pytest
from django.test import override_settings

from apps.ingestion.document_download import extract_document_text
from apps.legislation.enhancements.reader_chunking import planned_sources
from apps.legislation.enhancements.reader_dependencies import DependencyIndex
from apps.legislation.enhancements.xml_sections import xml_boundaries


@pytest.mark.parametrize("body", ["legis-body", "engrossed-amendment-body"])
@pytest.mark.parametrize("target", [1000, 8000])
def test_large_quoted_amendment_and_inline_continuation_have_disjoint_complete_ownership(
    body, target
):
    reports = "".join(
        f"<paragraph><enum>({i + 1})</enum><text>The Secretary shall publish report "
        f"number {i + 1} about program operations.</text></paragraph>"
        for i in range(400)
    )
    raw = (
        f'<bill><{body}><section id="s"><enum>1.</enum><header>Requirements</header>'
        '<text>The Act is amended by adding:</text><quoted-block id="q">'
        '<section id="inside"><enum>100.</enum>'
        "<text>Programs shall comply with the following requirements:</text>"
        + reports
        + "</section></quoted-block><after-quoted-block>and by inserting "
        '<quoted-text id="inline">other hospital programs</quoted-text> '
        'in the table of contents and replacing <quoted-text id="second">old entry</quoted-text> '
        f"with a new entry.</after-quoted-block></section></{body}></bill>"
    ).encode()
    text = extract_document_text(raw, "application/xml", "bill.xml")
    sections = xml_boundaries(raw, text)
    index = DependencyIndex(text, sections)
    nodes = {node.identity: node for node in sections.provisions}
    if body == "legis-body":
        assert nodes["inline"].end < nodes["q"].start
        assert nodes["second"].end < nodes["q"].start
    else:
        assert nodes["q"].end < nodes["inline"].start
    assert (
        text[nodes["inline"].start : nodes["inline"].end] == "other hospital programs"
    )
    assert text[nodes["second"].start : nodes["second"].end] == "old entry"
    units = index.ownership_units()
    assert "".join(text[start:end] for start, end, _ in units) == text
    assert all(
        left[1] == right[0] for left, right in zip(units, units[1:], strict=False)
    )
    for number, node in enumerate(index.nodes):
        for start, end in index.direct[number]:
            assert node.start <= start < end <= node.end
            assert all(
                end <= index.nodes[child].start or start >= index.nodes[child].end
                for child in index.children[number]
            )
    with override_settings(
        LLM_ENHANCEMENT_PROVIDER="openai",
        LLM_ENHANCEMENT_MODEL="gpt-5.6-luna",
        LLM_ENHANCEMENT_REASONING_EFFORT="none",
    ):
        sources = planned_sources(
            SimpleNamespace(version_label="Test"), text, 1, target, sections
        )
    assert "".join(source["quoted_text"] for source in sources) == text
    assert all(
        source["quoted_text"] == text[source["start_char"] : source["end_char"]]
        for source in sources
    )
    assert all(
        left["end_char"] == right["start_char"]
        for left, right in zip(sources, sources[1:], strict=False)
    )
