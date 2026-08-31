import pytest

from apps.congress.models import Representative
from apps.legislation.models import Bill, BillContract, BillDocument, BillTopic, Topic


@pytest.mark.django_db
def test_search_projection_chunks_active_document_and_is_idempotent():
    from apps.legislation.search_index import rebuild_bill_search_index

    sponsor = Representative.objects.create(
        bioguide_id="S000001",
        name="Ada Sponsor",
        chamber="house",
        party="Independent",
        state="NY",
    )
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 901",
        title="Rural Hospital Support Act",
        summary="Expands rural hospital support.",
        status="Introduced",
        sponsor=sponsor,
    )
    topic = Topic.objects.create(name="Health", slug="health")
    BillTopic.objects.create(bill=bill, topic=topic, confidence_score=0.9)
    BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        extracted_text="obsolete private draft language",
        is_active_version=False,
    )
    active = BillDocument.objects.create(
        bill=bill,
        version_label="Engrossed",
        extracted_text="Rural hospitals receive grants.\n\nThe Secretary reports yearly.",
        is_active_version=True,
    )
    contract = BillContract.objects.create(
        bill=bill,
        document=active,
        contract_hash="contract-index-1",
        contract_json={"plain_summary": "Creates grants", "requirements": [{"actor": "Secretary", "action": "report"}]},
    )
    bill.latest_contract = contract
    bill.save(update_fields=["latest_contract"])

    first = rebuild_bill_search_index(bill_id=bill.id)
    second = rebuild_bill_search_index(bill_id=bill.id)

    from apps.legislation.models import BillSearchChunk

    chunks = list(BillSearchChunk.objects.filter(bill=bill).order_by("kind", "ordinal"))
    assert first.changed is True
    assert second.changed is False
    assert {chunk.kind for chunk in chunks} == {"metadata", "contract", "document"}
    assert any("Ada Sponsor" in chunk.text and "Health" in chunk.text for chunk in chunks)
    assert any(chunk.document_id == active.id for chunk in chunks if chunk.kind == "document")
    assert all("obsolete private draft" not in chunk.text for chunk in chunks)


def test_chunk_search_text_preserves_paragraphs_and_bounds_oversized_paragraphs():
    from apps.legislation.search_index import chunk_search_text

    chunks = chunk_search_text("alpha\n\nbeta\n\n" + ("x" * 25), max_chars=10)

    assert chunks[:2] == ["alpha", "beta"]
    assert "".join(chunks[2:]) == "x" * 25
    assert all(len(chunk) <= 10 for chunk in chunks)
