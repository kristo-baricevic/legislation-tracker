import hashlib
import re

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.legislation.models import Bill, BillContract, BillDocument, BillEnhancement

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("count", [1, 20])
def test_bill_list_projects_card_summaries_without_loading_full_payloads(count):
    from apps.legislation.extraction.reader_language import VERSION

    bill = Bill.objects.create(
        jurisdiction="federal", session=119, bill_number="HR 88", title="College grants"
    )
    doc = BillDocument.objects.create(
        bill=bill, version_label="Introduced", extracted_text="large " * 10000
    )
    contract = BillContract.objects.create(
        bill=bill,
        document=doc,
        schema_version="2.1-legal-nlp",
        contract_json={"large": "x" * 10000},
        contract_hash="test",
        reader_copy={
            "version": VERSION,
            "contract_hash": "test",
            "brief": {"summary": "Helps students pay for college."},
        },
    )
    bill.latest_contract = contract
    bill.save()
    for number in range(1, count):
        other = Bill.objects.create(
            jurisdiction="federal",
            session=119,
            bill_number=f"HR {100 + number}",
            title="College grants",
        )
        other_doc = BillDocument.objects.create(
            bill=other, version_label="Introduced", extracted_text="large " * 10000
        )
        other.latest_contract = BillContract.objects.create(
            bill=other,
            document=other_doc,
            schema_version=contract.schema_version,
            contract_json=contract.contract_json,
            contract_hash=contract.contract_hash,
            reader_copy=contract.reader_copy,
        )
        other.save()
    with CaptureQueriesContext(connection) as queries:
        response = APIClient().get("/api/bills/")
    assert response.status_code == 200
    assert any(row["id"] == bill.pk for row in response.data["results"])
    assert all(
        row["card_summary"] == "Helps students pay for college."
        for row in response.data["results"]
    )
    # Scalar JSON projections and document metadata joins are needed for cards.
    # Full documents, contracts and reader payloads must not be materialized.
    for query in queries:
        selected = query["sql"].split(" FROM ", 1)[0]
        assert not re.search(
            r'(?:SELECT |, )"\w+"\."(?:contract_json|reader_copy|raw_text|extracted_text)"(?:,|$)',
            selected,
        )
    assert len(queries) <= 8  # Same bound for one card or a complete page.


def test_document_digest_changes_even_on_bulk_update():
    bill = Bill.objects.create(jurisdiction="federal", session=119, bill_number="HR 89")
    doc = BillDocument.objects.create(
        bill=bill, version_label="Introduced", raw_text="raw", extracted_text="parsed"
    )
    doc.refresh_from_db()
    assert doc.reader_text_hash == hashlib.sha256(b"parsed").hexdigest()
    BillDocument.objects.filter(pk=doc.pk).update(extracted_text="")
    doc.refresh_from_db()
    assert doc.reader_text_hash == hashlib.sha256(b"raw").hexdigest()


def test_validation_digest_tracks_bulk_result_and_source_changes():
    bill = Bill.objects.create(jurisdiction="federal", session=119, bill_number="HR 90")
    saved = BillEnhancement.objects.create(
        bill=bill, result_json={"a": 1}, source_snapshot_json=[]
    )
    saved.refresh_from_db()
    original = saved.validation_digest
    BillEnhancement.objects.filter(pk=saved.pk).update(result_json={"a": 2})
    saved.refresh_from_db()
    assert saved.validation_digest != original
    second = saved.validation_digest
    BillEnhancement.objects.filter(pk=saved.pk).update(
        source_snapshot_json=[{"quote": "new"}]
    )
    saved.refresh_from_db()
    assert saved.validation_digest != second


def test_search_only_materializes_three_best_chunks_per_bill():
    from django.db.models import F

    from apps.legislation.models import BillSearchChunk
    from apps.legislation.search import top_highlight_chunks

    bills = [
        Bill.objects.create(jurisdiction="federal", session=119, bill_number=f"HR {n}")
        for n in (91, 92)
    ]
    for bill in bills:
        BillSearchChunk.objects.bulk_create(
            [
                BillSearchChunk(
                    bill=bill,
                    source_key=f"chunk-{i}",
                    ordinal=i,
                    kind="document",
                    text=f"college {i}",
                )
                for i in range(100)
            ]
        )
    rows = list(
        top_highlight_chunks(BillSearchChunk.objects.annotate(_rank=F("ordinal")))
    )
    assert len(rows) == 6
    for bill in bills:
        assert [r.ordinal for r in rows if r.bill_id == bill.pk] == [99, 98, 97]


def test_shared_lookup_does_not_repeat_source_reads_for_old_results():
    from apps.legislation.enhancements.shared import shared_enhancement

    bill = Bill.objects.create(jurisdiction="federal", session=119, bill_number="HR 93")
    BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        is_active_version=True,
        extracted_text="current",
    )
    BillEnhancement.objects.bulk_create(
        [
            BillEnhancement(
                bill=bill,
                status="succeeded",
                result_completeness="complete",
                result_json={"large": "x" * 10000},
                source_manifest_json={"document_id": -1},
            )
            for _ in range(20)
        ]
    )
    with CaptureQueriesContext(connection) as queries:
        assert shared_enhancement(bill, include_active=False) is None
    assert len(queries) <= 3
    assert not any(
        '"raw_text"' in q["sql"].split(" FROM ")[0]
        or '"result_json"' in q["sql"].split(" FROM ")[0]
        for q in queries
    )


def test_postgres_search_preserves_three_excerpts():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL headline function")
    from django.contrib.postgres.search import SearchVector

    from apps.legislation.models import BillSearchChunk
    from apps.legislation.search import BillSearchQuery, search_bills

    bill = Bill.objects.create(jurisdiction="federal", session=119, bill_number="HR 94")
    BillSearchChunk.objects.bulk_create(
        [
            BillSearchChunk(
                bill=bill,
                kind="document",
                source_key=f"s{i}",
                ordinal=i,
                text=f"College grants support students. Passage number {i}.",
            )
            for i in range(100)
        ]
    )
    BillSearchChunk.objects.filter(bill=bill).update(
        search_vector=SearchVector("text", config="english")
    )
    results = search_bills(
        queryset=Bill.objects.filter(pk=bill.pk), query=BillSearchQuery(q="college")
    )
    assert len(results.hits) == 1
    assert len(results.hits[0].highlights) == 3
    assert all(
        any(
            segment.matched and segment.text.lower() == "college"
            for segment in h.segments
        )
        for h in results.hits[0].highlights
    )


@pytest.mark.parametrize("count", [1, 6, 20])
@pytest.mark.parametrize("schema", ["1.3", "2.0-source-first"])
def test_enhanced_card_reads_are_batched(count, schema):
    from apps.accounts.dashboard_bill_cards import add_card_summaries
    from apps.legislation.enhancements.shared import validation_key
    from apps.legislation.enhancements.source_graph import document_fingerprint
    from apps.legislation.models import BillProcessingCache

    rows = []
    for n in range(count):
        bill = Bill.objects.create(
            jurisdiction="federal", session=119, bill_number=f"S {n}"
        )
        doc = BillDocument.objects.create(
            bill=bill, version_label="IH", raw_text="Bill text", is_active_version=True
        )
        saved = BillEnhancement.objects.create(
            bill=bill,
            status="succeeded",
            result_completeness="complete",
            output_schema_version=schema,
            source_fingerprint=document_fingerprint(
                str(doc.pk), "IH", doc.reader_text_hash, ()
            ),
            source_manifest_json={
                "document_id": doc.pk,
                "document_content_hash": doc.reader_text_hash,
                "source_kind": "pinned_passages",
                "document_version_label": "IH",
            },
            result_json=(
                {"synopsis": {"text": f"Saved summary {n}"}}
                if schema == "2.0-source-first"
                else {"summary": [{"text": f"Saved summary {n}"}]}
            ),
        )
        BillProcessingCache.objects.create(
            pk=validation_key(saved),
            kind="reader-validation",
            result_json={"valid": True, "preview": f"Saved summary {n}"},
        )
        rows.append({"bill": {"id": bill.pk}})
    with CaptureQueriesContext(connection) as queries:
        add_card_summaries(rows)
    assert [row["bill"]["card_summary"] for row in rows] == [
        f"Saved summary {n}" for n in range(count)
    ]
    assert len(queries) <= 7
    print(f"{count} enhanced cards: {len(queries)} summary queries")


@pytest.mark.parametrize("other_result", ["stale", "partial"])
def test_resolved_card_history_is_never_loaded_when_another_card_has_no_result(
    other_result,
    monkeypatch,
):
    from datetime import timedelta

    from apps.accounts.dashboard_bill_cards import add_card_summaries
    from apps.legislation.enhancements.shared import validation_key
    from apps.legislation.models import BillProcessingCache

    def make_bill(number):
        bill = Bill.objects.create(
            jurisdiction="federal", session=119, bill_number=number, summary="Original"
        )
        doc = BillDocument.objects.create(
            bill=bill, raw_text="Bill text", is_active_version=True
        )
        return bill, {
            "document_id": doc.pk,
            "document_content_hash": doc.reader_text_hash,
        }

    first, first_manifest = make_bill("S 1")
    second, second_manifest = make_bill("S 2")
    output = {"summary": [{"text": "Enhanced"}]}
    current = BillEnhancement.objects.create(
        bill=first,
        status="succeeded",
        result_completeness="complete",
        output_schema_version="1.3",
        source_fingerprint="current",
        source_manifest_json=first_manifest,
        result_json=output,
    )
    BillProcessingCache.objects.create(
        pk=validation_key(current),
        kind="reader-validation",
        result_json={"valid": True, "preview": "Enhanced"},
    )
    if other_result == "stale":
        second_manifest["document_content_hash"] = "old"
    BillEnhancement.objects.create(
        bill=second,
        status="succeeded",
        result_completeness="partial" if other_result == "partial" else "complete",
        output_schema_version="1.3",
        source_fingerprint="other",
        source_manifest_json=second_manifest,
        result_json=output,
    )

    loaded = []
    from_db = BillEnhancement.from_db

    def record_load(*args):
        row = from_db(*args)
        loaded.append(row.pk)
        return row

    monkeypatch.setattr(BillEnhancement, "from_db", record_load)

    def read_cards():
        loaded.clear()
        rows = [{"bill": {"id": bill.pk}} for bill in (first, second)]
        with CaptureQueriesContext(connection) as queries:
            add_card_summaries(rows)
        assert [
            (r["bill"]["card_summary"], r["bill"]["enhancement_id"]) for r in rows
        ] == [("Enhanced", current.pk), ("Original", None)]
        return len(queries), set(loaded)

    baseline = read_cards()
    BillEnhancement.objects.bulk_create(
        [
            BillEnhancement(
                bill=first,
                status="succeeded",
                result_completeness="complete",
                output_schema_version="1.3",
                source_fingerprint=f"old-{i}",
                source_manifest_json=first_manifest,
                result_json=output,
            )
            for i in range(1024)
        ]
    )
    BillEnhancement.objects.filter(bill=first).exclude(pk=current.pk).update(
        created_at=current.created_at - timedelta(days=1)
    )
    assert read_cards() == baseline


def test_card_search_advances_past_stale_result_to_older_success_before_running():
    from apps.accounts.dashboard_bill_cards import add_card_summaries
    from apps.legislation.enhancements.shared import validation_key
    from apps.legislation.models import BillProcessingCache

    bill = Bill.objects.create(jurisdiction="federal", session=119, bill_number="S 4")
    doc = BillDocument.objects.create(
        bill=bill, raw_text="Bill text", is_active_version=True
    )
    manifest = {"document_id": doc.pk, "document_content_hash": doc.reader_text_hash}

    def candidate(status, fingerprint, source):
        return BillEnhancement.objects.create(
            bill=bill,
            status=status,
            source_fingerprint=fingerprint,
            output_schema_version="1.3",
            source_manifest_json=source,
            result_json={"summary": [{"text": "Saved"}]},
        )

    saved = candidate("succeeded", "compatible", manifest)
    BillProcessingCache.objects.create(
        pk=validation_key(saved), kind="reader-validation", result_json={"valid": True}
    )
    stale = candidate(
        "succeeded", "stale", {**manifest, "document_content_hash": "old"}
    )
    BillEnhancement.objects.filter(pk=stale.pk).update(created_at=saved.created_at)
    active = candidate("running", "active", manifest)
    candidate("pending", "pending", manifest)
    rows = [{"bill": {"id": bill.pk}}]
    add_card_summaries(rows)
    assert rows[0]["bill"]["enhancement_id"] == saved.pk
    saved.delete()
    add_card_summaries(rows)
    assert rows[0]["bill"]["enhancement_id"] == active.pk


@pytest.mark.parametrize("rejection", ["stale", "cached_invalid"])
def test_unresolved_card_checks_rejected_history_in_batches(rejection):
    from apps.accounts.dashboard_bill_cards import add_card_summaries
    from apps.legislation.enhancements.shared import validation_key
    from apps.legislation.models import BillProcessingCache

    cards = []
    for number in ("S 8", "S 9"):
        bill = Bill.objects.create(
            jurisdiction="federal", session=119, bill_number=number
        )
        doc = BillDocument.objects.create(
            bill=bill, raw_text="Bill text", is_active_version=True
        )
        manifest = {
            "document_id": doc.pk,
            "document_content_hash": doc.reader_text_hash,
        }
        fields = dict(
            bill=bill,
            status="succeeded",
            output_schema_version="1.3",
            result_json={"summary": [{"text": number}]},
            source_manifest_json=manifest,
        )
        saved = BillEnhancement.objects.create(**fields, source_fingerprint=number)
        BillProcessingCache.objects.create(
            pk=validation_key(saved),
            kind="reader-validation",
            result_json={"valid": True},
        )
        cards.append((bill, saved))

    if rejection == "stale":
        fields["source_manifest_json"] = {
            **manifest,
            "document_content_hash": "obsolete",
        }
    BillEnhancement.objects.bulk_create(
        [
            BillEnhancement(**fields, source_fingerprint=f"rejected-{i}")
            for i in range(256)
        ]
    )
    if rejection == "cached_invalid":
        rejected = BillEnhancement.objects.filter(bill=bill).exclude(pk=saved.pk)
        BillProcessingCache.objects.bulk_create(
            [
                BillProcessingCache(
                    pk=validation_key(row),
                    kind="reader-validation",
                    result_json={"valid": False},
                )
                for row in rejected
            ]
        )
    rows = [{"bill": {"id": bill.pk}} for bill, _ in cards]
    with CaptureQueriesContext(connection) as queries:
        add_card_summaries(rows)
    assert [row["bill"]["enhancement_id"] for row in rows] == [
        saved.pk for _, saved in cards
    ]
    print(f"{rejection}: {len(queries)} queries for 256 rejected results")
    assert len(queries) <= 16


def test_document_metadata_projection_avoids_transferring_stored_text():
    bill = Bill.objects.create(jurisdiction="federal", session=119, bill_number="HR 88")
    text = "Bill provision " * 37000
    assert len(text.encode()) * 2 * 5 == 5_550_000
    for n in range(5):
        BillDocument.objects.create(
            bill=bill, version_label=str(n), raw_text=text, extracted_text=text
        )
    bill.latest_contract = BillContract.objects.create(
        bill=bill,
        document=bill.documents.first(),
        schema_version="1.1",
        contract_json={"plain_summary": "Published summary."},
        contract_hash="published",
    )
    bill.save(update_fields=["latest_contract"])
    response = APIClient().get(f"/api/bills/{bill.pk}/?contract_view=summary")
    assert len(response.data["documents"]) == 5
    assert all(doc["text_url"] for doc in response.data["documents"])
    from apps.legislation.views import BillViewSet

    view = BillViewSet()
    view.action = "retrieve"
    from rest_framework.request import Request
    from rest_framework.test import APIRequestFactory

    view.request = Request(APIRequestFactory().get("/", {"contract_view": "summary"}))
    loaded = view.get_queryset().get(pk=bill.pk)
    assert {
        "raw_text",
        "extracted_text",
    } <= loaded.latest_contract.document.get_deferred_fields()
    docs = list(loaded.documents.all())
    assert all(
        {"raw_text", "extracted_text"} <= doc.get_deferred_fields()
        and doc.fallback_text is None
        for doc in docs
    )


def test_document_backfill_restores_digest_after_bulk_edit_and_can_resume():
    from importlib import import_module
    from types import SimpleNamespace

    from django.apps import apps

    bill = Bill.objects.create(
        jurisdiction="federal", session=119, bill_number="S 1000"
    )
    document = BillDocument.objects.create(
        bill=bill, version_label="IH", raw_text="First version."
    )
    BillDocument.objects.filter(pk=document.pk).update(
        extracted_text="Amended version."
    )
    url = f"/api/bills/{bill.pk}/?contract_view=summary"
    client = APIClient()
    assert (
        client.get(url).data["documents"][0]["reader_summary"]
        == "Bill text: Amended version."
    )
    backfill = import_module(
        "apps.legislation.migrations.0039_backfill_document_summaries"
    ).backfill
    editor = SimpleNamespace(connection=connection)
    backfill(apps, editor)
    document.refresh_from_db()
    assert document.summary_text_hash == document.reader_text_hash
    assert document.stored_text_summary == "Bill text: Amended version."
    with CaptureQueriesContext(connection) as queries:
        backfill(apps, editor)
    assert not any(q["sql"].startswith("UPDATE") for q in queries)
