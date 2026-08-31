from __future__ import annotations

from copy import deepcopy

from django.db import transaction

from apps.changelog.models import BillActivityClock, ChangeLog
from apps.legislation.models import Bill, BillContract, BillDocument


def lock_bill_activity(*, bill_id: int) -> tuple[Bill, BillActivityClock]:
    """Acquire the bill row before the shared activity clock.

    Several ingestion paths update a bill before recording its activity.  This
    order prevents those paths from forming a cycle with the global clock.
    """
    locked_bill = Bill.objects.select_for_update().get(pk=bill_id)
    BillActivityClock.objects.get_or_create(pk=1, defaults={"committed_sequence": 0})
    clock = BillActivityClock.objects.select_for_update().get(pk=1)
    return locked_bill, clock


def record_bill_change(
    *,
    bill: Bill,
    change_type: str,
    new_value: dict,
    old_value: dict | None = None,
    event_key: str | None = None,
    document: BillDocument | None = None,
    contract: BillContract | None = None,
) -> ChangeLog:
    """Create one idempotent bill event and advance canonical activity state."""
    if new_value is None:
        raise ValueError("new_value is required")
    if not isinstance(new_value, dict):
        raise ValueError("new_value must be a dictionary")

    payload = deepcopy(new_value)

    with transaction.atomic():
        # Test databases and pre-migration operational restores can lack the
        # seeded singleton. Ensuring it after locking the bill preserves the
        # canonical bill-then-clock order while making the service self-healing.
        locked_bill, clock = lock_bill_activity(bill_id=bill.pk)

        if event_key:
            existing = ChangeLog.objects.filter(
                bill=locked_bill,
                change_type=change_type,
                event_key=event_key,
            ).first()
            if existing is not None:
                return existing

        next_sequence = clock.committed_sequence + 1
        event = ChangeLog.objects.create(
            bill=locked_bill,
            document=document,
            contract=contract,
            change_type=change_type,
            event_key=event_key,
            old_value=old_value,
            new_value=payload,
        )

        locked_bill.last_activity_at = max(
            value
            for value in (locked_bill.last_activity_at, event.created_at)
            if value is not None
        )
        locked_bill.last_activity_sequence = next_sequence
        locked_bill.save(update_fields=["last_activity_at", "last_activity_sequence"])
        clock.committed_sequence = next_sequence
        clock.save(update_fields=["committed_sequence"])
        return event
