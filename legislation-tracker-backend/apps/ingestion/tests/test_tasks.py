import pytest
from django.db import IntegrityError
from django.contrib.auth import get_user_model
from datetime import datetime, timedelta, timezone as dt_timezone

from django.utils import timezone

from apps.accounts.models import TrackedBill, TrackedLegislator, TrackedTopic
from apps.changelog.models import ChangeLog
from apps.congress.models import Representative, Vote, VoteRecord
from apps.ingestion import tasks
from apps.ingestion.congress_client import CongressAPIError
from apps.ingestion.models import (
    IngestionState,
    IngestionTaskFailure,
    IngestionWorkItem,
    IngestionWorkStatus,
)
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
def test_poll_congress_persists_discovered_work_and_cursor_when_dispatch_fails(monkeypatch):
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
        tasks.dispatch_ingestion_work,
        "delay",
        lambda: (_ for _ in ()).throw(RuntimeError("broker down")),
    )

    result = tasks.poll_congress(jurisdiction="federal", congress=119)

    state.refresh_from_db()
    assert result["discovered"] == 1
    assert state.last_bill_update_seen_at.isoformat() == "2026-01-02T00:00:00+00:00"
    assert state.last_polled_at is not None
    work = IngestionWorkItem.objects.get()
    assert (work.kind, work.dedupe_key, work.status) == (
        "bill",
        "119-hr-1",
        IngestionWorkStatus.PENDING,
    )


@pytest.mark.django_db
def test_poll_congress_replays_a_cursor_overlap_before_advancing(monkeypatch):
    state = IngestionState.objects.create(
        jurisdiction="federal",
        congress=119,
        last_bill_update_seen_at=datetime(2026, 1, 2, 12, 0, tzinfo=dt_timezone.utc),
    )
    observed_from_dates = []

    def fake_bill_list(congress, bill_type, from_date_time=None, limit=250, offset=0):
        observed_from_dates.append((bill_type, from_date_time))
        if bill_type == "hr":
            return [
                {
                    "congress": congress,
                    "type": bill_type,
                    "number": "2",
                    "updateDate": "2026-01-02T12:00:00Z",
                }
            ]
        return []

    monkeypatch.setattr(tasks, "bill_list", fake_bill_list)
    monkeypatch.setattr(tasks.dispatch_ingestion_work, "delay", lambda: None)

    tasks.poll_congress(jurisdiction="federal", congress=119)

    assert observed_from_dates == [
        ("hr", "2026-01-02T11:55:00Z"),
        ("s", "2026-01-02T11:55:00Z"),
    ]
    assert IngestionWorkItem.objects.get().dedupe_key == "119-hr-2"


@pytest.mark.django_db
def test_dispatch_ingestion_work_leases_pending_rows_before_sending_to_celery(monkeypatch):
    work = IngestionWorkItem.objects.create(
        kind="bill",
        dedupe_key="119-hr-1",
        source_updated_at=timezone.now(),
        payload_json={"bill_key": "119-hr-1"},
    )
    enqueued = []

    class Result:
        id = "worker-task-1"

    monkeypatch.setattr(
        tasks.process_ingestion_work_item,
        "apply_async",
        lambda args=None, kwargs=None: enqueued.append((args, kwargs)) or Result(),
    )

    result = tasks.dispatch_ingestion_work()

    work.refresh_from_db()
    assert result == {"dispatched": 1}
    assert enqueued == [([work.id, work.dispatch_token], None)]
    assert work.status == IngestionWorkStatus.DISPATCHED
    assert work.celery_task_id == "worker-task-1"
    assert work.dispatch_token
    assert work.lease_expires_at is not None


@pytest.mark.django_db
def test_processing_work_dead_letters_after_the_last_persistent_retry(monkeypatch):
    work = IngestionWorkItem.objects.create(
        kind="bill",
        dedupe_key="119-hr-1",
        source_updated_at=timezone.now(),
        payload_json={"bill_key": "119-hr-1"},
        status=IngestionWorkStatus.DISPATCHED,
        attempt_count=tasks.MAX_INGESTION_WORK_ATTEMPTS - 1,
        lease_expires_at=timezone.now() + timedelta(minutes=5),
    )
    monkeypatch.setattr(
        tasks,
        "_process_bill_impl",
        lambda bill_key: (_ for _ in ()).throw(CongressAPIError("Congress unavailable")),
    )

    result = tasks.process_ingestion_work_item(work.id)

    work.refresh_from_db()
    assert result == {"work_item_id": work.id, "status": "dead"}
    assert work.status == IngestionWorkStatus.DEAD
    failure = IngestionTaskFailure.objects.get(work_item=work)
    assert "Congress unavailable" in failure.error_message


@pytest.mark.django_db
def test_work_processor_rejects_a_stale_dispatch_token(monkeypatch):
    work = IngestionWorkItem.objects.create(
        kind="bill",
        dedupe_key="119-hr-1",
        source_updated_at=timezone.now(),
        payload_json={"bill_key": "119-hr-1"},
        status=IngestionWorkStatus.DISPATCHED,
        dispatch_token="current-lease",
        lease_expires_at=timezone.now() + timedelta(minutes=5),
    )
    monkeypatch.setattr(
        tasks,
        "_process_bill_impl",
        lambda bill_key: (_ for _ in ()).throw(AssertionError("must not process")),
    )

    assert tasks.process_ingestion_work_item(work.id, "stale-lease") == {
        "work_item_id": work.id,
        "status": "superseded",
    }


@pytest.mark.django_db
def test_recover_stale_ingestion_work_makes_expired_leases_dispatchable():
    work = IngestionWorkItem.objects.create(
        kind="bill",
        dedupe_key="119-hr-1",
        source_updated_at=timezone.now(),
        payload_json={"bill_key": "119-hr-1"},
        status=IngestionWorkStatus.PROCESSING,
        lease_expires_at=timezone.now() - timedelta(seconds=1),
    )

    assert tasks.recover_stale_ingestion_work() == {"recovered": 1}

    work.refresh_from_db()
    assert work.status == IngestionWorkStatus.PENDING
    assert work.lease_expires_at is None


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
        "bill_actions",
        lambda congress, bill_type, number: [
            {
                "recordedVotes": [
                    {
                        "chamber": "house",
                        "rollNumber": 10,
                        "sessionNumber": 1,
                    }
                ]
            }
        ],
    )

    def fail_vote_detail(congress, chamber, roll_number, **kwargs):
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
        "bill_actions",
        lambda congress, bill_type, number: [
            {
                "recordedVotes": [
                    {
                        "chamber": "house",
                        "rollNumber": 10,
                        "sessionNumber": 1,
                        "url": "https://api.congress.gov/v3/house-vote/119/1/10",
                    }
                ]
            }
        ],
    )
    vote_calls = []

    def fake_vote_detail(
        congress,
        chamber,
        roll_number,
        *,
        session_number=None,
        source_url=None,
    ):
        vote_calls.append((congress, chamber, roll_number, session_number, source_url))
        return {
            "date": "2026-01-02T00:00:00Z",
            "result": "Passed",
            "yeas": 1,
            "nays": 1,
            "members": {
                "yeas": [{"bioguideId": "A000001", "name": "Yes Member"}],
                "nays": [{"bioguideId": "B000002", "name": "No Member"}],
                "present": [{"bioguideId": "C000003", "name": "Present Member"}],
            },
        }

    monkeypatch.setattr(
        tasks,
        "vote_detail",
        fake_vote_detail,
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
    assert vote_calls == [
        (
            119,
            "house",
            10,
            1,
            "https://api.congress.gov/v3/house-vote/119/1/10",
        )
    ]


@pytest.mark.django_db
def test_sync_representatives_rejects_a_historical_congress(monkeypatch):
    monkeypatch.setattr(
        tasks,
        "member_list",
        lambda *args, **kwargs: pytest.fail("historical roster must not be fetched"),
    )

    with pytest.raises(ValueError, match="current Congress"):
        tasks.sync_representatives(congress=118)


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
        "bill_actions",
        lambda congress, bill_type, number: [
            {
                "recordedVotes": [
                    {
                        "chamber": "house",
                        "rollNumber": 10,
                        "sessionNumber": 1,
                    }
                ]
            }
        ],
    )
    payload = {
        "date": "2026-01-02T00:00:00Z",
        "result": "Passed",
        "yeas": 1,
        "nays": 0,
        "members": {"yeas": [{"bioguideId": "A000001", "name": "Member"}]},
    }
    monkeypatch.setattr(tasks, "vote_detail", lambda *args, **kwargs: payload)
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
def test_poll_tracked_bills_creates_durable_work_and_dispatches(monkeypatch):
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
    dispatched = []
    now = datetime(2026, 1, 2, 12, 3, tzinfo=dt_timezone.utc)
    monkeypatch.setattr(tasks.timezone, "now", lambda: now)
    monkeypatch.setattr(tasks.dispatch_ingestion_work, "delay", lambda: dispatched.append(True))
    monkeypatch.setattr(
        tasks.process_bill,
        "apply_async",
        lambda *args, **kwargs: pytest.fail(
            "tracked refreshes must use durable work, not direct Celery tasks"
        ),
    )

    result = tasks.poll_tracked_bills()

    assert result == {"enqueued": 3}
    assert dispatched == [True]
    work_items = list(IngestionWorkItem.objects.order_by("dedupe_key"))
    assert [
        (work.dedupe_key, work.status, work.source_updated_at, work.payload_json)
        for work in work_items
    ] == [
        (
            "119-hr-101",
            IngestionWorkStatus.PENDING,
            datetime(2026, 1, 2, 12, 0, tzinfo=dt_timezone.utc),
            {"bill_key": "119-hr-101"},
        ),
        (
            "119-hr-303",
            IngestionWorkStatus.PENDING,
            datetime(2026, 1, 2, 12, 0, tzinfo=dt_timezone.utc),
            {"bill_key": "119-hr-303"},
        ),
        (
            "119-s-202",
            IngestionWorkStatus.PENDING,
            datetime(2026, 1, 2, 12, 0, tzinfo=dt_timezone.utc),
            {"bill_key": "119-s-202"},
        ),
    ]


@pytest.mark.django_db
def test_sync_representatives_ingests_the_complete_current_roster_before_retiring_stale_rows(monkeypatch):
    stale = Representative.objects.create(
        bioguide_id="S000001",
        name="Stale Member",
        chamber="house",
        party="Independent",
        state="NY",
        is_current=True,
    )
    offsets = []

    def fake_member_list(congress, current_member=True, limit=250, offset=0):
        offsets.append(offset)
        if offset == 0:
            return [
                {
                    "bioguideId": "C000001",
                    "name": "Doe, Jane",
                    "partyName": "Independent",
                    "state": "CA",
                    "district": 12,
                    "url": "https://api.congress.gov/v3/member/C000001",
                }
            ]
        return []

    monkeypatch.setattr(tasks, "member_list", fake_member_list)
    monkeypatch.setattr(
        tasks,
        "member_detail",
        lambda bioguide_id: {
            "bioguideId": bioguide_id,
            "directOrderName": "Jane Doe",
            "firstName": "Jane",
            "lastName": "Doe",
            "officialWebsiteUrl": "https://doe.house.gov",
            "depiction": {"imageUrl": "https://images.example.com/doe.jpg"},
            "terms": {"item": [{"chamber": "House"}]},
            "currentMember": True,
        },
    )

    result = tasks.sync_representatives(congress=119)

    representative = Representative.objects.get(bioguide_id="C000001")
    stale.refresh_from_db()
    assert result == {"congress": 119, "members": 1, "created": 1, "updated": 0}
    assert offsets == [0]
    assert (
        representative.name,
        representative.first_name,
        representative.last_name,
        representative.chamber,
        representative.party,
        representative.state,
        representative.district,
        representative.official_website_url,
        representative.image_url,
        representative.source_api_url,
        representative.is_current,
    ) == (
        "Jane Doe",
        "Jane",
        "Doe",
        "house",
        "Independent",
        "CA",
        "12",
        "https://doe.house.gov",
        "https://images.example.com/doe.jpg",
        "https://api.congress.gov/v3/member/C000001",
        True,
    )
    assert stale.is_current is False


@pytest.mark.django_db
def test_sync_representatives_does_not_retire_existing_members_after_an_incomplete_pull(monkeypatch):
    stale = Representative.objects.create(
        bioguide_id="S000001",
        name="Stale Member",
        chamber="house",
        party="Independent",
        state="NY",
        is_current=True,
    )
    monkeypatch.setattr(
        tasks,
        "member_list",
        lambda congress, current_member=True, limit=250, offset=0: [
            {"bioguideId": "C000001", "name": "Doe, Jane"}
        ] if offset == 0 else [],
    )
    monkeypatch.setattr(
        tasks,
        "member_detail",
        lambda bioguide_id: (_ for _ in ()).throw(CongressAPIError("member unavailable")),
    )

    with pytest.raises(CongressAPIError, match="member unavailable"):
        tasks.sync_representatives(congress=119)

    stale.refresh_from_db()
    assert stale.is_current is True
    assert not Representative.objects.filter(bioguide_id="C000001").exists()
