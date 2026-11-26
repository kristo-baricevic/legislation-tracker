"""Incoming references remain evidence until their applicability is reviewed."""

from types import SimpleNamespace

import pytest
from django.test import override_settings

from apps.ingestion.document_download import extract_document_text
from apps.legislation.enhancements.model_selection import planning_for
from apps.legislation.enhancements.reader_batches import build_reader_preflight
from apps.legislation.enhancements.reader_chunking import planned_sources
from apps.legislation.enhancements.reader_citations import citation_passages
from apps.legislation.enhancements.xml_sections import (
    stored_xml_sections,
    xml_boundaries,
)
from apps.legislation.tests.test_large_bill_planning_regression import (
    _assert_complete_bounded_plan,
    _assert_context_for_owned_text,
    _stored_document,
)
from apps.legislation.tests.test_large_bill_planning_regression import (
    offline_large_bill_settings as offline_large_bill_settings,
)

GRANT = "The Secretary shall award grants to hospitals."
RESTRICTIONS = [
    "Only public hospitals are eligible for grants under this section.",
    "Only public hospitals may receive a grant under subsection (a).",
    "A grant under subsection (a) may be used only for construction of public hospitals.",
    "No grant under subsection (a) may be awarded to private hospitals.",
    # A new phrase outside any restriction-word list must also remain evidence.
    "Recipients of grants under subsection (a) must be publicly owned hospitals.",
]


def _large_section(restriction, *, extra_conditions=""):
    reports = "".join(
        f"<paragraph><enum>({i + 1})</enum><text>The Secretary shall publish administrative "
        f"report number {i + 1} about program operations.</text></paragraph>"
        for i in range(350)
    )
    return (
        '<bill><engrossed-amendment-body><section id="s"><enum>1.</enum>'
        '<header>Hospital grants</header><subsection id="grant"><enum>(a)</enum>'
        f'<text>{GRANT}</text></subsection><subsection id="reports">'
        f"<enum>(b)</enum><header>Program reports</header>{reports}</subsection>"
        '<subsection id="restriction"><enum>(c)</enum>'
        f"<text>{restriction}</text>{extra_conditions}</subsection>"
        "</section></engrossed-amendment-body></bill>"
    ).encode()


@pytest.mark.parametrize("restriction", RESTRICTIONS)
def test_distant_incoming_restriction_has_citable_context_without_wording_gate(
    restriction,
):
    raw = _large_section(restriction)
    text = extract_document_text(raw, "application/xml", "bill.xml")
    sections = xml_boundaries(raw, text)
    with override_settings(
        LLM_ENHANCEMENT_PROVIDER="openai",
        LLM_ENHANCEMENT_MODEL="gpt-5.6-luna",
        LLM_ENHANCEMENT_REASONING_EFFORT="none",
    ):
        sources = planned_sources(
            SimpleNamespace(version_label="Test"), text, 1, 1000, sections
        )
    grant = next(source for source in sources if GRANT in source["quoted_text"])
    evidence = [
        passage["text"]
        for source in sources
        if source["source_ref"] in grant["context_source_refs"]
        for passage in citation_passages(source)
        if passage["quote_id"] in grant["context_quote_ids"][source["source_ref"]]
    ]
    context = "\n".join(evidence)
    assert restriction in context
    assert not grant["unresolved_dependencies"]
    assert "report number 350" not in context
    assert "".join(source["quoted_text"] for source in sources) == text


def test_structural_incoming_reference_does_not_need_a_rendered_subsection_label():
    restriction = (
        'Recipients of <internal-xref idref="grant">these grants</internal-xref>'
        " must be publicly owned hospitals."
    )
    raw = _large_section(restriction)
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
            1000,
            xml_boundaries(raw, text),
        )
    grant = next(source for source in sources if GRANT in source["quoted_text"])
    context = "\n".join(
        source["quoted_text"]
        for source in sources
        if source["source_ref"] in grant["context_source_refs"]
    )
    assert "Recipients of these grants must be publicly owned hospitals." in context


@pytest.mark.parametrize("target", [1000, 8000])
@pytest.mark.parametrize("cyclic", [False, True], ids=["chain", "cycle"])
def test_indirect_eligibility_includes_incoming_restrictions_only_for_reached_rules(
    target, cyclic, offline_large_bill_settings
):
    grant = "The Secretary shall award grants to applicants eligible under section 2."
    requirement = "An applicant must operate a hospital."
    restriction = "Only public hospitals may qualify under section 2."
    unrelated = "Only rural schools may qualify under section 4."
    reports = "".join(
        f"<paragraph><enum>({i})</enum><text>Publish administrative report {i} "
        "on the department's annual operations.</text></paragraph>"
        for i in range(1, 141)
    )
    cycle = " Section 6 also applies to these applications." if cyclic else ""
    # Keep separate sections out of the same packed owner so assertions check
    # legal dependencies, independent of citation-passage boundary padding.
    sections = "".join(
        f"<title><section><enum>{number}.</enum>{body}</section></title>"
        for number, body in (
            (1, f"<text>{grant}</text>"),
            (100, reports),
            (2, f"<text>{requirement}{cycle}</text>"),
            (101, reports),
            (3, f"<text>{restriction}</text>"),
            (
                4,
                "<text>Fund school buildings near applicants described in section 2.</text>",
            ),
            (5, f"<text>{unrelated}</text>"),
            (6, "<text>Process applications received under section 2.</text>"),
        )
    )
    raw = f"<bill><legis-body>{sections}</legis-body></bill>".encode()
    text = extract_document_text(raw, "application/xml", "bill.xml")
    sources = planned_sources(
        SimpleNamespace(version_label="Test"),
        text,
        1,
        target,
        xml_boundaries(raw, text),
    )
    owned = next(source for source in sources if grant in source["quoted_text"])
    assert restriction not in owned["quoted_text"]
    context = "\n".join(
        passage["text"]
        for source in sources
        for passage in citation_passages(source)
        if passage["quote_id"]
        in owned["context_quote_ids"].get(source["source_ref"], [])
    )
    assert requirement in context
    assert restriction in context
    assert unrelated not in context
    assert "administrative report 140" not in context
    assert not owned["unresolved_dependencies"]


@pytest.mark.django_db
def test_oversized_incoming_context_becomes_a_required_mapped_dependency(
    tmp_path, offline_large_bill_settings, settings
):
    conditions = "".join(
        f"<paragraph><enum>({i + 1})</enum><text>Governing term {i + 1}: "
        "Hospitals receiving funds must retain their publicly owned status throughout "
        "construction and operation of each facility supported by the grant.</text></paragraph>"
        for i in range(180)
    )
    raw = _large_section(RESTRICTIONS[0], extra_conditions=conditions)
    document = _stored_document(raw, tmp_path, number="S 9991")
    text = document.extracted_text
    sections = stored_xml_sections(document, text)
    settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES = 18_000
    settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS = 18_000
    with planning_for(("openai", "offline-large-bill"), owned_target=1000):
        plan = build_reader_preflight(
            document, xml_sections=sections, reuse_publication=False
        )
        _assert_complete_bounded_plan(plan, text, sections)
    grant = next(
        source
        for source in plan.source_snapshot
        if source.get("discovery_source") and GRANT in source["quoted_text"]
    )
    assert grant["deferred_context_source_refs"]
    assert grant["factual_map"]
    _assert_context_for_owned_text(
        plan, text, GRANT, [RESTRICTIONS[0], "Governing term 1:", "Governing term 180:"]
    )
