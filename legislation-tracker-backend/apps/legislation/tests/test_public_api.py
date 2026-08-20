import pytest
from django.db import connection
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.congress.models import Vote, VoteRecord
from apps.legislation import views
from apps.congress.models import Representative
from apps.legislation.models import (
    Bill,
    BillContract,
    BillDocument,
    BillSimilarity,
    BillTopic,
    EvidenceSpan,
    Topic,
)


@pytest.mark.django_db
def test_public_corpus_endpoints_ignore_stale_bearer_token():
    representative = Representative.objects.create(
        bioguide_id="A000001",
        name="Public Representative",
        chamber="house",
        party="Independent",
        state="NY",
    )
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 100",
        title="Public corpus bill",
        status="introduced",
        sponsor=representative,
    )
    topic = Topic.objects.create(name="Health", slug="health")
    BillTopic.objects.create(bill=bill, topic=topic, confidence_score=0.9)

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer stale.invalid.token")

    responses = [
        client.get("/api/bills/"),
        client.get(f"/api/bills/{bill.id}/"),
        client.get("/api/bills/filter-options/"),
        client.get("/api/topics/"),
        client.get("/api/representatives/"),
    ]

    assert [response.status_code for response in responses] == [200, 200, 200, 200, 200]


@pytest.mark.django_db
def test_related_bills_endpoint_returns_similarity_ranked_public_results():
    first = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 100",
        title="Rural health grants",
        status="introduced",
    )
    second = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="S 101",
        title="Rural hospital grants",
        status="introduced",
    )
    third = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 102",
        title="Public health workforce",
        status="introduced",
    )
    BillSimilarity.objects.create(
        bill_a=first,
        bill_b=second,
        method="deterministic-v1",
        similarity_score=0.91,
    )
    BillSimilarity.objects.create(
        bill_a=first,
        bill_b=third,
        method="deterministic-v1",
        similarity_score=0.42,
    )

    response = APIClient().get(f"/api/bills/{first.id}/related/")

    assert response.status_code == 200
    assert [item["bill"]["id"] for item in response.json()["results"]] == [
        second.id,
        third.id,
    ]
    assert [item["similarity_score"] for item in response.json()["results"]] == [
        0.91,
        0.42,
    ]
    assert all(item["method"] == "deterministic-v1" for item in response.json()["results"])


@pytest.mark.django_db
def test_bill_detail_exposes_evidence_span_offsets():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 103",
        title="Evidence bill",
        status="introduced",
    )
    document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        is_active_version=True,
        extracted_text="This bill creates a grant program.",
    )
    contract = BillContract.objects.create(
        bill=bill,
        document=document,
        schema_version="1.1-deterministic",
        contract_json={"plain_summary": "This bill creates a grant program."},
        contract_hash="hash",
    )
    bill.latest_contract = contract
    bill.save(update_fields=["latest_contract"])
    EvidenceSpan.objects.create(
        bill=bill,
        document=document,
        contract=contract,
        field_path="plain_summary",
        start_char=0,
        end_char=34,
        quoted_text="This bill creates a grant program.",
    )

    response = APIClient().get(f"/api/bills/{bill.id}/")

    assert response.status_code == 200
    evidence = response.json()["latest_contract"]["evidence_spans"][0]
    assert evidence["field_path"] == "plain_summary"
    assert evidence["start_char"] == 0
    assert evidence["end_char"] == 34
    assert evidence["quoted_text"] == "This bill creates a grant program."


@pytest.mark.django_db
def test_public_document_download_uses_the_stored_object_url(monkeypatch):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 104",
        title="Stored document bill",
        status="introduced",
    )
    document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        object_storage_key="bills/119/HR_104/Introduced.pdf",
        content_type="application/pdf",
        file_size_bytes=123,
    )
    monkeypatch.setattr(
        views.default_storage,
        "url",
        lambda object_key: f"https://documents.example.com/{object_key}?signature=abc",
    )

    response = APIClient().get(f"/api/documents/{document.id}/download/")
    detail = APIClient().get(f"/api/bills/{bill.id}/")

    assert response.status_code == 302
    assert response["Location"] == (
        "https://documents.example.com/bills/119/HR_104/Introduced.pdf?signature=abc"
    )
    assert detail.json()["documents"] == [
        {
            "id": document.id,
            "version_label": "Introduced",
            "is_active_version": False,
            "content_type": "application/pdf",
            "file_size_bytes": 123,
            "source_url": None,
            "downloaded_at": None,
            "download_url": f"/api/documents/{document.id}/download/",
            "text_url": None,
        }
    ]


@pytest.mark.django_db
def test_public_document_download_streams_filesystem_stored_objects(monkeypatch, tmp_path):
    storage = FileSystemStorage(location=tmp_path, base_url="/media/")
    object_key = "bills/119/HR_104/Introduced.pdf"
    storage.save(object_key, ContentFile(b"stored bill bytes"))
    monkeypatch.setattr(views, "default_storage", storage)
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 108",
        title="Filesystem stored document bill",
        status="introduced",
    )
    document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        object_storage_key=object_key,
        content_type="application/pdf",
    )

    response = APIClient().get(f"/api/documents/{document.id}/download/")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert b"".join(response.streaming_content) == b"stored bill bytes"


@pytest.mark.django_db
def test_public_document_text_endpoint_serves_extracted_or_raw_text():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 105",
        title="Text document bill",
        status="introduced",
    )
    document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        extracted_text="An accessible plain-text bill version.",
    )

    response = APIClient().get(f"/api/documents/{document.id}/text/")

    assert response.status_code == 200
    assert response.json() == {"text": "An accessible plain-text bill version."}


@pytest.mark.django_db
def test_contract_history_list_and_detail_are_public_and_filtered_by_bill():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 106",
        title="Contract history bill",
        status="introduced",
    )
    document = BillDocument.objects.create(bill=bill, version_label="Introduced")
    older = BillContract.objects.create(
        bill=bill,
        document=document,
        schema_version="1.0",
        contract_json={"plain_summary": "Original summary"},
        contract_hash="old-contract",
    )
    latest = BillContract.objects.create(
        bill=bill,
        document=None,
        schema_version="1.1",
        contract_json={"plain_summary": "Updated summary"},
        contract_hash="new-contract",
    )

    response = APIClient().get(f"/api/contracts/?bill={bill.id}")
    detail = APIClient().get(f"/api/contracts/{latest.id}/")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["results"]] == [latest.id, older.id]
    assert response.json()["results"][1]["document_version_label"] == "Introduced"
    assert detail.status_code == 200
    assert detail.json()["contract_json"] == {"plain_summary": "Updated summary"}


@pytest.mark.django_db
def test_vote_list_and_detail_include_member_positions_for_a_bill():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 107",
        title="Vote history bill",
        status="introduced",
    )
    representative = Representative.objects.create(
        bioguide_id="V000001",
        name="Voting Representative",
        chamber="house",
        party="Independent",
        state="NY",
    )
    vote = Vote.objects.create(
        bill=bill,
        chamber="house",
        session_number=1,
        roll_number=17,
        vote_date="2026-08-19T12:00:00Z",
        result="Passed",
        yeas=220,
        nays=210,
    )
    VoteRecord.objects.create(vote=vote, representative=representative, position="yes")

    response = APIClient().get(f"/api/votes/?bill={bill.id}")
    detail = APIClient().get(f"/api/votes/{vote.id}/")

    assert response.status_code == 200
    assert response.json()["results"] == [
        {
            "id": vote.id,
            "bill": bill.id,
            "chamber": "house",
            "session_number": 1,
            "roll_number": 17,
            "vote_date": "2026-08-19T12:00:00Z",
            "result": "Passed",
            "yeas": 220,
            "nays": 210,
        }
    ]
    assert detail.status_code == 200
    assert detail.json()["records"] == [
        {
            "representative": {
                "id": representative.id,
                "bioguide_id": "V000001",
                "name": "Voting Representative",
                "chamber": "house",
                "party": "Independent",
                "state": "NY",
                "district": None,
                "first_name": "",
                "last_name": "",
                "official_website_url": None,
                "image_url": None,
                "is_current": True,
            },
            "position": "yes",
        }
    ]


@pytest.mark.django_db
def test_vote_list_does_not_query_member_positions():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 108",
        title="Vote list bill",
        status="introduced",
    )
    representative = Representative.objects.create(
        bioguide_id="V000002",
        name="List Representative",
        chamber="house",
        party="Independent",
        state="NY",
    )
    vote = Vote.objects.create(
        bill=bill,
        chamber="house",
        roll_number=18,
        vote_date="2026-08-20T12:00:00Z",
        result="Passed",
    )
    VoteRecord.objects.create(vote=vote, representative=representative, position="yes")

    with CaptureQueriesContext(connection) as queries:
        response = APIClient().get(f"/api/votes/?bill={bill.id}")

    assert response.status_code == 200
    assert not any("congress_voterecord" in query["sql"] for query in queries.captured_queries)
