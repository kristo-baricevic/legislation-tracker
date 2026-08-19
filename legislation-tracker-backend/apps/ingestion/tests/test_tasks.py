import pytest
from django.db import IntegrityError
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.models import TrackedBill, TrackedLegislator, TrackedTopic
from apps.changelog.models import ChangeLog
from apps.congress.models import Representative, Vote, VoteRecord
from apps.ingestion import tasks
from apps.ingestion.congress_client import CongressAPIError
from apps.ingestion.models import IngestionState, IngestionTaskFailure
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
def test_poll_congress_does_not_advance_cursor_when_enqueue_fails(monkeypatch):
    state = IngestionState.objects.create(jurisdiction="federal", congress=119)

    monkeypatch.setattr(
        tasks,
        "bill_list",
        lambda congress, bill_type, from_date_time=None, limit=250, offset=0: (
            [
                {
                    "congress": congress,
                    "type": bill_type,
                    "number": "1",
                    "updateDate": "2026-01-02T00:00:00Z",
                }
            ]
            if bill_type == "hr"
            else []
        ),
    )
    monkeypatch.setattr(
        tasks.process_bill,
        "apply_async",
        lambda args=None, kwargs=None: (_ for _ in ()).throw(RuntimeError("broker down")),
    )

    with pytest.raises(RuntimeError, match="broker down"):
        tasks.poll_congress(jurisdiction="federal", congress=119)

    state.refresh_from_db()
    assert state.last_bill_update_seen_at is None
    assert state.last_polled_at is None


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
def test_process_bill_votes_preserves_positions_from_grouped_member_payload(monkeypatch):
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
    monkeypatch.setattr(
        tasks,
        "vote_detail",
        lambda congress, chamber, roll_number: {
            "date": "2026-01-02T00:00:00Z",
            "result": "Passed",
            "yeas": 1,
            "nays": 1,
            "members": {
                "yeas": [{"bioguideId": "A000001", "name": "Yes Member"}],
                "nays": [{"bioguideId": "B000002", "name": "No Member"}],
                "present": [{"bioguideId": "C000003", "name": "Present Member"}],
            },
        },
    )

    tasks.process_bill_votes(bill.id)

    vote = Vote.objects.get(bill=bill)
    assert dict(
        VoteRecord.objects.filter(vote=vote).values_list(
            "representative__bioguide_id", "position"
        )
    ) == {
        "A000001": "yes",
        "B000002": "no",
        "C000003": "present",
    }


@pytest.mark.django_db
def test_process_bill_votes_updates_existing_vote_and_records(monkeypatch):
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
    payload = {
        "date": "2026-01-02T00:00:00Z",
        "result": "Passed",
        "yeas": 1,
        "nays": 0,
        "members": {"yeas": [{"bioguideId": "A000001", "name": "Member"}]},
    }
    monkeypatch.setattr(tasks, "vote_detail", lambda *args: payload)
    tasks.process_bill_votes(bill.id)

    payload.update(
        {
            "result": "Failed",
            "yeas": 0,
            "nays": 1,
            "members": {"nays": [{"bioguideId": "A000001", "name": "Member"}]},
        }
    )
    tasks.process_bill_votes(bill.id)

    vote = Vote.objects.get(bill=bill)
    assert (vote.result, vote.yeas, vote.nays) == ("Failed", 0, 1)
    assert VoteRecord.objects.get(vote=vote).position == "no"
    assert ChangeLog.objects.filter(bill=bill, change_type="vote").count() == 2


@pytest.mark.django_db
def test_vote_records_are_unique_per_vote_and_representative():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 2",
        title="Test bill",
        status="Introduced",
    )
    representative = Representative.objects.create(
        bioguide_id="A000002",
        name="Member",
        chamber="house",
        party="Independent",
        state="NY",
    )
    vote = Vote.objects.create(
        bill=bill,
        chamber="house",
        roll_number=1,
        vote_date=timezone.now(),
        result="Passed",
    )
    VoteRecord.objects.create(vote=vote, representative=representative, position="yes")

    with pytest.raises(IntegrityError):
        VoteRecord.objects.create(vote=vote, representative=representative, position="yes")


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
def test_process_bill_refreshes_votes_when_existing_documents_are_complete(monkeypatch):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 1",
        title="Test bill",
        status="Introduced",
        metadata_hash=tasks.compute_metadata_hash(
            "Introduced", "Test bill", None, None, source_api_id="119-hr-1"
        ),
    )
    BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        object_storage_key="documents/hr-1.xml",
        downloaded_at=timezone.now(),
    )
    enqueued = []
    monkeypatch.setattr(
        tasks,
        "bill_detail",
        lambda congress, bill_type, number: {
            "title": "Test bill",
            "latestAction": {"text": "Introduced"},
            "url": "119-hr-1",
        },
    )
    monkeypatch.setattr(
        tasks.process_bill_versions,
        "apply_async",
        lambda args=None, kwargs=None: enqueued.append(("versions", args)),
    )
    monkeypatch.setattr(
        tasks.process_bill_votes,
        "apply_async",
        lambda args=None, kwargs=None: enqueued.append(("votes", args)),
    )

    result = tasks._process_bill_impl("119-hr-1")

    assert result == {"bill_id": bill.id, "unchanged": True}
    assert enqueued == [("votes", [bill.id])]


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
def test_process_bill_versions_enqueues_metadata_contract_when_no_text_versions_exist(monkeypatch):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 1",
        title="Test bill",
        status="Introduced",
        processing_status=ProcessingStatus.PROCESSING,
    )
    enqueued = []
    monkeypatch.setattr(tasks, "bill_text_list", lambda *args: [])
    monkeypatch.setattr(
        tasks.generate_contract_for_bill,
        "apply_async",
        lambda args=None, kwargs=None: enqueued.append((args, kwargs)),
    )

    result = tasks.process_bill_versions(bill.id)

    assert result == {"bill_id": bill.id, "versions": 0, "fallback_enqueued": True}
    assert enqueued == [([bill.id], None)]


@pytest.mark.django_db
def test_process_bill_records_non_retryable_failures(monkeypatch):
    monkeypatch.setattr(
        tasks,
        "_process_bill_impl",
        lambda bill_key: (_ for _ in ()).throw(ValueError("invalid payload")),
    )

    with pytest.raises(ValueError, match="invalid payload"):
        tasks.process_bill("119-hr-1")

    failure = IngestionTaskFailure.objects.get(task_name="process_bill")
    assert "invalid payload" in failure.error_message


@pytest.mark.django_db
def test_existing_sponsor_profiles_are_refreshed_from_new_metadata():
    rep = Representative.objects.create(
        bioguide_id="A000001",
        name="Old Name",
        chamber="house",
        party="Old Party",
        state="NY",
        district="1",
    )

    result = tasks.get_or_create_representative_from_sponsor(
        {
            "bioguideId": rep.bioguide_id,
            "fullName": "New Name",
            "chamber": "senate",
            "party": "New Party",
            "state": "CA",
        }
    )

    result.refresh_from_db()
    assert (result.name, result.chamber, result.party, result.state, result.district) == (
        "New Name",
        "senate",
        "New Party",
        "CA",
        None,
    )


@pytest.mark.django_db
def test_sparse_representative_payloads_do_not_erase_existing_profile_data():
    rep = Representative.objects.create(
        bioguide_id="B000002",
        name="Known Senator",
        chamber="senate",
        party="Independent",
        state="VT",
    )

    result = tasks.get_or_create_representative_from_sponsor(
        {"bioguideId": rep.bioguide_id}
    )

    result.refresh_from_db()
    assert (result.name, result.chamber, result.party, result.state) == (
        "Known Senator",
        "senate",
        "Independent",
        "VT",
    )


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
