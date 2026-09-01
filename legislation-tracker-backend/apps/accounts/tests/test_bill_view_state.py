from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest
from django.db import close_old_connections, connection

from apps.accounts.bill_views import acknowledge_bill_changes
from apps.accounts.models import BillViewState, User
from apps.changelog.cursors import ChangeCursor
from apps.changelog.models import ChangeLog
from apps.legislation.models import Bill

POSTGRESQL_ONLY = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="requires PostgreSQL row locking"
)


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


@POSTGRESQL_ONLY
@pytest.mark.django_db(transaction=True)
def test_concurrent_first_acknowledgements_create_one_monotonic_state():
    user = User.objects.create_user(
        username="concurrent-viewer@example.test",
        email="concurrent-viewer@example.test",
        password="safe-password-123",
    )
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 907",
        title="Concurrent view state bill",
        status="Introduced",
    )
    events = [
        ChangeLog.objects.create(
            bill=bill,
            change_type="status_update",
            new_value={"position": position},
        )
        for position in ("first", "second")
    ]
    cursors = [
        ChangeCursor(
            version=1,
            bill_id=bill.id,
            direction="after",
            purpose="acknowledge",
            created_at=event.created_at,
            event_id=event.id,
        )
        for event in events
    ]
    barrier = Barrier(2)

    def acknowledge(cursor):
        close_old_connections()
        try:
            thread_user = User.objects.get(pk=user.id)
            thread_bill = Bill.objects.get(pk=bill.id)
            barrier.wait()
            acknowledge_bill_changes(
                user=thread_user,
                bill=thread_bill,
                cursor=cursor,
                acknowledged_at=datetime(2026, 1, 4, tzinfo=UTC),
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(acknowledge, cursor) for cursor in cursors]
        for future in futures:
            future.result(timeout=10)

    state = BillViewState.objects.get(user=user, bill=bill)
    assert state.last_seen_change_id == events[-1].id
    assert BillViewState.objects.filter(user=user, bill=bill).count() == 1
