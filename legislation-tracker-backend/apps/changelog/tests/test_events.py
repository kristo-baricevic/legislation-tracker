from datetime import UTC, datetime

from apps.changelog.events import (
    BillMetadataSnapshot,
    diff_bill_metadata,
    serialize_change_event,
)


def test_metadata_diff_emits_only_the_changed_public_fields():
    before = BillMetadataSnapshot(
        title="Original title",
        summary="Original summary",
        status="Introduced",
        sponsor_id=1,
        introduced_at=None,
        last_action_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    after = BillMetadataSnapshot(
        title="Original title",
        summary="Updated summary",
        status="Introduced",
        sponsor_id=1,
        introduced_at=None,
        last_action_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    changes = diff_bill_metadata(before, after)

    assert [(change.change_type, change.old_value, change.new_value) for change in changes] == [
        ("summary_update", {"summary": "Original summary"}, {"summary": "Updated summary"})
    ]


def test_public_event_serializer_rejects_unknown_payload_keys():
    event = serialize_change_event(
        change_type="status_update",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        old_value={"status": "Introduced"},
        new_value={"status": "Reported", "unexpected": "nope"},
        document_id=None,
        contract_id=None,
    )

    assert event["summary"] == "Bill status changed"
    assert event["after"] == {"status": "Reported"}
    assert "unexpected" not in event["after"]
