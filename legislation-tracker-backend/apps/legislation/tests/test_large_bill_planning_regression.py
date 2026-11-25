"""Bounded whole-bill plans, using real XML, storage and database identities.

The small cases run in the regular suite. Set LARGE_BILL_XML_PATH to the pinned
BILLS-119s1071eah.xml to run the full 3.37-million-character regression as well.
These are offline planning tests: they do not establish model output quality.
"""

import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from time import monotonic

import pytest
from django.conf import settings as django_settings

from apps.ingestion.document_download import extract_document_text
from apps.legislation.enhancements.model_selection import planning_for
from apps.legislation.enhancements.reader_batches import build_reader_preflight
from apps.legislation.enhancements.reader_capacity import fits
from apps.legislation.enhancements.reader_discovery import policy_passages
from apps.legislation.enhancements.source_packet import (
    build_document_preflight,
    canonical_json_bytes,
)
from apps.legislation.enhancements.xml_sections import stored_xml_sections
from apps.legislation.models import Bill, BillDocument

FIXTURES = Path(__file__).parent / "fixtures"
NOTIFICATION = (
    "The Secretary of Veterans Affairs may not carry out subsection (a) until "
    "after notifying the next of kin of Fernando V. Cota."
)
DISPOSITION = (
    "if no such next of kin responds to the notification under subsection (b), "
    "arrange for disposition of the remains as the Secretary determines appropriate."
)


@pytest.fixture
def offline_large_bill_settings(settings, monkeypatch, tmp_path):
    settings.STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": tmp_path},
        }
    }
    settings.LLM_ENHANCEMENT_PROVIDER = "openai"
    settings.LLM_ENHANCEMENT_MODEL = "offline-large-bill"
    settings.LLM_READER_MODEL_CAPACITIES = {
        "openai/offline-large-bill": {
            "context_tokens": 1_048_576,
            "output_tokens": 262_144,
        }
    }
    settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES = 120_000
    settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS = 100_000
    settings.LLM_READER_MAX_OUTPUT_TOKENS = 24_000
    settings.LLM_READER_MAX_CALLS = 0

    def forbid_network(*args, **kwargs):
        pytest.fail("Offline preflight attempted an HTTP request")

    monkeypatch.setattr("httpx.Client.send", forbid_network)
    monkeypatch.setattr("httpx.AsyncClient.send", forbid_network)
    monkeypatch.setattr("requests.sessions.Session.request", forbid_network)


def _stored_document(raw, tmp_path, *, text=None, number="S 1071"):
    text = text or extract_document_text(raw, "application/xml", "bill.xml")
    filename = "bill.xml"
    (tmp_path / filename).write_bytes(raw)
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number=number,
        title="Large bill planning regression",
        status="introduced",
    )
    return BillDocument.objects.create(
        bill=bill,
        version_label="Engrossed Amendment House",
        is_active_version=True,
        extracted_text=text,
        content_hash=hashlib.sha256(raw).hexdigest(),
        content_type="application/xml",
        object_storage_key=filename,
        file_size_bytes=len(raw),
    )


def _assert_complete_bounded_plan(plan, text, sections):
    scans = [s for s in plan.source_snapshot if s.get("discovery_source")]
    assert scans
    cursor = 0
    for source in scans:
        assert source["start_char"] == cursor
        cursor = source["end_char"]
        assert source["quoted_text"] == text[source["start_char"] : cursor]
        assert not source.get("omitted_dependency_ranges")
    assert cursor == len(text)
    assert "".join(source["quoted_text"] for source in scans) == text

    coverage = plan.source_manifest["coverage"]
    assert coverage["complete_document"] is True
    assert coverage["sections_planned"] == len(sections)
    assert coverage["sections_omitted"] == 0
    assert coverage["source_chars_planned"] == len(text)

    reviews = [
        batch
        for batch in plan.reader_batches
        if batch.request_envelope.get("source_review")
    ]
    assert reviews
    assert Counter(policy_passages(scans)) == Counter(
        key for batch in reviews for key in policy_passages(batch.source_snapshot)
    )
    sizes = []
    for envelope in [
        plan.request_envelope,
        *(b.request_envelope for b in plan.reader_batches),
    ]:
        size = len(canonical_json_bytes(envelope))
        sizes.append(size)
        assert size <= django_settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES
        assert size <= django_settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS
        assert fits(envelope), f"Serialized {size}-byte request exceeds model capacity"
    return {
        "source_characters": len(text),
        "sections": len(sections),
        "owned_chunks": len(scans),
        "review_requests": len(reviews),
        "planned_calls": plan.source_manifest["budget"]["planned_calls"],
        "maximum_serialized_request_bytes": max(sizes),
    }


def _passage_intervals(source):
    from apps.legislation.enhancements.reader_citations import citation_passages

    start = source["start_char"]
    for passage in citation_passages(source):
        end = start + len(passage["text"])
        yield start, end, passage
        start = end


def _owns_offset(source, offset):
    if not source.get("discovery_source") or not (
        source["start_char"] <= offset < source["end_char"]
    ):
        return False
    selected = source.get("review_quote_ids")
    return any(
        start <= offset < end
        and passage["quote_id"]
        and (selected is None or passage["quote_id"] in selected)
        for start, end, passage in _passage_intervals(source)
    )


def _contiguous_evidence(text, intervals):
    """Join only contiguous original spans, preserving words split by citations."""
    merged = []
    for start, end in sorted(set(intervals)):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return "\n".join(text[start:end] for start, end in merged)


def _assert_context_for_owned_text(plan, text, owned_quote, expected):
    from apps.legislation.enhancements.reader_citations import citation_passages

    offset = text.index(owned_quote)
    requests = [
        batch
        for batch in plan.reader_batches
        if batch.request_envelope.get("source_review")
        and any(_owns_offset(source, offset) for source in batch.source_snapshot)
    ]
    assert requests, f"No request owns {owned_quote!r}"
    for request in requests:
        packet = request.request_envelope["source_packet"]
        wire_sources = {source["source_ref"]: source for source in packet["sources"]}
        supplied_intervals = []
        for source in request.source_snapshot:
            catalog = wire_sources[source["source_ref"]].get("citation_passages", [])
            supplied_intervals.extend(
                (start, end)
                for start, end, passage in _passage_intervals(source)
                if passage in catalog
            )
        for selected_owner in request.source_snapshot:
            if not _owns_offset(selected_owner, offset):
                continue
            owner = next(
                source
                for source in plan.source_snapshot
                if source["source_ref"] == selected_owner["source_ref"]
                and source.get("discovery_source")
            )
            deferred_quotes = owner.get("deferred_context_quote_ids", {})
            for ref in owner.get("deferred_context_source_refs", []):
                dependency = next(
                    source
                    for source in plan.source_snapshot
                    if source["source_ref"] == ref and source.get("discovery_source")
                )
                selected_ids = set(deferred_quotes[ref])
                mapped_ids = {
                    passage["quote_id"]
                    for batch in plan.reader_batches
                    for source in batch.source_snapshot
                    if source["source_ref"] == ref and source.get("factual_map")
                    for passage in citation_passages(source)
                    if passage["quote_id"]
                    and (
                        source.get("review_quote_ids") is None
                        or passage["quote_id"] in source["review_quote_ids"]
                    )
                }
                assert selected_ids - {None} <= mapped_ids
                supplied_intervals.extend(
                    (start, end)
                    for start, end, passage in _passage_intervals(dependency)
                    if passage["quote_id"] in selected_ids
                )
        supplied = _contiguous_evidence(text, supplied_intervals)
        supplied += "\n" + packet.get("section_context", "")
        for quote in expected:
            assert quote in supplied, f"Request omits governing evidence: {quote!r}"


def _assert_veterans_conditions(plan, text):
    _assert_context_for_owned_text(
        plan,
        text,
        "a briefing on the status of implementation",
        [
            "Not later than 30 days",
            "not less frequently than monthly thereafter",
            "five years after such date",
            "the Federated States of Micronesia",
            "the Republic of the Marshall Islands",
            "the Republic of Palau",
        ],
    )
    _assert_context_for_owned_text(
        plan,
        text,
        "shall disinter the remains of Fernando V. Cota",
        [NOTIFICATION],
    )
    _assert_context_for_owned_text(
        plan,
        text,
        "arrange for disposition of the remains",
        [
            "After carrying out subsection (a)",
            "relinquish the remains to the next of kin",
            DISPOSITION,
        ],
    )


@pytest.mark.django_db
@pytest.mark.parametrize("target", [0, 1_000, 2_000, 4_000])
def test_real_s1071_excerpt_preserves_conditional_actions(
    tmp_path, offline_large_bill_settings, target
):
    raw = (FIXTURES / "xml_inventory/s1071_eah_excerpt.xml").read_bytes()
    document = _stored_document(raw, tmp_path)
    sections = stored_xml_sections(document, document.extracted_text)
    assert [section[3] for section in sections] == ["Sec. 8805", "Sec. 8806"]
    with planning_for(("openai", "offline-large-bill"), owned_target=target):
        plan = build_reader_preflight(
            document, xml_sections=sections, reuse_publication=False
        )
        _assert_complete_bounded_plan(plan, document.extracted_text, sections)
    _assert_veterans_conditions(plan, document.extracted_text)


@pytest.mark.django_db
@pytest.mark.parametrize("target", [0, 1_000, 4_000])
def test_oversized_section_retains_parent_condition_later_prohibition_and_definition(
    tmp_path, offline_large_bill_settings, target
):
    parent_condition = (
        "The Secretary shall award grants only to qualifying public hospitals."
    )
    definition = "The term qualifying public hospital means a public hospital serving a rural county."
    prohibition = "No funds under this section may be used for lobbying."
    paragraphs = "".join(
        f'<paragraph id="program-{i}"><enum>({i})</enum><text>'
        f"Program {i} shall support local medical services and provide public progress reports. "
        + (
            "The report shall describe the services provided, the number of residents served, "
            "and the work required to maintain those services in the coming year. "
        )
        * 3
        + "</text></paragraph>"
        for i in range(1, 271)
    )
    raw = (
        '<bill><legis-body><section id="definitions"><enum>1.</enum><header>Definitions</header>'
        f"<text>In this Act, {definition[0].lower() + definition[1:]}</text></section>"
        '<section id="programs"><enum>2.</enum><header>Hospital programs</header>'
        f"<text>{parent_condition}</text>{paragraphs}"
        f'<subsection id="restriction"><enum>(b)</enum><header>Restriction</header><text>{prohibition}</text></subsection>'
        "</section></legis-body></bill>"
    ).encode()
    document = _stored_document(raw, tmp_path, number="HR 99999")
    text = document.extracted_text
    assert len(text.encode()) > 120_000
    sections = stored_xml_sections(document, text)
    with planning_for(("openai", "offline-large-bill"), owned_target=target):
        plan = build_document_preflight(document, reuse_publication=False)
        _assert_complete_bounded_plan(plan, text, sections)
    _assert_context_for_owned_text(
        plan,
        text,
        "Program 1 shall support local medical services",
        [parent_condition, definition[0].lower() + definition[1:], prohibition],
    )


@pytest.fixture(scope="module")
def pinned_s1071_source():
    source_path = os.environ.get("LARGE_BILL_XML_PATH")
    if not source_path:
        pytest.skip("Set LARGE_BILL_XML_PATH to run the full pinned S.1071 regression")
    raw = Path(source_path).read_bytes()
    manifest = json.loads((FIXTURES / "harness/119s1071eah.json").read_text())
    assert hashlib.sha256(raw).hexdigest() == manifest["xml_sha256"]
    text = extract_document_text(raw, "application/xml", "bill.xml")
    assert hashlib.sha256(text.encode()).hexdigest() == manifest["text_sha256"]
    assert len(text) == manifest["chars"]
    return raw, text


@pytest.mark.django_db
@pytest.mark.parametrize("target", [0, 1_000, 2_000, 4_000])
def test_full_pinned_s1071_has_executable_complete_bounded_plan(
    tmp_path, offline_large_bill_settings, pinned_s1071_source, target, record_property
):
    raw, text = pinned_s1071_source
    document = _stored_document(raw, tmp_path, text=text)
    sections = stored_xml_sections(document, text)
    inventory = json.loads((FIXTURES / "xml_inventory/s1071_eah.json").read_text())
    assert len(sections) == inventory["sections"] == 1_134
    assert (
        hashlib.sha256(
            "\n".join(section[0] for section in sections).encode()
        ).hexdigest()
        == inventory["ordered_id_sha256"]
    )
    started = monotonic()
    with planning_for(("openai", "offline-large-bill"), owned_target=target):
        plan = build_document_preflight(document, reuse_publication=False)
        planning_seconds = round(monotonic() - started, 3)
        report = _assert_complete_bounded_plan(plan, text, sections)
    _assert_veterans_conditions(plan, text)
    report.update(
        owned_target=target,
        planning_seconds=planning_seconds,
        planning_and_checks_seconds=round(monotonic() - started, 3),
    )
    record_property("large_bill_plan", json.dumps(report, sort_keys=True))
    print(json.dumps(report, sort_keys=True))
