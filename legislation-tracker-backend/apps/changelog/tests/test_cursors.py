from datetime import UTC, datetime

import pytest

from apps.changelog.cursors import (
    ChangeCursor,
    ChangeCursorValidationError,
    decode_change_cursor,
    encode_change_cursor,
)


def test_change_cursor_round_trip_binds_bill_direction_and_purpose():
    cursor = ChangeCursor(
        version=1,
        bill_id=9,
        direction="after",
        purpose="acknowledge",
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
        event_id=7,
    )

    decoded = decode_change_cursor(
        encode_change_cursor(cursor),
        expected_bill_id=9,
        allowed_purposes=frozenset({"acknowledge"}),
        allowed_directions=frozenset({"after"}),
    )

    assert decoded == cursor


def test_change_cursor_rejects_wrong_bill_and_tampering():
    cursor = ChangeCursor(
        version=1,
        bill_id=9,
        direction="before",
        purpose="browse",
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
        event_id=7,
    )
    value = encode_change_cursor(cursor)

    with pytest.raises(ChangeCursorValidationError):
        decode_change_cursor(
            value,
            expected_bill_id=10,
            allowed_purposes=frozenset({"browse"}),
            allowed_directions=frozenset({"before"}),
        )
    with pytest.raises(ChangeCursorValidationError):
        decode_change_cursor(
            value + "tampered",
            expected_bill_id=9,
            allowed_purposes=frozenset({"browse"}),
            allowed_directions=frozenset({"before"}),
        )
