import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.models import TrackedBill, TrackedLegislator, TrackedTopic
from apps.changelog.models import ChangeLog
from apps.congress.models import Representative, Vote
from apps.ingestion import tasks
from apps.ingestion.congress_client import CongressAPIError
from apps.ingestion.models import IngestionState
from apps.legislation.models import Bill, BillDocument, BillTopic, ProcessingStatus, Topic


@pytest.mark.django_db
def test_poll_congress_does_not_advance_cursor_or_enqueue_after_partial_failure(monkeypatch):
    state = IngestionState.objects.create(jurisdiction="federal", congress=119)
    enqueued = []

    def fake_bill_list(congress, bill_type, from_date_time=None, limit=250, offset=0):
        if bill_type == "hr":
            return [
                {
                    "congress": congress,
                    "type": bill_type,
                    "number": "1",
                    "updateDate": "2026-01-02T00:00:00Z",
                }
            ]
        raise CongressAPIError("senate list unavailable")

    monkeypatch.setattr(tasks, "bill_list", fake_bill_list)
    monkeypatch.setattr(
        tasks.process_bill,
        "apply_async",
        lambda args=None, kwargs=None: enqueued.append((args, kwargs)),
    )

    with pytest.raises(CongressAPIError):
        tasks.poll_congress(jurisdiction="federal", congress=119)

    state.refresh_from_db()
    assert state.last_bill_update_seen_at is None
    assert state.last_polled_at is None
    assert enqueued == []


@pytest.mark.django_db
def test_process_bill_votes_surfaces_vote_detail_failures_for_retry(monkeypatch):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 1",
        title="Test bill",
        status="Introduced",
    )

    monkeypatch.setattr(
        tasks,
        "bill_detail",
        lambda congress, bill_type, number: {
            "votes": [{"chamber": "house", "rollNumber": 10}]
        },
    )

    def fail_vote_detail(congress, chamber, roll_number):
        raise CongressAPIError("vote endpoint unavailable")

    monkeypatch.setattr(tasks, "vote_detail", fail_vote_detail)

    with pytest.raises(CongressAPIError):
        tasks.process_bill_votes(bill.id)

    assert Vote.objects.count() == 0
    assert ChangeLog.objects.count() == 0


@pytest.mark.django_db
def test_process_bill_keeps_bill_processing_after_enqueueing_downstream_work(monkeypatch):
    enqueued = []

    monkeypatch.setattr(
        tasks,
        "bill_detail",
        lambda congress, bill_type, number: {
            "title": "Test bill",
            "latestAction": {
                "actionDate": "2026-01-01",
                "text": "Introduced in House",
            },
            "introducedDate": "2026-01-01",
            "url": "https://api.congress.gov/v3/bill/119/hr/1",
        },
    )
    monkeypatch.setattr(
        tasks.process_bill_versions,
        "apply_async",
        lambda args=None, kwargs=None: enqueued.append(("versions", args, kwargs)),
    )
    monkeypatch.setattr(
        tasks.process_bill_votes,
        "apply_async",
        lambda args=None, kwargs=None: enqueued.append(("votes", args, kwargs)),
    )

    result = tasks._process_bill_impl("119-hr-1")

    bill = Bill.objects.get(pk=result["bill_id"])
    assert bill.processing_status == ProcessingStatus.PROCESSING
    assert enqueued == [
        ("versions", [bill.id], None),
        ("votes", [bill.id], None),
    ]


@pytest.mark.django_db
def test_process_bill_status_changelog_preserves_old_and_new_values(monkeypatch):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 1",
        title="Old title",
        status="Old action",
        metadata_hash="old-hash",
    )
    monkeypatch.setattr(
        tasks,
        "bill_detail",
        lambda congress, bill_type, number: {
            "title": "New title",
            "latestAction": {
                "actionDate": "2026-01-02",
                "text": "New action",
            },
            "introducedDate": "2026-01-01",
            "url": "https://api.congress.gov/v3/bill/119/hr/1",
        },
    )
    monkeypatch.setattr(tasks.process_bill_versions, "apply_async", lambda args=None, kwargs=None: None)
    monkeypatch.setattr(tasks.process_bill_votes, "apply_async", lambda args=None, kwargs=None: None)

    result = tasks._process_bill_impl("119-hr-1")

    assert result == {"bill_id": bill.id, "unchanged": False}
    change = ChangeLog.objects.get(change_type="status_update")
    assert change.old_value == {"status": "Old action", "title": "Old title"}
    assert change.new_value == {"status": "New action", "title": "New title"}


@pytest.mark.django_db
def test_process_bill_versions_does_not_reenqueue_download_for_unchanged_document(monkeypatch):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 1",
        title="Test bill",
        status="Introduced",
    )
    enqueued = []

    monkeypatch.setattr(
        tasks,
        "bill_text_list",
        lambda congress, bill_type, number: [
            {
                "version_label": "Introduced",
                "url": "https://www.congress.gov/119/bills/hr1/BILLS-119hr1ih.xml",
            }
        ],
    )
    monkeypatch.setattr(
        tasks.download_document,
        "apply_async",
        lambda args=None, kwargs=None: enqueued.append((args, kwargs)),
    )

    first_result = tasks.process_bill_versions(bill.id)

    doc = BillDocument.objects.get(bill=bill, version_label="Introduced")
    assert first_result == {"bill_id": bill.id, "versions": 1}
    assert enqueued == [([doc.id], None)]

    doc.object_storage_key = "congress/119/hr-1/introduced.xml"
    doc.downloaded_at = timezone.now()
    doc.save(update_fields=["object_storage_key", "downloaded_at"])
    enqueued.clear()

    second_result = tasks.process_bill_versions(bill.id)

    assert second_result == {"bill_id": bill.id, "versions": 1}
    assert BillDocument.objects.filter(bill=bill, version_label="Introduced").count() == 1
    assert BillDocument.objects.filter(bill=bill, is_active_version=True).count() == 1
    assert enqueued == []


@pytest.mark.django_db
def test_poll_tracked_bills_enqueues_unique_bills_matching_user_tracking(monkeypatch):
    user = get_user_model().objects.create_user(
        username="owner@example.com",
        email="owner@example.com",
        password="password",
    )
    representative = Representative.objects.create(
        bioguide_id="A000001",
        name="Tracked Representative",
        chamber="house",
        party="Independent",
        state="NY",
    )
    topic = Topic.objects.create(name="Health", slug="health")
    direct_bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 101",
        title="Direct bill",
        status="Introduced",
    )
    topic_bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="S 202",
        title="Topic bill",
        status="Introduced",
    )
    legislator_bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 303",
        title="Legislator bill",
        status="Introduced",
        sponsor=representative,
    )
    unrelated_bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 404",
        title="Unrelated bill",
        status="Introduced",
    )
    BillTopic.objects.create(bill=topic_bill, topic=topic)
    BillTopic.objects.create(bill=direct_bill, topic=topic)
    TrackedBill.objects.create(user=user, bill=direct_bill)
    TrackedTopic.objects.create(user=user, topic=topic)
    TrackedLegislator.objects.create(user=user, representative=representative)
    enqueued = []

    monkeypatch.setattr(
        tasks.process_bill,
        "apply_async",
        lambda args=None, kwargs=None: enqueued.append((args, kwargs)),
    )

    result = tasks.poll_tracked_bills()

    assert result == {"enqueued": 3}
    assert {tuple(args) for args, _kwargs in enqueued} == {
        ("119-hr-101",),
        ("119-s-202",),
        ("119-hr-303",),
    }
    assert ("119-hr-404",) not in {tuple(args) for args, _kwargs in enqueued}
