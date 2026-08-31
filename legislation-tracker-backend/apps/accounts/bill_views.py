"""Monotonic authenticated bill timeline acknowledgement state."""

from django.db import IntegrityError, transaction

from apps.changelog.cursors import ChangeCursor, strictly_after
from apps.changelog.models import ChangeLog

from .models import BillViewState


def acknowledge_bill_changes(*, user, bill, cursor: ChangeCursor, acknowledged_at):
    if cursor.bill_id != bill.id or cursor.purpose != "acknowledge":
        raise ValueError("Cursor cannot acknowledge this bill.")
    with transaction.atomic():
        if not ChangeLog.objects.filter(
            bill=bill,
            id=cursor.event_id,
            created_at=cursor.created_at,
        ).exists():
            raise ValueError("Cursor does not reference a bill change.")
        state = (
            BillViewState.objects.select_for_update()
            .filter(user=user, bill=bill)
            .first()
        )
        if state is None:
            try:
                state = BillViewState.objects.create(user=user, bill=bill)
            except IntegrityError:
                state = BillViewState.objects.select_for_update().get(user=user, bill=bill)
        current = (
            (state.last_seen_change_created_at, state.last_seen_change_id)
            if state.last_seen_change_created_at is not None
            and state.last_seen_change_id is not None
            else None
        )
        if current is None or cursor.position > current:
            state.last_seen_change_created_at = cursor.created_at
            state.last_seen_change_id = cursor.event_id
            state.last_viewed_at = acknowledged_at
            state.save(
                update_fields=[
                    "last_seen_change_created_at",
                    "last_seen_change_id",
                    "last_viewed_at",
                    "updated_at",
                ]
            )
    return state


def unread_change_count(*, user, bill):
    state = BillViewState.objects.filter(user=user, bill=bill).first()
    if not state or state.last_seen_change_created_at is None or state.last_seen_change_id is None:
        return None
    cursor = ChangeCursor(
        version=1,
        bill_id=bill.id,
        direction="after",
        purpose="acknowledge",
        created_at=state.last_seen_change_created_at,
        event_id=state.last_seen_change_id,
    )
    return ChangeLog.objects.filter(bill=bill).filter(strictly_after(cursor)).count()
