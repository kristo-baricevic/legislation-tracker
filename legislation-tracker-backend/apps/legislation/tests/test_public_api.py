import pytest
from rest_framework.test import APIClient

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
