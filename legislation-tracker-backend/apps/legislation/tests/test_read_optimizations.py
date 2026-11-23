import hashlib
import re

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.legislation.models import Bill, BillDocument, BillContract, BillEnhancement

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("count", [1, 20])
def test_bill_list_projects_card_summaries_without_loading_full_payloads(count):
    from apps.legislation.extraction.reader_language import VERSION
    bill = Bill.objects.create(jurisdiction="federal", session=119, bill_number="HR 88", title="College grants")
    doc = BillDocument.objects.create(bill=bill, version_label="Introduced", extracted_text="large " * 10000)
    contract = BillContract.objects.create(bill=bill, document=doc, schema_version="2.1-legal-nlp", contract_json={"large": "x" * 10000}, contract_hash="test",
        reader_copy={"version": VERSION, "contract_hash": "test", "brief": {"summary": "Helps students pay for college."}})
    bill.latest_contract = contract
    bill.save()
    for number in range(1, count):
        other = Bill.objects.create(jurisdiction="federal", session=119, bill_number=f"HR {100 + number}", title="College grants")
        other_doc = BillDocument.objects.create(bill=other, version_label="Introduced", extracted_text="large " * 10000)
        other.latest_contract = BillContract.objects.create(bill=other, document=other_doc, schema_version=contract.schema_version,
            contract_json=contract.contract_json, contract_hash=contract.contract_hash, reader_copy=contract.reader_copy)
        other.save()
    with CaptureQueriesContext(connection) as queries:
        response = APIClient().get("/api/bills/")
    assert response.status_code == 200
    assert any(row["id"] == bill.pk for row in response.data["results"])
    assert all(row["card_summary"] == "Helps students pay for college." for row in response.data["results"])
    # Scalar JSON projections and document metadata joins are needed for cards.
    # Full documents, contracts and reader payloads must not be materialized.
    for query in queries:
        selected = query["sql"].split(" FROM ", 1)[0]
        assert not re.search(r'(?:SELECT |, )"\w+"\."(?:contract_json|reader_copy|raw_text|extracted_text)"(?:,|$)', selected)
    assert len(queries) <= 8  # Same bound for one card or a complete page.


def test_document_digest_changes_even_on_bulk_update():
    bill = Bill.objects.create(jurisdiction="federal", session=119, bill_number="HR 89")
    doc = BillDocument.objects.create(bill=bill, version_label="Introduced", raw_text="raw", extracted_text="parsed")
    doc.refresh_from_db()
    assert doc.reader_text_hash == hashlib.sha256(b"parsed").hexdigest()
    BillDocument.objects.filter(pk=doc.pk).update(extracted_text="")
    doc.refresh_from_db()
    assert doc.reader_text_hash == hashlib.sha256(b"raw").hexdigest()


def test_validation_digest_tracks_bulk_result_and_source_changes():
    bill = Bill.objects.create(jurisdiction="federal", session=119, bill_number="HR 90")
    saved = BillEnhancement.objects.create(bill=bill, result_json={"a": 1}, source_snapshot_json=[])
    saved.refresh_from_db()
    original = saved.validation_digest
    BillEnhancement.objects.filter(pk=saved.pk).update(result_json={"a": 2})
    saved.refresh_from_db()
    assert saved.validation_digest != original
    second = saved.validation_digest
    BillEnhancement.objects.filter(pk=saved.pk).update(source_snapshot_json=[{"quote": "new"}])
    saved.refresh_from_db()
    assert saved.validation_digest != second


def test_search_only_materializes_three_best_chunks_per_bill():
    from django.db.models import F
    from apps.legislation.models import BillSearchChunk
    from apps.legislation.search import top_highlight_chunks
    bills = [Bill.objects.create(jurisdiction="federal", session=119, bill_number=f"HR {n}") for n in (91, 92)]
    for bill in bills:
        BillSearchChunk.objects.bulk_create([
            BillSearchChunk(bill=bill, source_key=f"chunk-{i}", ordinal=i, kind="document", text=f"college {i}") for i in range(100)
        ])
    rows = list(top_highlight_chunks(BillSearchChunk.objects.annotate(_rank=F("ordinal"))))
    assert len(rows) == 6
    for bill in bills:
        assert [r.ordinal for r in rows if r.bill_id == bill.pk] == [99, 98, 97]


def test_shared_lookup_does_not_repeat_source_reads_for_old_results():
    from apps.legislation.enhancements.shared import shared_enhancement
    bill = Bill.objects.create(jurisdiction="federal", session=119, bill_number="HR 93")
    BillDocument.objects.create(bill=bill, version_label="Introduced", is_active_version=True, extracted_text="current")
    BillEnhancement.objects.bulk_create([BillEnhancement(bill=bill, status="succeeded", result_completeness="complete", result_json={"large": "x" * 10000}, source_manifest_json={"document_id": -1}) for _ in range(20)])
    with CaptureQueriesContext(connection) as queries:
        assert shared_enhancement(bill, include_active=False) is None
    assert len(queries) <= 3
    assert not any('"raw_text"' in q["sql"].split(" FROM ")[0] or '"result_json"' in q["sql"].split(" FROM ")[0] for q in queries)


def test_postgres_search_preserves_three_excerpts():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL headline function")
    from django.contrib.postgres.search import SearchVector
    from apps.legislation.models import BillSearchChunk
    from apps.legislation.search import search_bills, BillSearchQuery
    bill = Bill.objects.create(jurisdiction="federal", session=119, bill_number="HR 94")
    BillSearchChunk.objects.bulk_create([BillSearchChunk(bill=bill, kind="document", source_key=f"s{i}", ordinal=i, text=f"College grants support students. Passage number {i}.") for i in range(100)])
    BillSearchChunk.objects.filter(bill=bill).update(search_vector=SearchVector("text", config="english"))
    results = search_bills(queryset=Bill.objects.filter(pk=bill.pk), query=BillSearchQuery(q="college"))
    assert len(results.hits) == 1
    assert len(results.hits[0].highlights) == 3
    assert all(any(segment.matched and segment.text.lower() == "college" for segment in h.segments) for h in results.hits[0].highlights)
