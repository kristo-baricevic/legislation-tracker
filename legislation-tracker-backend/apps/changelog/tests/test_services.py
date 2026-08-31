import pytest

from apps.changelog.models import ChangeLog
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


@pytest.mark.django_db
def test_record_bill_change_requires_a_non_null_payload():
    from apps.changelog.services import record_bill_change

    with pytest.raises(ValueError, match="new_value"):
        record_bill_change(
            bill=make_bill(number="HR 9002"),
            change_type="status_update",
            new_value=None,
        )
