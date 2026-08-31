from __future__ import annotations

from copy import deepcopy

from django.db import transaction

from apps.changelog.models import BillActivityClock, ChangeLog
from apps.legislation.models import Bill, BillContract, BillDocument


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
        clock = BillActivityClock.objects.select_for_update().get(pk=1)
        locked_bill = Bill.objects.select_for_update().get(pk=bill.pk)

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
