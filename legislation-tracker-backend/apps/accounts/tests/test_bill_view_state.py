from datetime import UTC, datetime

import pytest

from apps.accounts.bill_views import acknowledge_bill_changes
from apps.accounts.models import User
from apps.changelog.cursors import ChangeCursor
from apps.changelog.models import ChangeLog
from apps.legislation.models import Bill


@pytest.mark.django_db
def test_bill_view_acknowledgement_is_user_scoped_and_monotonic():
    user = User.objects.create_user(
        username="viewer@example.test",
        email="viewer@example.test",
        password="safe-password-123",
    )
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 906",
        title="View state bill",
        status="Introduced",
    )
    first = ChangeLog.objects.create(
        bill=bill,
        change_type="status_update",
        new_value={"status": "Reported"},
    )
    second = ChangeLog.objects.create(
        bill=bill,
        change_type="title_update",
        new_value={"title": "Updated"},
    )
    newest = ChangeCursor(
        version=1,
        bill_id=bill.id,
        direction="after",
        purpose="acknowledge",
        created_at=second.created_at,
        event_id=second.id,
    )
    oldest = ChangeCursor(
        version=1,
        bill_id=bill.id,
        direction="after",
        purpose="acknowledge",
        created_at=first.created_at,
        event_id=first.id,
    )

    acknowledged = acknowledge_bill_changes(
        user=user,
        bill=bill,
        cursor=newest,
        acknowledged_at=datetime(2026, 1, 3, tzinfo=UTC),
    )
    acknowledged = acknowledge_bill_changes(
        user=user,
        bill=bill,
        cursor=oldest,
        acknowledged_at=datetime(2026, 1, 4, tzinfo=UTC),
    )

    assert acknowledged.last_seen_change_id == second.id
