import hashlib
import math

import pytest
from django.test import override_settings

from apps.legislation.enhancements import source_packet
from apps.legislation.enhancements.source_packet import (
    PreflightUnavailable,
    build_enhancement_preflight,
)
from apps.legislation.models import Bill, BillContract, BillDocument, EvidenceSpan


def _bill_with_contract_and_evidence():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 500",
        title="Reporting and Grants Act",
        status="introduced",
    )
    source = (
        "SEC. 2. REPORTING. The Secretary shall publish a report. "
        "SEC. 3. GRANTS. There is authorized to be appropriated $5,000,000."
    )
    document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        is_active_version=True,
        extracted_text=source,
        content_hash=hashlib.sha256(source.encode()).hexdigest(),
    )
    contract_json = {
        "schema_version": "2.0-legal-nlp",
        "plain_summary": "The bill requires reporting and authorizes grants.",
        "requirements": [
            {"display_text": "The Secretary must publish a report."},
        ],
        "funding_items": [
            {"display_text": "The bill authorizes $5,000,000."},
        ],
    }
    contract = BillContract.objects.create(
        bill=bill,
        document=document,
        schema_version="2.0-legal-nlp",
        contract_json=contract_json,
        contract_hash="contract-hash-500",
    )
    bill.latest_contract = contract
    bill.save(update_fields=["latest_contract"])
    reporting_quote = "The Secretary shall publish a report."
    funding_quote = "There is authorized to be appropriated $5,000,000."
    EvidenceSpan.objects.create(
        bill=bill,
        document=document,
        contract=contract,
        field_path="requirements[0].display_text",
        start_char=source.index(reporting_quote),
        end_char=source.index(reporting_quote) + len(reporting_quote),
        quoted_text=reporting_quote,
    )
    EvidenceSpan.objects.create(
        bill=bill,
        document=document,
        contract=contract,
        field_path="funding_items[0].display_text",
        start_char=source.index(funding_quote),
        end_char=source.index(funding_quote) + len(funding_quote),
        quoted_text=funding_quote,
    )
    return bill


@pytest.mark.django_db
def test_complete_request_is_canonical_bounded_and_uses_exact_evidence():
    bill = _bill_with_contract_and_evidence()

    first = build_enhancement_preflight(bill)
    second = build_enhancement_preflight(Bill.objects.get(pk=bill.pk))

    assert [item["field_path"] for item in first.source_snapshot] == [
        "requirements[0].display_text",
        "funding_items[0].display_text",
    ]
    assert first.source_snapshot[0]["quoted_text"] == (
        "The Secretary shall publish a report."
    )
    assert first.estimated_input_tokens == math.ceil(len(first.request_bytes) / 2)
    assert first.request_fingerprint == hashlib.sha256(first.request_bytes).hexdigest()
    assert first.request_bytes == second.request_bytes
    assert first.source_fingerprint == second.source_fingerprint
    assert len(first.request_bytes) <= 120000
    assert first.truncated is False


@pytest.mark.django_db
def test_document_text_is_used_when_contract_has_no_usable_evidence():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="S 501",
        title="Fallback Text Act",
        status="introduced",
    )
    text = "SEC. 2. DUTY. The Administrator shall publish guidance."
    BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        is_active_version=True,
        extracted_text=text,
    )

    preflight = build_enhancement_preflight(bill)

    assert preflight.source_snapshot == [
        {
            "source_ref": "src_0001",
            "kind": "document_chunk",
            "field_path": None,
            "section_label": "Introduced",
            "quoted_text": text,
            "start_char": 0,
            "end_char": len(text),
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        }
    ]


@pytest.mark.django_db
def test_blank_active_document_does_not_hide_an_older_stored_document():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="S 501A",
        title="Fallback Version Act",
        status="introduced",
    )
    older_text = "SEC. 2. The Secretary shall publish an annual report."
    BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        is_active_version=False,
        extracted_text=older_text,
    )
    BillDocument.objects.create(
        bill=bill,
        version_label="Engrossed",
        is_active_version=True,
        extracted_text="",
        raw_text="",
    )

    preflight = build_enhancement_preflight(bill)

    assert preflight.source_snapshot[0]["section_label"] == "Introduced"
    assert preflight.source_snapshot[0]["quoted_text"] == older_text


@pytest.mark.django_db
def test_source_selection_shrinks_until_the_complete_request_fits():
    bill = _bill_with_contract_and_evidence()
    document = bill.documents.get()
    contract = bill.latest_contract
    source_text = document.extracted_text
    for index in range(8):
        quote = f"Additional provision {index}. " + ("x" * 900)
        start = len(source_text)
        source_text += "\n" + quote
        EvidenceSpan.objects.create(
            bill=bill,
            document=document,
            contract=contract,
            field_path=f"key_provisions[{index}].text",
            start_char=start + 1,
            end_char=start + 1 + len(quote),
            quoted_text=quote,
        )
    document.extracted_text = source_text
    document.save(update_fields=["extracted_text"])

    with override_settings(
        LLM_ENHANCEMENT_MAX_REQUEST_BYTES=9000,
        LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS=4500,
    ):
        preflight = build_enhancement_preflight(bill)

    assert len(preflight.request_bytes) <= 9000
    assert preflight.estimated_input_tokens <= 4500
    assert preflight.truncated is True
    assert len(preflight.source_snapshot) < 10


@pytest.mark.django_db
def test_large_document_finds_bounded_prefix_without_linear_reserialization(
    monkeypatch,
):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 501A",
        title="Large Fallback Text Act",
        status="introduced",
    )
    chunk_count = 1_000
    text = (("x" * 3_999) + "\n") * chunk_count
    BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        is_active_version=True,
        extracted_text=text,
    )
    real_serializer = source_packet.canonical_json_bytes
    serialization_calls = 0

    def counted_serializer(value):
        nonlocal serialization_calls
        serialization_calls += 1
        return real_serializer(value)

    monkeypatch.setattr(source_packet, "canonical_json_bytes", counted_serializer)

    preflight = build_enhancement_preflight(bill)

    assert preflight.truncated is True
    assert 0 < len(preflight.source_snapshot) < chunk_count
    assert serialization_calls <= 20


@pytest.mark.django_db
def test_preflight_fails_when_fixed_request_overhead_cannot_fit():
    bill = _bill_with_contract_and_evidence()
    with override_settings(
        LLM_ENHANCEMENT_MAX_REQUEST_BYTES=100,
        LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS=50,
    ), pytest.raises(PreflightUnavailable, match="fixed request overhead"):
        build_enhancement_preflight(bill)


@pytest.mark.django_db
def test_preflight_requires_stored_source_text():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 502",
        title="No Text Act",
        status="introduced",
    )

    with pytest.raises(PreflightUnavailable, match="source text"):
        build_enhancement_preflight(bill)


@pytest.mark.django_db
def test_stale_contract_evidence_is_rejected_and_document_offsets_remain_exact():
    bill = _bill_with_contract_and_evidence()
    document = bill.documents.get()
    document.extracted_text = "  \n" + document.extracted_text
    document.save(update_fields=["extracted_text"])

    preflight = build_enhancement_preflight(bill)

    assert preflight.source_manifest["source_kind"] == "document_chunk"
    first = preflight.source_snapshot[0]
    assert first["start_char"] == 3
    assert (
        document.extracted_text[first["start_char"] : first["end_char"]]
        == first["quoted_text"]
    )
