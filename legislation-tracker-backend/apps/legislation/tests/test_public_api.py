import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.congress.models import Representative, Vote, VoteRecord
from apps.legislation import views
from apps.legislation.models import (
    Bill,
    BillContract,
    BillDocument,
    BillSimilarity,
    BillTopic,
    EvidenceSpan,
    Topic,
)


class FakeRemoteStorage:
    def url(self, object_key):
        return f"https://documents.example.com/{object_key}?signature=abc"


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
    assert all(
        item["method"] == "deterministic-v1" for item in response.json()["results"]
    )

    limited = APIClient().get(f"/api/bills/{first.id}/related/?limit=1")
    invalid = APIClient().get(f"/api/bills/{first.id}/related/?limit=not-an-integer")

    assert limited.status_code == 200
    assert [item["bill"]["id"] for item in limited.json()["results"]] == [second.id]
    assert invalid.status_code == 400
    assert "limit" in invalid.json()


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
    monkeypatch.setattr(views, "default_storage", FakeRemoteStorage())

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
def test_public_document_download_streams_filesystem_stored_objects(
    monkeypatch, tmp_path
):
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
def test_public_api_serializes_mixed_v1_and_v2_contract_history():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 109",
        title="Mixed contract history bill",
        status="introduced",
    )
    old_document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        extracted_text="Original source sentence.",
    )
    new_document = BillDocument.objects.create(
        bill=bill,
        version_label="Engrossed",
        extracted_text="The Secretary shall report.",
    )
    old_contract = BillContract.objects.create(
        bill=bill,
        document=old_document,
        schema_version="1.1-deterministic",
        contract_json={
            "schema_version": "1.1-deterministic",
            "plain_summary": "Original source sentence.",
        },
        contract_hash="mixed-old",
    )
    new_contract = BillContract.objects.create(
        bill=bill,
        document=new_document,
        schema_version="2.0-legal-nlp",
        contract_json={
            "schema_version": "2.0-legal-nlp",
            "plain_summary": "The Secretary is required to report.",
        },
        contract_hash="mixed-new",
    )
    EvidenceSpan.objects.create(
        bill=bill,
        document=new_document,
        contract=new_contract,
        field_path="plain_summary",
        start_char=0,
        end_char=len(new_document.extracted_text),
        quoted_text=new_document.extracted_text,
    )
    bill.latest_contract = new_contract
    bill.save(update_fields=["latest_contract"])

    bill_detail = APIClient().get(f"/api/bills/{bill.id}/")
    history = APIClient().get(f"/api/contracts/?bill={bill.id}")

    assert bill_detail.status_code == 200
    latest = bill_detail.json()["latest_contract"]
    assert latest["schema_version"] == "2.0-legal-nlp"
    assert latest["contract_json"]["schema_version"] == latest["schema_version"]
    assert latest["evidence_spans"][0]["quoted_text"] == new_document.extracted_text
    assert history.status_code == 200
    versions = {
        item["id"]: (
            item["schema_version"],
            item["contract_json"]["schema_version"],
        )
        for item in history.json()["results"]
    }
    assert versions == {
        new_contract.id: ("2.0-legal-nlp", "2.0-legal-nlp"),
        old_contract.id: ("1.1-deterministic", "1.1-deterministic"),
    }


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
    assert not any(
        "congress_voterecord" in query["sql"] for query in queries.captured_queries
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("path", "field"),
    [
        ("/api/bills/?id=not-an-integer", "id"),
        ("/api/bills/?session=not-an-integer", "session"),
        ("/api/bills/?congress=not-an-integer", "congress"),
        ("/api/contracts/?bill=not-an-integer", "bill"),
        ("/api/votes/?bill=not-an-integer", "bill"),
        ("/api/votes/?congress=not-an-integer", "congress"),
        ("/api/votes/?session_number=not-an-integer", "session_number"),
        ("/api/votes/?roll_number=not-an-integer", "roll_number"),
        ("/api/votes/?vote_date=not-a-date", "vote_date"),
        ("/api/votes/?chamber=executive", "chamber"),
        ("/api/representatives/?is_current=perhaps", "is_current"),
        ("/api/representatives/?chamber=executive", "chamber"),
    ],
)
def test_public_list_endpoints_reject_invalid_typed_filters(path, field):
    response = APIClient().get(path)

    assert response.status_code == 400
    assert field in response.json()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("path", "field"),
    [
        ("/api/bills/?congres=119", "congres"),
        ("/api/contracts/?bill_id=7", "bill_id"),
        ("/api/votes/?bill_id=7", "bill_id"),
        ("/api/representatives/?state_code=NY", "state_code"),
        ("/api/topics/?topic_id=7", "topic_id"),
        ("/api/documents/?bill=7", "bill"),
    ],
)
def test_public_list_endpoints_reject_unknown_filters(path, field):
    response = APIClient().get(path)

    assert response.status_code == 400
    assert response.json()[field] == ["Unknown query parameter."]


@pytest.mark.django_db
def test_public_paginated_list_accepts_the_declared_page_parameter():
    response = APIClient().get("/api/bills/?page=1")

    assert response.status_code == 200


@pytest.mark.django_db
def test_bill_list_supports_congress_as_a_typed_session_filter():
    matching = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 201",
        title="Matching Congress bill",
        status="introduced",
    )
    Bill.objects.create(
        jurisdiction="federal",
        session=118,
        bill_number="HR 202",
        title="Older Congress bill",
        status="introduced",
    )

    response = APIClient().get("/api/bills/?congress=119")

    assert response.status_code == 200
    assert [bill["id"] for bill in response.json()["results"]] == [matching.id]


@pytest.mark.django_db
def test_vote_list_applies_typed_congress_session_roll_date_and_chamber_filters():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 203",
        title="Filtered vote bill",
        status="introduced",
    )
    matching = Vote.objects.create(
        bill=bill,
        chamber="house",
        session_number=1,
        roll_number=22,
        vote_date="2026-08-20T12:00:00Z",
        result="Passed",
    )
    Vote.objects.create(
        bill=bill,
        chamber="senate",
        session_number=2,
        roll_number=23,
        vote_date="2026-08-21T12:00:00Z",
        result="Failed",
    )

    response = APIClient().get(
        "/api/votes/",
        {
            "congress": "119",
            "session_number": "1",
            "roll_number": "22",
            "vote_date": "2026-08-20",
            "chamber": "house",
        },
    )

    assert response.status_code == 200
    assert [vote["id"] for vote in response.json()["results"]] == [matching.id]


@pytest.mark.django_db
def test_representative_list_applies_typed_boolean_and_chamber_filters():
    matching = Representative.objects.create(
        bioguide_id="R000001",
        name="Current House Representative",
        chamber="house",
        party="Independent",
        state="NY",
        is_current=True,
    )
    Representative.objects.create(
        bioguide_id="R000002",
        name="Former House Representative",
        chamber="house",
        party="Independent",
        state="NY",
        is_current=False,
    )

    response = APIClient().get(
        "/api/representatives/",
        {"is_current": "true", "chamber": "house"},
    )

    assert response.status_code == 200
    assert [representative["id"] for representative in response.json()["results"]] == [
        matching.id
    ]
