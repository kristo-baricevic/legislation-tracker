import pytest
from django.test import override_settings

from apps.legislation.enhancements import source_packet
from apps.legislation.tests.test_enhancement_source_packet import (
    _bill_with_contract_and_evidence,
)


def test_contents_entries_do_not_count_as_supplied_operative_sections():
    from apps.legislation.enhancements.source_sections import document_groups

    text = "SECTION 1. CONTENTS\nSec. 104. Eligibility.\nSec. 302. Checks.\nSEC. 104. ELIGIBILITY\nApplicants must complete training.\nSEC. 302. CHECKS\nThe Secretary shall check eligibility."
    groups = document_groups(text, "Introduced")
    assert [g["number"] for g in groups] == ["1", "104", "302"]


@pytest.mark.parametrize("input_limit,complete", [(None, True), (60000, False)])
def test_pinned_hr1589_compaction_preserves_selected_content_and_citation_offsets(
    settings, input_limit, complete
):
    from types import SimpleNamespace

    from apps.legislation.enhancements.citations import citation_spans
    from apps.legislation.evaluation.whole_bill import load_cases

    case = next(c for c in load_cases() if c["id"] == "BILLS-119hr1589ih")
    bill = SimpleNamespace(
        id=1,
        jurisdiction="federal",
        session=119,
        bill_number="HR 1589",
        title=case["title"],
        status="introduced",
        introduced_at=None,
    )
    if input_limit is not None:
        settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS = input_limit
    sources, envelope, request_bytes = source_packet.select_document_sources(
        bill, case["text"], case["id"]
    )
    coverage = envelope["source_packet"]["coverage"]
    assert coverage["complete_document"] is complete
    assert bool(coverage["omitted_sections"]) is not complete
    assert len(request_bytes) <= settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS
    assert len(request_bytes) <= settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES
    selected_text = "".join(
        case["text"][s["start_char"] : s["end_char"]]
        for s in coverage["selected_sections"]
    )
    if complete:
        assert "".join(selected_text.split()) == "".join(case["text"].split())
    assert "".join("".join(s["quoted_text"].split()) for s in sources) == "".join(
        selected_text.split()
    )
    for raw, sent in zip(sources, envelope["source_packet"]["sources"], strict=True):
        assert case["text"][raw["start_char"] : raw["end_char"]] == raw["quoted_text"]
        assert "".join(raw["quoted_text"].split()) == "".join(
            sent["quoted_text"].split()
        )
        assert citation_spans(raw["quoted_text"], sent["quoted_text"])


@pytest.mark.django_db
def test_packet_never_selects_a_partial_section_or_extraction_fragment():
    bill = _bill_with_contract_and_evidence()
    document = bill.documents.get()
    large = (
        "SEC. 104. ELIGIBILITY\nThe Secretary shall approve only if--\n(A) eligible; and\n(B) "
        + "training " * 1400
        + ".\n"
    )
    small = "SEC. 312. SURCHARGE\nApplicants shall pay an additional $25 for counsel."
    document.extracted_text = large + small
    document.save(update_fields=["extracted_text"])
    overhead = len(
        source_packet.canonical_json_bytes(
            source_packet._request_envelope(bill, [], truncated=True)
        )
    )
    with override_settings(
        LLM_ENHANCEMENT_MAX_REQUEST_BYTES=overhead + 6000,
        LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS=overhead + 6000,
    ):
        packet = source_packet.build_enhancement_preflight(bill)
    assert all(s["kind"] == "document_chunk" for s in packet.source_snapshot)
    assert not any(
        "Secretary shall approve" in s["quoted_text"] for s in packet.source_snapshot
    )
    assert any("additional $25" in s["quoted_text"] for s in packet.source_snapshot)
    coverage = packet.request_envelope["source_packet"]["coverage"]
    assert [s["label"] for s in coverage["omitted_sections"]] == ["Sec. 104"]
    assert packet.truncated is True


@pytest.mark.django_db
def test_complete_sections_keep_all_chunks_and_cross_reference_coverage():
    bill = _bill_with_contract_and_evidence()
    document = bill.documents.get()
    text = (
        "SEC. 1. DUTIES\nThe Secretary shall approve applicants described in section 2.\n"
        + "Supporting text. " * 300
        + "\nSEC. 2. CONDITIONS\nApplicants must hold a permit and complete training."
    )
    document.extracted_text = text
    document.save(update_fields=["extracted_text"])
    packet = source_packet.build_enhancement_preflight(bill)
    coverage = packet.request_envelope["source_packet"]["coverage"]
    assert coverage["complete_document"] is True
    assert coverage["omitted_sections"] == []
    assert len(coverage["selected_sections"]) == 2
    selected = coverage["selected_sections"][0]
    assert len(selected["source_refs"]) >= 2
    assert selected["unresolved_section_references"] == []
    for source in packet.source_snapshot:
        assert text[source["start_char"] : source["end_char"]] == source["quoted_text"]
    assert "complete training" in packet.source_snapshot[-1]["quoted_text"]


@pytest.mark.django_db
def test_omitted_same_bill_reference_is_not_silently_treated_as_resolved():
    bill = _bill_with_contract_and_evidence()
    document = bill.documents.get()
    document.extracted_text = (
        "SEC. 1. DUTY\nThe Secretary shall grant status subject to section 2.\nSEC. 2. CONDITIONS\n"
        + "Condition. " * 2000
    )
    document.save(update_fields=["extracted_text"])
    overhead = len(
        source_packet.canonical_json_bytes(
            source_packet._request_envelope(bill, [], truncated=True)
        )
    )
    with override_settings(
        LLM_ENHANCEMENT_MAX_REQUEST_BYTES=overhead + 5000,
        LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS=overhead + 5000,
    ):
        packet = source_packet.build_enhancement_preflight(bill)
    selected = packet.request_envelope["source_packet"]["coverage"]["selected_sections"]
    assert selected[0]["unresolved_section_references"] == ["2"]
