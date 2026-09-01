from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.test import override_settings

from apps.ingestion import tasks as ingestion_tasks
from apps.ingestion.models import IngestionWorkItem
from apps.legislation.models import Bill, BillContract, BillDocument


def make_document(*, number, session=119, active=True):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=session,
        bill_number=f"HR {number}",
        title=f"Bill {number}",
        status="Introduced",
    )
    return BillDocument.objects.create(
        bill=bill,
        version_label="Introduced" if active else "Reported",
        is_active_version=active,
        extracted_text="SEC. 2. DUTY\nThe Secretary shall report.",
        content_hash=f"hash-{number}",
    )


def make_existing_contract(document, *, suffix="existing"):
    contract = BillContract.objects.create(
        bill=document.bill,
        document=document,
        schema_version="2.0-legal-nlp",
        contract_json={"schema_version": "2.0-legal-nlp"},
        contract_hash=f"{suffix}-{document.id}",
    )
    if document.is_active_version:
        document.bill.latest_contract = contract
        document.bill.save(update_fields=["latest_contract"])
    return contract


@pytest.mark.django_db
@pytest.mark.parametrize(
    "arguments",
    [
        (),
        ("--start-id", "10", "--end-id", "5"),
        ("--limit", "0"),
        ("--limit", "-1"),
    ],
)
def test_backfill_contracts_rejects_unsafe_selectors(arguments):
    with pytest.raises(CommandError):
        call_command("backfill_contracts", *arguments)


@pytest.mark.django_db
def test_backfill_contracts_previews_active_documents_in_stable_bounded_order():
    first = make_document(number=301, session=118, active=True)
    make_document(number=302, session=119, active=False)
    third = make_document(number=303, session=119, active=True)
    make_document(number=304, session=119, active=True)
    output = StringIO()

    call_command(
        "backfill_contracts",
        "--session",
        "119",
        "--start-id",
        str(first.id),
        "--end-id",
        str(third.id),
        "--limit",
        "1",
        stdout=output,
    )

    rendered = output.getvalue()
    assert "selected=1" in rendered
    assert f"min_id={third.id}" in rendered
    assert f"max_id={third.id}" in rendered
    assert "sessions=119:1" in rendered
    assert "active=1 inactive=0" in rendered
    assert "target_schema=2.1-legal-nlp" in rendered
    assert "target_extractor=federal-rules-2.1.0" in rendered
    assert "generation_reason=schema_backfill" in rendered
    assert "writer_enabled=false" in rendered
    assert "Preview only; pass --execute to enqueue." in rendered
    assert not IngestionWorkItem.objects.exists()


@pytest.mark.django_db
def test_backfill_contracts_all_versions_includes_inactive_documents():
    active = make_document(number=305, active=True)
    inactive = make_document(number=306, active=False)
    output = StringIO()

    call_command(
        "backfill_contracts",
        "--start-id",
        str(active.id),
        "--end-id",
        str(inactive.id),
        "--all-versions",
        stdout=output,
    )

    assert "selected=2" in output.getvalue()
    assert "active=1 inactive=1" in output.getvalue()
    assert not IngestionWorkItem.objects.exists()


@pytest.mark.django_db(transaction=True)
@override_settings(LEGAL_NLP_V21_WRITE_ENABLED=True)
def test_backfill_contracts_execute_is_durable_and_idempotent(monkeypatch):
    document = make_document(number=307)
    make_existing_contract(document)
    broker_observations = []
    monkeypatch.setattr(
        ingestion_tasks.dispatch_ingestion_work,
        "delay",
        lambda: broker_observations.append(IngestionWorkItem.objects.count()),
    )

    first_output = StringIO()
    call_command(
        "backfill_contracts",
        "--start-id",
        str(document.id),
        "--end-id",
        str(document.id),
        "--execute",
        stdout=first_output,
    )
    second_output = StringIO()
    call_command(
        "backfill_contracts",
        "--start-id",
        str(document.id),
        "--end-id",
        str(document.id),
        "--execute",
        stdout=second_output,
    )

    assert broker_observations == [1, 1]
    assert IngestionWorkItem.objects.filter(kind="document_contract").count() == 1
    assert "selected=1" in first_output.getvalue()
    assert "enqueued=1" in first_output.getvalue()
    assert "selected=1" in second_output.getvalue()
    assert "enqueued=1" in second_output.getvalue()


@pytest.mark.django_db(transaction=True)
@override_settings(LEGAL_NLP_V21_WRITE_ENABLED=True)
def test_backfill_contracts_reextracts_pre_v2_xml_before_generating_contract(
    monkeypatch,
):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 308",
        title="Reports Act",
        status="Introduced",
    )
    document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        is_active_version=True,
        source_url="https://example.test/hr308.xml",
        content_type="application/xml",
        content_hash="legacy-xml",
        extracted_text=(
            "<bill><legis-body><section><enum>2.</enum><header>Reports</header>"
            "<text>The Secretary shall publish a report.</text>"
            "</section></legis-body></bill>"
        ),
    )
    existing_contract = BillContract.objects.create(
        bill=bill,
        document=document,
        schema_version="2.0-legal-nlp",
        contract_json={"schema_version": "2.0-legal-nlp"},
        contract_hash="legacy-xml-contract",
    )
    bill.latest_contract = existing_contract
    bill.save(update_fields=["latest_contract"])
    monkeypatch.setattr(ingestion_tasks.dispatch_ingestion_work, "delay", lambda: None)

    call_command(
        "backfill_contracts",
        "--start-id",
        str(document.id),
        "--end-id",
        str(document.id),
        "--execute",
    )

    work = IngestionWorkItem.objects.get(kind="document_contract")
    assert work.payload_json == {
        "document_id": document.id,
        "reextract_source": True,
        "generation_reason": "schema_backfill",
        "extractor_version": "federal-rules-2.1.0",
        "generation_occurrence": document.created_at.isoformat(),
    }

    result = ingestion_tasks._process_durable_work(work)

    document.refresh_from_db()
    bill.refresh_from_db()
    assert result["contract_id"] == bill.latest_contract_id
    assert bill.latest_contract.schema_version == "2.1-legal-nlp"
    assert document.extracted_text == (
        "SEC. 2. Reports\nThe Secretary shall publish a report."
    )


@pytest.mark.django_db(transaction=True)
@override_settings(LEGAL_NLP_V21_WRITE_ENABLED=False)
def test_backfill_contracts_refuses_execute_before_creating_durable_work():
    document = make_document(number=309)

    with pytest.raises(CommandError, match="LEGAL_NLP_V21_WRITE_ENABLED"):
        call_command(
            "backfill_contracts",
            "--start-id",
            str(document.id),
            "--end-id",
            str(document.id),
            "--execute",
        )

    assert not IngestionWorkItem.objects.exists()


@pytest.mark.django_db
@override_settings(LEGAL_NLP_V21_WRITE_ENABLED=True)
def test_backfill_contracts_requires_a_bounded_execute_batch():
    document = make_document(number=310)
    make_existing_contract(document)

    with pytest.raises(CommandError, match="bounded"):
        call_command("backfill_contracts", "--session", "119", "--execute")

    assert not IngestionWorkItem.objects.exists()


@pytest.mark.django_db
def test_backfill_contracts_preview_reports_eligible_and_ineligible_documents():
    eligible = make_document(number=311)
    make_existing_contract(eligible)
    ineligible = make_document(number=312)
    output = StringIO()

    call_command(
        "backfill_contracts",
        "--start-id",
        str(eligible.id),
        "--end-id",
        str(ineligible.id),
        stdout=output,
    )

    assert "selected=2" in output.getvalue()
    assert "eligible=1 ineligible=1" in output.getvalue()
    assert not IngestionWorkItem.objects.exists()


@pytest.mark.django_db(transaction=True)
@override_settings(LEGAL_NLP_V21_WRITE_ENABLED=True)
def test_backfill_contracts_execute_excludes_documents_without_prior_contract(
    monkeypatch,
):
    eligible = make_document(number=313)
    make_existing_contract(eligible)
    ineligible = make_document(number=314)
    monkeypatch.setattr(ingestion_tasks.dispatch_ingestion_work, "delay", lambda: None)
    output = StringIO()

    call_command(
        "backfill_contracts",
        "--start-id",
        str(eligible.id),
        "--end-id",
        str(ineligible.id),
        "--execute",
        stdout=output,
    )

    work = IngestionWorkItem.objects.get(kind="document_contract")
    assert work.payload_json["document_id"] == eligible.id
    assert "enqueued=1 skipped_ineligible=1" in output.getvalue()
