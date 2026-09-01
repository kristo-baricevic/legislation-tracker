"""Signed, bill-bound keyset cursors for the canonical change stream."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from django.core import signing
from django.db.models import Q

CURSOR_SALT = "changelog.bill-timeline.cursor"
CURSOR_VERSION = 1


class ChangeCursorValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ChangeCursor:
    version: int
    bill_id: int
    direction: Literal["after", "before", "head"]
    purpose: Literal["acknowledge", "browse", "stream_head"]
    created_at: datetime
    event_id: int

    @property
    def position(self) -> tuple[datetime, int]:
        return self.created_at, self.event_id


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ChangeCursorValidationError("Cursor timestamp must include timezone.")
    return value.astimezone(UTC)


def encode_change_cursor(cursor: ChangeCursor) -> str:
    return signing.dumps(
        {
            "v": cursor.version,
            "b": cursor.bill_id,
            "d": cursor.direction,
            "p": cursor.purpose,
            "t": _utc(cursor.created_at).isoformat(),
            "i": cursor.event_id,
        },
        salt=CURSOR_SALT,
        compress=True,
    )


def decode_change_cursor(
    value: str,
    *,
    expected_bill_id: int,
    allowed_purposes: frozenset[str],
    allowed_directions: frozenset[str],
) -> ChangeCursor:
    try:
        payload = signing.loads(value, salt=CURSOR_SALT)
        if not isinstance(payload, dict) or payload.get("v") != CURSOR_VERSION:
            raise ChangeCursorValidationError("Unsupported change cursor.")
        cursor = ChangeCursor(
            version=payload["v"],
            bill_id=payload["b"],
            direction=payload["d"],
            purpose=payload["p"],
            created_at=_utc(datetime.fromisoformat(payload["t"])),
            event_id=payload["i"],
        )
        if not isinstance(cursor.bill_id, int) or not isinstance(cursor.event_id, int):
            raise ChangeCursorValidationError("Invalid change cursor identifiers.")
        if cursor.bill_id != expected_bill_id:
            raise ChangeCursorValidationError("Change cursor belongs to another bill.")
        if cursor.purpose not in allowed_purposes or cursor.direction not in allowed_directions:
            raise ChangeCursorValidationError("Change cursor cannot be used here.")
        return cursor
    except (KeyError, TypeError, ValueError, signing.BadSignature) as exc:
        if isinstance(exc, ChangeCursorValidationError):
            raise
        raise ChangeCursorValidationError("Invalid change cursor.") from exc


def strictly_after(cursor: ChangeCursor) -> Q:
    return Q(created_at__gt=cursor.created_at) | Q(
        created_at=cursor.created_at, id__gt=cursor.event_id
    )


def strictly_before(cursor: ChangeCursor) -> Q:
    return Q(created_at__lt=cursor.created_at) | Q(
        created_at=cursor.created_at, id__lt=cursor.event_id
    )
