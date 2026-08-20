from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.ingestion import tasks as ingestion_tasks
from apps.ingestion.models import IngestionWorkItem
from apps.legislation.models import Bill, BillDocument


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
def test_backfill_contracts_execute_is_durable_and_idempotent(monkeypatch):
    document = make_document(number=307)
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
