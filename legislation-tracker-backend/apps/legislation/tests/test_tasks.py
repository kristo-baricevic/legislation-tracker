import pytest
from django.db import IntegrityError, transaction

from apps.changelog.models import ChangeLog
from apps.ingestion import tasks as ingestion_tasks
from apps.ingestion.models import IngestionWorkItem
from apps.legislation import tasks
from apps.legislation.extraction.types import EXTRACTOR_VERSION
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


@pytest.fixture(autouse=True)
def prevent_broker_publish(monkeypatch):
    monkeypatch.setattr(ingestion_tasks.dispatch_ingestion_work, "delay", lambda: None)


@pytest.mark.django_db
def test_generate_contract_creates_contract_and_skips_unchanged_document(monkeypatch):
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
        assert (
            document.extracted_text[span.start_char : span.end_char] == span.quoted_text
        )
    assert list(
        IngestionWorkItem.objects.filter(kind="topic_update").values_list(
            "payload_json", flat=True
        )
    ) == [{"contract_id": first["contract_id"]}]

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
    assert IngestionWorkItem.objects.filter(kind="topic_update").count() == 1


@pytest.mark.django_db
def test_generate_contract_persists_v2_and_reuses_unchanged_result():
    source_text = "SEC. 2. REPORTS\nThe Secretary shall publish a report."
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 200",
        title="Federal Reports Act",
        status="Introduced",
        processing_status=ProcessingStatus.PROCESSING,
    )
    document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        is_active_version=True,
        extracted_text=source_text,
        content_hash="v2-source",
    )

    first = tasks.generate_contract(document.id)
    contract = BillContract.objects.get(pk=first["contract_id"])

    assert contract.schema_version == "2.0-legal-nlp"
    assert contract.contract_json["schema_version"] == contract.schema_version
    evidence_count = EvidenceSpan.objects.filter(contract=contract).count()
    assert evidence_count > 0
    for span in EvidenceSpan.objects.filter(contract=contract):
        assert source_text[span.start_char : span.end_char] == span.quoted_text

    second = tasks.generate_contract(document.id)

    assert second["contract_id"] == first["contract_id"]
    assert second["unchanged"] is True
    assert BillContract.objects.count() == 1
    assert ChangeLog.objects.filter(contract=contract).count() == 1
    assert EvidenceSpan.objects.filter(contract=contract).count() == evidence_count


@pytest.mark.django_db
def test_generate_contract_refreshes_evidence_after_a_whitespace_only_source_update():
    original_source = "SEC. 2. REPORTS\nThe Secretary shall publish a report."
    reflowed_source = "SEC. 2. REPORTS\n\nThe Secretary shall publish a report."
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 200A",
        title="Federal Reports Act",
        status="Introduced",
    )
    document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        is_active_version=True,
        extracted_text=original_source,
    )

    first = tasks.generate_contract(document.id)
    contract = BillContract.objects.get(pk=first["contract_id"])
    original_requirement = EvidenceSpan.objects.get(
        contract=contract,
        field_path="requirements[0].display_text",
    )
    document.extracted_text = reflowed_source
    document.save(update_fields=["extracted_text"])

    second = tasks.generate_contract(document.id)

    refreshed_requirement = EvidenceSpan.objects.get(
        contract=contract,
        field_path="requirements[0].display_text",
    )
    assert second["unchanged"] is True
    assert refreshed_requirement.start_char == original_requirement.start_char + 1
    assert (
        reflowed_source[
            refreshed_requirement.start_char : refreshed_requirement.end_char
        ]
        == refreshed_requirement.quoted_text
    )


@pytest.mark.django_db
def test_generate_contract_refreshes_evidence_when_reusing_an_older_hash():
    original_source = "SEC. 2. REPORTS\nThe Secretary shall publish a report."
    reflowed_source = "SEC. 2. REPORTS\n\nThe Secretary shall publish a report."
    intervening_source = "SEC. 2. REPORTS\nThe Secretary shall submit a report."
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 200B",
        title="Federal Reports Act",
        status="Introduced",
    )
    document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        is_active_version=True,
        extracted_text=original_source,
    )

    original = tasks.generate_contract(document.id)
    original_evidence = EvidenceSpan.objects.get(
        contract_id=original["contract_id"],
        field_path="requirements[0].display_text",
    )
    document.extracted_text = intervening_source
    document.save(update_fields=["extracted_text"])
    intervening = tasks.generate_contract(document.id)

    document.extracted_text = reflowed_source
    document.save(update_fields=["extracted_text"])
    reused = tasks.generate_contract(document.id)

    refreshed_evidence = EvidenceSpan.objects.get(
        contract_id=reused["contract_id"],
        field_path="requirements[0].display_text",
    )
    assert intervening["contract_id"] != original["contract_id"]
    assert reused["contract_id"] == original["contract_id"]
    assert refreshed_evidence.start_char == original_evidence.start_char + 1
    assert (
        reflowed_source[refreshed_evidence.start_char : refreshed_evidence.end_char]
        == refreshed_evidence.quoted_text
    )


@pytest.mark.django_db
def test_metadata_contract_generation_remains_legacy():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 201",
        title="Metadata Act",
        summary="Metadata-only summary.",
        status="Introduced",
    )

    result = tasks.generate_contract_for_bill(bill.id)
    contract = BillContract.objects.get(pk=result["contract_id"])

    assert contract.schema_version == "1.1-deterministic"
    assert contract.contract_json["schema_version"] == "1.1-deterministic"


@pytest.mark.django_db
def test_document_contract_work_is_versioned_by_extractor():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 202",
        title="Queued Act",
        status="Introduced",
    )
    document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        extracted_text="SEC. 2. DUTY\nThe Secretary shall report.",
        content_hash="content-hash",
    )

    work = tasks.enqueue_document_contract(document)

    assert work.dedupe_key == f"{document.id}:content-hash:{EXTRACTOR_VERSION}"


@pytest.mark.django_db
def test_unexpected_extraction_error_propagates_for_durable_retry(monkeypatch):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 203",
        title="Retry Act",
        status="Introduced",
    )
    document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        extracted_text="SEC. 2. DUTY\nThe Secretary shall report.",
    )

    monkeypatch.setattr(
        tasks,
        "extract_contract",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("extractor failed")),
    )

    with pytest.raises(RuntimeError, match="extractor failed"):
        tasks._generate_contract_impl(document.id)


@pytest.mark.django_db
def test_generate_contract_builds_structured_contract_with_source_evidence(monkeypatch):
    monkeypatch.setattr(
        tasks.update_topics, "apply_async", lambda args=None, kwargs=None: None
    )
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
        assert source_text[span.start_char : span.end_char] == span.quoted_text
        assert span.quoted_text


@pytest.mark.django_db
def test_contract_evidence_uses_the_actual_repeated_sentence_location(monkeypatch):
    monkeypatch.setattr(
        tasks.update_topics, "apply_async", lambda args=None, kwargs=None: None
    )
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
    monkeypatch.setattr(
        tasks.update_topics, "apply_async", lambda args=None, kwargs=None: None
    )
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
        extracted_text="SEC. 2. DUTY\nThe Secretary shall report.",
    )

    result = tasks.generate_contract(inactive_document.id)

    assert result["contract_id"] != active_contract.id
    assert BillContract.objects.get(pk=result["contract_id"]).schema_version == (
        "2.0-legal-nlp"
    )
    bill.refresh_from_db()
    inactive_document.refresh_from_db()
    assert bill.latest_contract_id == active_contract.id
    assert bill.processing_status == ProcessingStatus.COMPLETE
    assert inactive_document.contract_generated_at is not None
    assert not IngestionWorkItem.objects.filter(kind="topic_update").exists()
    assert not ChangeLog.objects.filter(change_type="contract_update").exists()


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
    assert set(change.new_value["topics"]) == {
        "energy",
        "environment-climate",
        "health",
    }

    second = tasks.update_topics(contract.id)

    assert set(second["topics"]) == {"energy", "environment-climate", "health"}
    assert BillTopic.objects.filter(bill=bill).count() == 3
    assert ChangeLog.objects.filter(change_type="topic_update").count() == 1


@pytest.mark.django_db
def test_update_topics_uses_latest_contract_when_queued_contract_is_stale():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 204",
        title="Versioned program bill",
        summary="",
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
        contract_json={"plain_summary": "Improves Medicare and hospital access."},
        contract_hash="active-health",
    )
    stale_document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        is_active_version=False,
    )
    stale_contract = BillContract.objects.create(
        bill=bill,
        document=stale_document,
        schema_version="1.0-stub",
        contract_json={
            "plain_summary": "Funds renewable energy and climate adaptation."
        },
        contract_hash="stale-climate",
    )
    bill.latest_contract = active_contract
    bill.save(update_fields=["latest_contract"])

    result = tasks.update_topics(stale_contract.id)

    assert result["contract_id"] == active_contract.id
    assert set(result["topics"]) == {"health"}
    assert set(
        BillTopic.objects.filter(bill=bill).values_list("topic__slug", flat=True)
    ) == {"health"}


@pytest.mark.django_db
def test_update_topics_abandons_a_contract_superseded_while_matching(monkeypatch):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 205",
        title="Versioned program bill",
        summary="",
        status="Introduced",
    )
    older_document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        is_active_version=True,
    )
    older_contract = BillContract.objects.create(
        bill=bill,
        document=older_document,
        schema_version="1.0-stub",
        contract_json={"plain_summary": "Funds renewable energy."},
        contract_hash="older-energy",
    )
    newer_document = BillDocument.objects.create(
        bill=bill,
        version_label="Engrossed",
        is_active_version=True,
    )
    newer_contract = BillContract.objects.create(
        bill=bill,
        document=newer_document,
        schema_version="1.0-stub",
        contract_json={"plain_summary": "Improves Medicare and hospital access."},
        contract_hash="newer-health",
    )
    bill.latest_contract = older_contract
    bill.save(update_fields=["latest_contract"])

    def supersede_during_matching(*, bill, contract):
        assert contract.id == older_contract.id
        bill.latest_contract = newer_contract
        bill.save(update_fields=["latest_contract"])
        return [("energy", 1.0)]

    monkeypatch.setattr(tasks, "infer_topic_matches", supersede_during_matching)

    result = tasks.update_topics(older_contract.id)

    assert result == {
        "contract_id": older_contract.id,
        "bill_id": bill.id,
        "skipped": True,
        "reason": "superseded",
    }
    assert not BillTopic.objects.filter(bill=bill).exists()
    assert not ChangeLog.objects.filter(change_type="topic_update").exists()


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
    result = tasks.update_topics(bill_id=bill.id)

    assert result["bill_id"] == bill.id
    assert result["contract_id"] is None
    assert "health" in result["topics"]
    assert list(
        IngestionWorkItem.objects.filter(kind="similarity").values_list(
            "payload_json", flat=True
        )
    ) == [{"bill_id": bill.id}]


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
    result = tasks.backfill_update_topics(session=119)

    assert result == {"enqueued": 1, "session": 119}
    assert list(
        IngestionWorkItem.objects.filter(kind="topic_update").values_list(
            "payload_json", flat=True
        )
    ) == [{"contract_id": latest_contract.id}]
    assert old_contract.id not in [
        item["contract_id"]
        for item in IngestionWorkItem.objects.filter(kind="topic_update").values_list(
            "payload_json", flat=True
        )
    ]
    assert other_contract.id not in [
        item["contract_id"]
        for item in IngestionWorkItem.objects.filter(kind="topic_update").values_list(
            "payload_json", flat=True
        )
    ]


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
    tasks.backfill_update_topics(session=119)

    assert list(
        IngestionWorkItem.objects.filter(kind="topic_update").values_list(
            "payload_json", flat=True
        )
    ) == [{"contract_id": active_contract.id}]


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
    result = tasks.recompute_similarity_batch(session=119)

    assert result == {"enqueued": 2, "session": 119}
    assert list(
        IngestionWorkItem.objects.filter(kind="similarity")
        .order_by("payload_json__bill_id")
        .values_list("payload_json", flat=True)
    ) == [{"bill_id": first.id}, {"bill_id": second.id}]


@pytest.mark.django_db
def test_recompute_similarity_batch_resolves_current_congress_at_execution(monkeypatch):
    current = Bill.objects.create(
        jurisdiction="federal",
        session=121,
        bill_number="HR 1",
        title="Current bill",
        status="Introduced",
    )
    Bill.objects.create(
        jurisdiction="federal",
        session=120,
        bill_number="HR 2",
        title="Historical bill",
        status="Introduced",
    )
    monkeypatch.setattr(tasks, "current_congress", lambda: 121)

    result = tasks.recompute_similarity_batch(session=None)

    assert result == {"enqueued": 1, "session": 121}
    assert IngestionWorkItem.objects.get(kind="similarity").payload_json == {
        "bill_id": current.id
    }
