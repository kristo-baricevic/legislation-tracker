"""Canonical bill-change event construction and safe public serialization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class BillMetadataSnapshot:
    title: str
    summary: str | None
    status: str
    sponsor_id: int | None
    introduced_at: date | None
    last_action_at: datetime | None


@dataclass(frozen=True)
class PendingBillChange:
    change_type: str
    old_value: dict | None
    new_value: dict
    event_key: str


def snapshot_bill_metadata(bill) -> BillMetadataSnapshot:
    return BillMetadataSnapshot(
        title=bill.title,
        summary=bill.summary,
        status=bill.status,
        sponsor_id=bill.sponsor_id,
        introduced_at=bill.introduced_at,
        last_action_at=bill.last_action_at,
    )


def _json_value(value):
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def diff_bill_metadata(
    before: BillMetadataSnapshot, after: BillMetadataSnapshot
) -> tuple[PendingBillChange, ...]:
    fields = (
        ("title", "title_update"),
        ("summary", "summary_update"),
        ("status", "status_update"),
        ("sponsor_id", "sponsor_update"),
        ("introduced_at", "introduced_date_update"),
        ("last_action_at", "action_update"),
    )
    changes = []
    for field, change_type in fields:
        old_value = getattr(before, field)
        new_value = getattr(after, field)
        if old_value == new_value:
            continue
        public_key = field.removesuffix("_id") if field == "sponsor_id" else field
        changes.append(
            PendingBillChange(
                change_type=change_type,
                old_value={public_key: _json_value(old_value)},
                new_value={public_key: _json_value(new_value)},
                event_key=f"metadata:{change_type}:{_json_value(new_value)}",
            )
        )
    return tuple(changes)


_EVENT_LABELS = {
    "bill_created": "Bill added to the tracker",
    "status_update": "Bill status changed",
    "title_update": "Bill title changed",
    "summary_update": "Bill summary changed",
    "sponsor_update": "Bill sponsor changed",
    "introduced_date_update": "Bill introduction date changed",
    "action_update": "Latest bill action changed",
    "new_version": "A new bill text version is available",
    "contract_update": "Bill analysis was updated",
    "topic_update": "Bill topics were updated",
    "vote": "A roll-call vote was recorded",
    "committee_update": "Committee membership was updated",
    "cosponsor_update": "Bill cosponsors were updated",
}

_EVENT_KEYS = {
    "bill_created": {"status", "title"},
    "status_update": {"status"},
    "title_update": {"title"},
    "summary_update": {"summary"},
    "sponsor_update": {"sponsor"},
    "introduced_date_update": {"introduced_at"},
    "action_update": {"last_action_at"},
    "new_version": {"document_id", "version_label", "content_hash", "is_active_version"},
    "contract_update": {"contract_id", "contract_hash", "schema_version"},
    "topic_update": {"topics", "contract_id"},
    "vote": {
        "vote_id",
        "congress",
        "chamber",
        "session_number",
        "roll_number",
        "result",
        "yeas",
        "nays",
    },
    "committee_update": {
        "added",
        "removed",
        "added_count",
        "removed_count",
        "truncated",
    },
    "cosponsor_update": {
        "added",
        "removed",
        "added_count",
        "removed_count",
        "truncated",
    },
}


def _public_payload(change_type: str, value: dict | None):
    if not value:
        return None
    allowed = _EVENT_KEYS.get(change_type, set())
    return {key: value[key] for key in allowed if key in value}


def serialize_change_event(
    *,
    change_type: str,
    created_at,
    old_value: dict | None,
    new_value: dict,
    document_id: int | None,
    contract_id: int | None,
) -> dict:
    """Return the one public timeline payload; internal persistence stays private."""
    return {
        "type": change_type,
        "occurred_at": created_at,
        "summary": _EVENT_LABELS.get(change_type, "Bill updated"),
        "before": _public_payload(change_type, old_value),
        "after": _public_payload(change_type, new_value),
        "document_id": document_id,
        "contract_id": contract_id,
    }
