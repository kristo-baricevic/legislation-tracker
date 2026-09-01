import pytest
from django.db import connection

from apps.changelog.models import BillActivityClock, ChangeLog
from apps.legislation.models import Bill


def make_bill(*, number="HR 9001"):
    return Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number=number,
        title="Activity test bill",
        status="Introduced",
    )


@pytest.mark.django_db(transaction=True)
def test_record_bill_change_advances_canonical_activity_once_for_event_key():
    from apps.changelog.services import record_bill_change

    bill = make_bill()

    first = record_bill_change(
        bill=bill,
        change_type="status_update",
        new_value={"status": "Reported"},
        event_key="bill:status:reported",
    )
    duplicate = record_bill_change(
        bill=bill,
        change_type="status_update",
        new_value={"status": "Reported"},
        event_key="bill:status:reported",
    )

    bill.refresh_from_db()
    assert duplicate.pk == first.pk
    assert ChangeLog.objects.filter(bill=bill).count() == 1
    assert bill.last_activity_at == first.created_at
    assert bill.last_activity_sequence == 1


@pytest.mark.django_db(transaction=True)
def test_record_bill_change_locks_bill_before_global_activity_clock():
    """Avoid the bill-to-clock / clock-to-bill deadlock cycle."""
    from apps.changelog.services import record_bill_change

    BillActivityClock.objects.get_or_create(pk=1, defaults={"committed_sequence": 0})
    observed_tables = []

    class LockQueryRecorder:
        def __call__(self, execute, sql, params, many, context):
            normalized_sql = sql.casefold()
            if "select" in normalized_sql:
                if "legislation_bill" in normalized_sql:
                    observed_tables.append("bill")
                elif "changelog_billactivityclock" in normalized_sql:
                    observed_tables.append("activity_clock")
            return execute(sql, params, many, context)

    with connection.execute_wrapper(LockQueryRecorder()):
        record_bill_change(
            bill=make_bill(number="HR 9003"),
            change_type="status_update",
            new_value={"status": "Reported"},
            event_key="bill:status:reported",
        )

    assert observed_tables.index("bill") < observed_tables.index("activity_clock")


@pytest.mark.django_db
def test_record_bill_change_requires_a_non_null_payload():
    from apps.changelog.services import record_bill_change

    with pytest.raises(ValueError, match="new_value"):
        record_bill_change(
            bill=make_bill(number="HR 9002"),
            change_type="status_update",
            new_value=None,
        )
