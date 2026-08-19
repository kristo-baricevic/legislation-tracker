import pytest
from django.db import IntegrityError, transaction

from apps.changelog.models import ChangeLog
from apps.legislation.models import (
    Bill,
    BillContract,
    BillDocument,
    BillSimilarity,
    BillTopic,
    EvidenceSpan,
    ProcessingStatus,
    Topic,
)
from apps.legislation import tasks


@pytest.mark.django_db
def test_generate_contract_creates_contract_and_skips_unchanged_document(monkeypatch):
    enqueued_topics = []
    enqueued_similarity = []
    monkeypatch.setattr(
        tasks.update_topics,
        "apply_async",
        lambda args=None, kwargs=None: enqueued_topics.append((args, kwargs)),
    )
    monkeypatch.setattr(
        tasks.schedule_similarity_for_bill,
        "apply_async",
        lambda args=None, kwargs=None: enqueued_similarity.append((args, kwargs)),
    )

    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 2",
        title="Test bill",
        status="Introduced",
        processing_status=ProcessingStatus.PROCESSING,
    )
    document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        is_active_version=True,
        source_url="https://example.test/hr2.xml",
        extracted_text="Section 1. This bill creates a pilot program.",
    )

    first = tasks.generate_contract(document.id)

    contract = BillContract.objects.get()
    assert first["contract_id"] == contract.id
    bill.refresh_from_db()
    document.refresh_from_db()
    assert bill.latest_contract_id == first["contract_id"]
    assert bill.processing_status == ProcessingStatus.COMPLETE
    assert document.contract_generated_at is not None
    assert ChangeLog.objects.filter(change_type="contract_update").count() == 1
    spans = EvidenceSpan.objects.filter(contract_id=first["contract_id"])
    assert spans.count() > 0
    for span in spans:
        assert document.extracted_text[span.start_char:span.end_char] == span.quoted_text
    assert enqueued_topics == [([first["contract_id"]], None)]
    assert enqueued_similarity == []

    second = tasks.generate_contract(document.id)

    assert second == {
        "document_id": document.id,
        "contract_id": first["contract_id"],
        "unchanged": True,
    }
    assert BillContract.objects.count() == 1
    assert ChangeLog.objects.filter(change_type="contract_update").count() == 1
    document.refresh_from_db()
    assert document.contract_generated_at is not None
    assert enqueued_topics == [
        ([first["contract_id"]], None),
        ([first["contract_id"]], None),
    ]
    assert enqueued_similarity == []


@pytest.mark.django_db
def test_generate_contract_builds_structured_contract_with_source_evidence(monkeypatch):
    monkeypatch.setattr(tasks.update_topics, "apply_async", lambda args=None, kwargs=None: None)
    monkeypatch.setattr(
        tasks.schedule_similarity_for_bill,
        "apply_async",
        lambda args=None, kwargs=None: None,
    )
    source_text = (
        "Section 1. The Secretary of Health and Human Services shall award grants "
        "to rural hospitals. The grants may be used to purchase telehealth equipment. "
        "There is authorized to be appropriated $25,000,000 for fiscal year 2027. "
        "This Act takes effect 90 days after enactment."
    )
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 60",
        title="Rural Health Grants Act",
        status="Introduced",
        processing_status=ProcessingStatus.PROCESSING,
    )
    document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        is_active_version=True,
        source_url="https://example.test/hr60.xml",
        extracted_text=source_text,
    )

    result = tasks.generate_contract(document.id)

    contract = BillContract.objects.get(pk=result["contract_id"])
    contract_json = contract.contract_json
    assert contract.schema_version == tasks.CONTRACT_SCHEMA_VERSION
    assert contract_json["schema_version"] == tasks.CONTRACT_SCHEMA_VERSION
    assert contract_json["summary"]["text"] == (
        "The Secretary of Health and Human Services shall award grants to rural hospitals."
    )
    assert contract_json["key_points"][0]["text"] == contract_json["summary"]["text"]
    assert contract_json["requirements"][0]["text"] == contract_json["summary"]["text"]
    assert contract_json["funding_mentions"][0]["text"] == (
        "There is authorized to be appropriated $25,000,000 for fiscal year 2027."
    )
    assert contract_json["effective_dates"][0]["text"] == (
        "This Act takes effect 90 days after enactment."
    )

    spans = list(EvidenceSpan.objects.filter(contract=contract).order_by("field_path"))
    field_paths = {span.field_path for span in spans}
    assert {
        "summary.text",
        "key_points[0].text",
        "requirements[0].text",
        "funding_mentions[0].text",
        "effective_dates[0].text",
        "source_excerpt",
    }.issubset(field_paths)
    for span in spans:
        assert source_text[span.start_char:span.end_char] == span.quoted_text
        assert span.quoted_text


@pytest.mark.django_db
def test_contract_evidence_uses_the_actual_repeated_sentence_location(monkeypatch):
    monkeypatch.setattr(tasks.update_topics, "apply_async", lambda args=None, kwargs=None: None)
    monkeypatch.setattr(
        tasks.schedule_similarity_for_bill,
        "apply_async",
        lambda args=None, kwargs=None: None,
    )
    source_text = "The agency must publish a report. The agency must publish a report."
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 62",
        title="Reporting bill",
        status="Introduced",
    )
    document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        is_active_version=True,
        extracted_text=source_text,
    )

    result = tasks.generate_contract(document.id)

    second_requirement = EvidenceSpan.objects.get(
        contract_id=result["contract_id"],
        field_path="requirements[1].text",
    )
    assert second_requirement.start_char == source_text.rfind(
        "The agency must publish a report."
    )


@pytest.mark.django_db
def test_generate_contract_for_inactive_document_does_not_replace_latest_contract(
    monkeypatch,
):
    monkeypatch.setattr(tasks.update_topics, "apply_async", lambda args=None, kwargs=None: None)
    monkeypatch.setattr(
        tasks.schedule_similarity_for_bill,
        "apply_async",
        lambda args=None, kwargs=None: None,
    )
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 61",
        title="Versioned bill",
        status="Introduced",
        processing_status=ProcessingStatus.COMPLETE,
    )
    active_document = BillDocument.objects.create(
        bill=bill,
        version_label="Engrossed",
        is_active_version=True,
        extracted_text="This active version controls.",
    )
    active_contract = BillContract.objects.create(
        bill=bill,
        document=active_document,
        schema_version=tasks.CONTRACT_SCHEMA_VERSION,
        contract_json={"plain_summary": "active"},
        contract_hash="active",
    )
    bill.latest_contract = active_contract
    bill.save(update_fields=["latest_contract"])
    inactive_document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        is_active_version=False,
        extracted_text="This older introduced version is not active.",
    )

    result = tasks.generate_contract(inactive_document.id)

    assert result["contract_id"] != active_contract.id
    bill.refresh_from_db()
    inactive_document.refresh_from_db()
    assert bill.latest_contract_id == active_contract.id
    assert bill.processing_status == ProcessingStatus.COMPLETE
    assert inactive_document.contract_generated_at is not None


@pytest.mark.django_db
def test_update_topics_infers_bill_topics_and_is_idempotent(monkeypatch):
    monkeypatch.setattr(
        tasks.schedule_similarity_for_bill,
        "apply_async",
        lambda args=None, kwargs=None: None,
    )
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 50",
        title="Health and climate resilience bill",
        summary="Improves hospital preparedness and clean energy infrastructure.",
        status="Introduced",
    )
    document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        is_active_version=True,
        extracted_text="",
    )
    contract = BillContract.objects.create(
        bill=bill,
        document=document,
        schema_version="1.0-stub",
        contract_json={
            "title": bill.title,
            "plain_summary": (
                "This Act funds Medicare access, public health programs, "
                "renewable energy, and climate adaptation."
            ),
            "source_excerpt": "Hospitals and clean energy projects are eligible.",
        },
        contract_hash="abc123",
    )

    first = tasks.update_topics(contract.id)

    assert first["bill_id"] == bill.id
    assert set(first["topics"]) == {"energy", "environment-climate", "health"}
    assert set(Topic.objects.values_list("slug", flat=True)) == {
        "energy",
        "environment-climate",
        "health",
    }
    assert set(
        BillTopic.objects.filter(bill=bill).values_list("topic__slug", flat=True)
    ) == {"energy", "environment-climate", "health"}
    assert ChangeLog.objects.filter(change_type="topic_update").count() == 1
    change = ChangeLog.objects.get(change_type="topic_update")
    assert change.old_value == {"topics": []}
    assert set(change.new_value["topics"]) == {"energy", "environment-climate", "health"}

    second = tasks.update_topics(contract.id)

    assert set(second["topics"]) == {"energy", "environment-climate", "health"}
    assert BillTopic.objects.filter(bill=bill).count() == 3
    assert ChangeLog.objects.filter(change_type="topic_update").count() == 1


@pytest.mark.django_db
def test_update_topics_handles_a_bill_without_a_contract_and_then_updates_similarity(
    monkeypatch,
):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 53",
        title="Health care access bill",
        summary="Improves hospital care and Medicare access.",
        status="Introduced",
    )
    enqueued = []
    monkeypatch.setattr(
        tasks.schedule_similarity_for_bill,
        "apply_async",
        lambda args=None, kwargs=None: enqueued.append((args, kwargs)),
    )

    result = tasks.update_topics(bill_id=bill.id)

    assert result["bill_id"] == bill.id
    assert result["contract_id"] is None
    assert "health" in result["topics"]
    assert enqueued == [([bill.id], None)]


@pytest.mark.django_db
def test_backfill_update_topics_enqueues_latest_contracts(monkeypatch):
    first_bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 51",
        title="Health bill",
        status="Introduced",
    )
    first_document = BillDocument.objects.create(
        bill=first_bill,
        version_label="Introduced",
        is_active_version=True,
    )
    old_contract = BillContract.objects.create(
        bill=first_bill,
        document=first_document,
        schema_version="1.0-stub",
        contract_json={"plain_summary": "old"},
        contract_hash="old",
    )
    latest_contract = BillContract.objects.create(
        bill=first_bill,
        document=first_document,
        schema_version="1.0-stub",
        contract_json={"plain_summary": "latest"},
        contract_hash="latest",
    )
    first_bill.latest_contract = latest_contract
    first_bill.save(update_fields=["latest_contract"])
    second_bill = Bill.objects.create(
        jurisdiction="federal",
        session=118,
        bill_number="S 52",
        title="Climate bill",
        status="Introduced",
    )
    second_document = BillDocument.objects.create(
        bill=second_bill,
        version_label="Introduced",
        is_active_version=True,
    )
    other_contract = BillContract.objects.create(
        bill=second_bill,
        document=second_document,
        schema_version="1.0-stub",
        contract_json={"plain_summary": "other"},
        contract_hash="other",
    )
    enqueued = []
    monkeypatch.setattr(
        tasks.update_topics,
        "apply_async",
        lambda args=None, kwargs=None: enqueued.append((args, kwargs)),
    )

    result = tasks.backfill_update_topics(session=119)

    assert result == {"enqueued": 1, "session": 119}
    assert enqueued == [([latest_contract.id], None)]
    assert old_contract.id not in [args[0] for args, _kwargs in enqueued]
    assert other_contract.id not in [args[0] for args, _kwargs in enqueued]


@pytest.mark.django_db
def test_backfill_update_topics_uses_the_selected_latest_contract_not_highest_id(
    monkeypatch,
):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 54",
        title="Versioned bill",
        status="Introduced",
    )
    active_document = BillDocument.objects.create(
        bill=bill,
        version_label="Engrossed",
        is_active_version=True,
    )
    active_contract = BillContract.objects.create(
        bill=bill,
        document=active_document,
        schema_version="1.0-stub",
        contract_json={"plain_summary": "active"},
        contract_hash="active",
    )
    inactive_document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        is_active_version=False,
    )
    BillContract.objects.create(
        bill=bill,
        document=inactive_document,
        schema_version="1.0-stub",
        contract_json={"plain_summary": "obsolete"},
        contract_hash="obsolete",
    )
    bill.latest_contract = active_contract
    bill.save(update_fields=["latest_contract"])
    enqueued = []
    monkeypatch.setattr(
        tasks.update_topics,
        "apply_async",
        lambda args=None, kwargs=None: enqueued.append((args, kwargs)),
    )

    tasks.backfill_update_topics(session=119)

    assert enqueued == [([active_contract.id], None)]


@pytest.mark.django_db
def test_contract_and_topic_rows_have_database_uniqueness_guarantees():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 55",
        title="Unique bill",
        status="Introduced",
    )
    document = BillDocument.objects.create(bill=bill, version_label="Introduced")
    topic = Topic.objects.create(name="Health", slug="health")
    BillContract.objects.create(
        bill=bill,
        document=document,
        schema_version="1.0-stub",
        contract_json={},
        contract_hash="same-document-hash",
    )
    BillTopic.objects.create(bill=bill, topic=topic)

    with pytest.raises(IntegrityError), transaction.atomic():
        BillContract.objects.create(
            bill=bill,
            document=document,
            schema_version="1.0-stub",
            contract_json={},
            contract_hash="same-document-hash",
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        BillTopic.objects.create(bill=bill, topic=topic)


@pytest.mark.django_db
def test_schedule_similarity_for_bill_recomputes_related_pairs():
    health = Topic.objects.create(name="Health", slug="health")
    climate = Topic.objects.create(name="Climate", slug="climate")
    source = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 70",
        title="Rural Health Grant Act",
        summary="Creates grants for rural hospitals and public health programs.",
        status="Introduced",
    )
    related = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="S 71",
        title="Rural Hospital Grant Program",
        summary="Authorizes grants for rural hospitals and telehealth equipment.",
        status="Introduced",
    )
    unrelated = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 72",
        title="Coastal Climate Resilience Act",
        summary="Funds coastal climate adaptation and emissions reduction.",
        status="Introduced",
    )
    BillTopic.objects.create(bill=source, topic=health)
    BillTopic.objects.create(bill=related, topic=health)
    BillTopic.objects.create(bill=unrelated, topic=climate)

    result = tasks.schedule_similarity_for_bill(source.id)

    assert result["bill_id"] == source.id
    assert result["computed"] == 1
    similarity = BillSimilarity.objects.get()
    assert similarity.method == tasks.SIMILARITY_METHOD
    assert similarity.bill_a_id == min(source.id, related.id)
    assert similarity.bill_b_id == max(source.id, related.id)
    assert similarity.similarity_score > 0.2

    unrelated_pair_exists = BillSimilarity.objects.filter(
        bill_a_id=min(source.id, unrelated.id),
        bill_b_id=max(source.id, unrelated.id),
    ).exists()
    assert unrelated_pair_exists is False


@pytest.mark.django_db
def test_recompute_similarity_batch_enqueues_all_bills(monkeypatch):
    first = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 73",
        title="First bill",
        status="Introduced",
    )
    second = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="S 74",
        title="Second bill",
        status="Introduced",
    )
    enqueued = []
    monkeypatch.setattr(
        tasks.schedule_similarity_for_bill,
        "apply_async",
        lambda args=None, kwargs=None: enqueued.append((args, kwargs)),
    )

    result = tasks.recompute_similarity_batch(session=119)

    assert result == {"enqueued": 2, "session": 119}
    assert enqueued == [([first.id], None), ([second.id], None)]
