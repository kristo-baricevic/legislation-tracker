import hashlib
from datetime import UTC, datetime, timedelta
from io import BytesIO
from tempfile import SpooledTemporaryFile

import pytest
from botocore.exceptions import ClientError
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.utils import timezone

from apps.accounts.models import TrackedBill, TrackedLegislator, TrackedTopic
from apps.changelog.models import ChangeLog
from apps.congress.models import Representative, Vote, VoteRecord
from apps.ingestion import document_download, tasks
from apps.ingestion.congress_client import CongressAPIError
from apps.ingestion.models import (
    IngestionState,
    IngestionTaskFailure,
    IngestionWorkItem,
    IngestionWorkStatus,
)
from apps.legislation.extraction.service import extract_contract
from apps.legislation.models import (
    Bill,
    BillDocument,
    BillTopic,
    ProcessingStatus,
    Topic,
)


def downloaded_document(payload, content_type):
    return document_download.DownloadedDocument(
        file=BytesIO(payload),
        content_type=content_type,
        size=len(payload),
        checksum=hashlib.sha256(payload).hexdigest(),
    )


@pytest.mark.django_db
def test_poll_congress_resolves_current_congress_when_task_executes(monkeypatch):
    monkeypatch.setattr(tasks, "current_congress", lambda: 121)
    observed = []
    monkeypatch.setattr(
        tasks,
        "bill_list",
        lambda congress, *args, **kwargs: observed.append(congress) or [],
    )

    result = tasks.poll_congress(congress=None)

    assert observed == [121, 121]
    assert result["congress"] == 121


@pytest.mark.django_db
def test_sync_representatives_resolves_current_congress_when_task_executes(monkeypatch):
    monkeypatch.setattr(tasks, "current_congress", lambda: 121)
    monkeypatch.setattr(tasks, "member_list", lambda congress, **kwargs: [])

    with pytest.raises(CongressAPIError, match="roster was empty"):
        tasks.sync_representatives(congress=None)


def test_sync_representatives_has_bounded_congress_api_retries():
    assert getattr(tasks.sync_representatives, "autoretry_for", ()) == (
        CongressAPIError,
    )
    assert tasks.sync_representatives.max_retries == 2


@pytest.mark.django_db
def test_poll_congress_does_not_advance_cursor_or_enqueue_after_partial_failure(
    monkeypatch,
):
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
def test_poll_congress_keeps_cursor_when_offset_pagination_repeats(monkeypatch):
    initial_cursor = datetime(2026, 1, 1, tzinfo=UTC)
    state = IngestionState.objects.create(
        jurisdiction="federal",
        congress=119,
        last_bill_update_seen_at=initial_cursor,
    )
    repeated_page = [
        {
            "congress": 119,
            "type": "hr",
            "number": str(number),
            "updateDate": "2026-01-02T00:00:00Z",
        }
        for number in range(1, 251)
    ]

    def fake_bill_list(congress, bill_type, from_date_time=None, limit=250, offset=0):
        if bill_type == "hr" and offset in (0, 250):
            return repeated_page
        return []

    monkeypatch.setattr(tasks, "bill_list", fake_bill_list)
    monkeypatch.setattr(tasks.dispatch_ingestion_work, "delay", lambda: None)

    with pytest.raises(CongressAPIError, match="repeated same page"):
        tasks.poll_congress(jurisdiction="federal", congress=119)

    state.refresh_from_db()
    assert state.last_bill_update_seen_at == initial_cursor
    assert state.last_polled_at is None
    assert not IngestionWorkItem.objects.exists()


@pytest.mark.django_db
def test_poll_congress_persists_discovered_work_and_cursor_when_dispatch_fails(
    monkeypatch,
):
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
    IngestionState.objects.create(
        jurisdiction="federal",
        congress=119,
        last_bill_update_seen_at=datetime(2026, 1, 2, 12, 0, tzinfo=UTC),
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
def test_dispatch_ingestion_work_leases_pending_rows_before_sending_to_celery(
    monkeypatch,
):
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
def test_dispatch_does_not_release_a_replacement_lease_after_enqueue_failure(
    monkeypatch,
):
    work = IngestionWorkItem.objects.create(
        kind="bill",
        dedupe_key="119-hr-2",
        source_updated_at=timezone.now(),
        payload_json={"bill_key": "119-hr-2"},
    )

    def replace_lease_then_fail(args=None, kwargs=None):
        IngestionWorkItem.objects.filter(pk=work.pk).update(
            status=IngestionWorkStatus.DISPATCHED,
            dispatch_token="replacement-lease",
            celery_task_id="replacement-task",
            lease_expires_at=timezone.now() + timedelta(minutes=10),
        )
        raise RuntimeError("stale dispatcher failed")

    monkeypatch.setattr(
        tasks.process_ingestion_work_item,
        "apply_async",
        replace_lease_then_fail,
    )

    result = tasks.dispatch_ingestion_work()

    work.refresh_from_db()
    assert result == {"dispatched": 0}
    assert work.status == IngestionWorkStatus.DISPATCHED
    assert work.dispatch_token == "replacement-lease"
    assert work.celery_task_id == "replacement-task"


@pytest.mark.django_db
def test_dispatch_does_not_overwrite_a_replacement_lease_task_id(monkeypatch):
    work = IngestionWorkItem.objects.create(
        kind="bill",
        dedupe_key="119-hr-3",
        source_updated_at=timezone.now(),
        payload_json={"bill_key": "119-hr-3"},
    )

    class Result:
        id = "stale-task"

    def replace_lease_then_return(args=None, kwargs=None):
        IngestionWorkItem.objects.filter(pk=work.pk).update(
            status=IngestionWorkStatus.DISPATCHED,
            dispatch_token="replacement-lease",
            celery_task_id="replacement-task",
            lease_expires_at=timezone.now() + timedelta(minutes=10),
        )
        return Result()

    monkeypatch.setattr(
        tasks.process_ingestion_work_item,
        "apply_async",
        replace_lease_then_return,
    )

    result = tasks.dispatch_ingestion_work()

    work.refresh_from_db()
    assert result == {"dispatched": 0}
    assert work.status == IngestionWorkStatus.DISPATCHED
    assert work.dispatch_token == "replacement-lease"
    assert work.celery_task_id == "replacement-task"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("kind", "payload", "target_module", "target_name"),
    [
        ("bill_versions", {"bill_id": 1}, "ingestion", "_process_bill_versions_impl"),
        ("bill_votes", {"bill_id": 1}, "ingestion", "_process_bill_votes_impl"),
        (
            "document_download",
            {"document_id": 1},
            "ingestion",
            "_download_document_impl",
        ),
        (
            "document_contract",
            {"document_id": 1},
            "legislation",
            "_generate_contract_impl",
        ),
        (
            "metadata_contract",
            {"bill_id": 1},
            "legislation",
            "_generate_contract_for_bill_impl",
        ),
        (
            "topic_update",
            {"bill_id": 1},
            "legislation",
            "_update_topics_impl",
        ),
        (
            "similarity",
            {"bill_id": 1},
            "legislation",
            "_schedule_similarity_for_bill_impl",
        ),
    ],
)
def test_durable_worker_routes_each_pipeline_stage(
    monkeypatch, kind, payload, target_module, target_name
):
    from apps.legislation import tasks as legislation_tasks

    called = []
    module = tasks if target_module == "ingestion" else legislation_tasks
    monkeypatch.setattr(
        module,
        target_name,
        lambda *args, **kwargs: called.append((args, kwargs)),
    )
    work = IngestionWorkItem.objects.create(
        kind=kind,
        dedupe_key=f"{kind}-1",
        source_updated_at=timezone.now(),
        payload_json=payload,
        status=IngestionWorkStatus.DISPATCHED,
    )

    result = tasks.process_ingestion_work_item(work.id)

    work.refresh_from_db()
    assert result == {"work_item_id": work.id, "status": "succeeded"}
    assert work.status == IngestionWorkStatus.SUCCEEDED
    assert called


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
        lambda bill_key: (_ for _ in ()).throw(
            CongressAPIError("Congress unavailable")
        ),
    )

    result = tasks.process_ingestion_work_item(work.id)

    work.refresh_from_db()
    assert result == {"work_item_id": work.id, "status": "dead"}
    assert work.status == IngestionWorkStatus.DEAD
    failure = IngestionTaskFailure.objects.get(work_item=work)
    assert "Congress unavailable" in failure.error_message


@pytest.mark.django_db
def test_bounded_document_validation_failure_dead_letters_without_retrying(monkeypatch):
    work = IngestionWorkItem.objects.create(
        kind="document_download",
        dedupe_key="document-1",
        source_updated_at=timezone.now(),
        payload_json={"document_id": 1},
        status=IngestionWorkStatus.DISPATCHED,
    )
    monkeypatch.setattr(
        tasks,
        "_download_document_impl",
        lambda document_id: (_ for _ in ()).throw(
            document_download.DocumentByteLimitExceeded(
                "Document contains more than 4 bytes"
            )
        ),
    )

    result = tasks.process_ingestion_work_item(work.id)

    work.refresh_from_db()
    assert result == {"work_item_id": work.id, "status": "dead"}
    assert work.status == IngestionWorkStatus.DEAD
    assert work.attempt_count == 1
    failure = IngestionTaskFailure.objects.get(work_item=work)
    assert "more than 4 bytes" in failure.error_message


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
def test_work_processor_does_not_complete_after_its_lease_is_replaced(monkeypatch):
    work = IngestionWorkItem.objects.create(
        kind="bill",
        dedupe_key="119-hr-1",
        source_updated_at=timezone.now(),
        payload_json={"bill_key": "119-hr-1"},
        status=IngestionWorkStatus.DISPATCHED,
        dispatch_token="original-lease",
        lease_expires_at=timezone.now() + timedelta(minutes=5),
    )

    def replace_lease(_bill_key):
        IngestionWorkItem.objects.filter(pk=work.id).update(
            status=IngestionWorkStatus.PROCESSING,
            dispatch_token="replacement-lease",
            attempt_count=2,
            lease_expires_at=timezone.now() + timedelta(minutes=5),
        )

    monkeypatch.setattr(tasks, "_process_bill_impl", replace_lease)

    assert tasks.process_ingestion_work_item(work.id, "original-lease") == {
        "work_item_id": work.id,
        "status": "superseded",
    }
    work.refresh_from_db()
    assert work.status == IngestionWorkStatus.PROCESSING
    assert work.dispatch_token == "replacement-lease"


@pytest.mark.django_db
def test_work_processor_does_not_retry_after_its_lease_is_replaced(monkeypatch):
    work = IngestionWorkItem.objects.create(
        kind="bill",
        dedupe_key="119-hr-1",
        source_updated_at=timezone.now(),
        payload_json={"bill_key": "119-hr-1"},
        status=IngestionWorkStatus.DISPATCHED,
        dispatch_token="original-lease",
        lease_expires_at=timezone.now() + timedelta(minutes=5),
    )

    def replace_lease_then_fail(_bill_key):
        IngestionWorkItem.objects.filter(pk=work.id).update(
            status=IngestionWorkStatus.PROCESSING,
            dispatch_token="replacement-lease",
            attempt_count=2,
            lease_expires_at=timezone.now() + timedelta(minutes=5),
        )
        raise CongressAPIError("old worker failed after replacement")

    monkeypatch.setattr(tasks, "_process_bill_impl", replace_lease_then_fail)

    assert tasks.process_ingestion_work_item(work.id, "original-lease") == {
        "work_item_id": work.id,
        "status": "superseded",
    }
    work.refresh_from_db()
    assert work.status == IngestionWorkStatus.PROCESSING
    assert work.dispatch_token == "replacement-lease"
    assert work.last_error == ""


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
def test_recover_stale_ingestion_work_dead_letters_an_exhausted_lease():
    work = IngestionWorkItem.objects.create(
        kind="bill",
        dedupe_key="119-hr-1",
        source_updated_at=timezone.now(),
        payload_json={"bill_key": "119-hr-1"},
        status=IngestionWorkStatus.PROCESSING,
        attempt_count=tasks.MAX_INGESTION_WORK_ATTEMPTS,
        celery_task_id="lost-worker-task",
        lease_expires_at=timezone.now() - timedelta(seconds=1),
    )

    assert tasks.recover_stale_ingestion_work() == {"recovered": 0}

    work.refresh_from_db()
    assert work.status == IngestionWorkStatus.DEAD
    assert work.lease_expires_at is None
    failure = IngestionTaskFailure.objects.get(work_item=work)
    assert failure.task_id == "lost-worker-task"
    assert "lease expired" in failure.error_message.lower()


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
def test_process_bill_votes_preserves_positions_from_grouped_member_payload(
    monkeypatch,
):
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
def test_process_bill_votes_adopts_a_legacy_vote_with_unknown_session(monkeypatch):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 4",
        title="Legacy vote bill",
        status="Introduced",
    )
    legacy_vote = Vote.objects.create(
        bill=bill,
        chamber="house",
        session_number=None,
        roll_number=10,
        vote_date=datetime(2025, 1, 3, tzinfo=UTC),
        result="Unknown",
    )
    monkeypatch.setattr(
        tasks,
        "bill_actions",
        lambda congress, bill_type, number: [
            {
                "recordedVotes": [
                    {"chamber": "house", "rollNumber": 10, "sessionNumber": 1},
                ]
            }
        ],
    )
    monkeypatch.setattr(
        tasks,
        "vote_detail",
        lambda congress, chamber, roll_number, *, session_number=None, source_url=None: {
            "date": "2025-01-03T00:00:00Z",
            "result": "Passed",
            "yeas": 1,
            "nays": 0,
            "members": [],
        },
    )

    tasks.process_bill_votes(bill.id)

    assert Vote.objects.filter(bill=bill, chamber="house", roll_number=10).count() == 1
    legacy_vote.refresh_from_db()
    assert legacy_vote.session_number == 1
    assert legacy_vote.result == "Passed"


@pytest.mark.django_db
def test_process_bill_votes_keeps_same_roll_number_from_two_sessions(monkeypatch):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 3",
        title="Two-session vote bill",
        status="Introduced",
    )
    monkeypatch.setattr(
        tasks,
        "bill_actions",
        lambda congress, bill_type, number: [
            {
                "recordedVotes": [
                    {"chamber": "house", "rollNumber": 10, "sessionNumber": 1},
                    {"chamber": "house", "rollNumber": 10, "sessionNumber": 2},
                ]
            }
        ],
    )
    monkeypatch.setattr(
        tasks,
        "vote_detail",
        lambda congress, chamber, roll_number, *, session_number=None, source_url=None: {
            "date": f"202{4 + session_number}-01-02T00:00:00Z",
            "result": f"Session {session_number}",
            "yeas": 1,
            "nays": 0,
            "members": [],
        },
    )

    tasks.process_bill_votes(bill.id)

    assert Vote.objects.filter(bill=bill, chamber="house", roll_number=10).count() == 2


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
        VoteRecord.objects.create(
            vote=vote, representative=representative, position="yes"
        )


@pytest.mark.django_db
def test_process_bill_keeps_bill_processing_after_enqueueing_downstream_work(
    monkeypatch,
):
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
    monkeypatch.setattr(tasks.dispatch_ingestion_work, "delay", lambda: None)

    result = tasks._process_bill_impl("119-hr-1")

    bill = Bill.objects.get(pk=result["bill_id"])
    assert bill.processing_status == ProcessingStatus.PROCESSING
    assert list(
        IngestionWorkItem.objects.order_by("kind").values_list("kind", "payload_json")
    ) == [
        ("bill_versions", {"bill_id": bill.id}),
        ("bill_votes", {"bill_id": bill.id}),
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
    monkeypatch.setattr(
        tasks,
        "bill_detail",
        lambda congress, bill_type, number: {
            "title": "Test bill",
            "latestAction": {"text": "Introduced"},
            "url": "119-hr-1",
        },
    )
    monkeypatch.setattr(tasks.dispatch_ingestion_work, "delay", lambda: None)

    result = tasks._process_bill_impl("119-hr-1")

    assert result == {"bill_id": bill.id, "unchanged": True}
    assert list(IngestionWorkItem.objects.values_list("kind", "payload_json")) == [
        ("bill_votes", {"bill_id": bill.id})
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
    monkeypatch.setattr(
        tasks.process_bill_versions, "apply_async", lambda args=None, kwargs=None: None
    )
    monkeypatch.setattr(
        tasks.process_bill_votes, "apply_async", lambda args=None, kwargs=None: None
    )

    result = tasks._process_bill_impl("119-hr-1")

    assert result == {"bill_id": bill.id, "unchanged": False}
    change = ChangeLog.objects.get(change_type="status_update")
    assert change.old_value == {"status": "Old action", "title": "Old title"}
    assert change.new_value == {"status": "New action", "title": "New title"}


@pytest.mark.django_db
def test_process_bill_versions_does_not_reenqueue_download_for_unchanged_document(
    monkeypatch,
):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 1",
        title="Test bill",
        status="Introduced",
    )

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
    monkeypatch.setattr(tasks.dispatch_ingestion_work, "delay", lambda: None)

    first_result = tasks.process_bill_versions(bill.id)

    doc = BillDocument.objects.get(bill=bill, version_label="Introduced")
    assert first_result == {"bill_id": bill.id, "versions": 1}
    assert list(
        IngestionWorkItem.objects.filter(kind="document_download").values_list(
            "payload_json", flat=True
        )
    ) == [{"document_id": doc.id}]

    doc.object_storage_key = "congress/119/hr-1/introduced.xml"
    doc.downloaded_at = timezone.now()
    doc.save(update_fields=["object_storage_key", "downloaded_at"])
    second_result = tasks.process_bill_versions(bill.id)

    assert second_result == {"bill_id": bill.id, "versions": 1}
    assert (
        BillDocument.objects.filter(bill=bill, version_label="Introduced").count() == 1
    )
    assert BillDocument.objects.filter(bill=bill, is_active_version=True).count() == 1
    assert IngestionWorkItem.objects.filter(kind="document_download").count() == 1


@pytest.mark.django_db
def test_process_bill_versions_enqueues_metadata_contract_when_no_text_versions_exist(
    monkeypatch,
):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 1",
        title="Test bill",
        status="Introduced",
        processing_status=ProcessingStatus.PROCESSING,
    )
    monkeypatch.setattr(tasks, "bill_text_list", lambda *args: [])
    monkeypatch.setattr(tasks.dispatch_ingestion_work, "delay", lambda: None)

    result = tasks.process_bill_versions(bill.id)

    assert result == {"bill_id": bill.id, "versions": 0, "fallback_enqueued": True}
    assert list(
        IngestionWorkItem.objects.filter(kind="metadata_contract").values_list(
            "payload_json", flat=True
        )
    ) == [{"bill_id": bill.id}]


@pytest.mark.django_db
def test_document_backfill_creates_fresh_work_after_a_previous_run(monkeypatch):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 1",
        title="Test bill",
        status="Introduced",
    )
    monkeypatch.setattr(tasks.dispatch_ingestion_work, "delay", lambda: None)

    tasks.backfill_process_bill_versions_for_all_bills(session=119)
    first_work = IngestionWorkItem.objects.get(kind="bill_versions")
    first_work.status = IngestionWorkStatus.SUCCEEDED
    first_work.save(update_fields=["status"])

    tasks.backfill_process_bill_versions_for_all_bills(session=119)

    assert list(
        IngestionWorkItem.objects.filter(kind="bill_versions")
        .order_by("id")
        .values_list("payload_json", "status")
    ) == [
        ({"bill_id": bill.id}, IngestionWorkStatus.SUCCEEDED),
        ({"bill_id": bill.id}, IngestionWorkStatus.PENDING),
    ]


@pytest.mark.django_db
def test_process_bill_versions_persists_document_work_before_dispatch(monkeypatch):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 1",
        title="Test bill",
        status="Introduced",
    )
    monkeypatch.setattr(
        tasks,
        "bill_text_list",
        lambda *args: [
            {
                "version_label": "Introduced",
                "url": "https://www.congress.gov/119/bills/hr1/BILLS-119hr1ih.xml",
            }
        ],
    )
    monkeypatch.setattr(tasks.dispatch_ingestion_work, "delay", lambda: None)
    monkeypatch.setattr(
        tasks.download_document,
        "apply_async",
        lambda *args, **kwargs: pytest.fail(
            "document work must be persisted before any broker publish"
        ),
    )

    tasks.process_bill_versions(bill.id)

    document = BillDocument.objects.get(bill=bill, version_label="Introduced")
    work = IngestionWorkItem.objects.get(kind="document_download")
    assert work.payload_json == {"document_id": document.id}
    assert work.status == IngestionWorkStatus.PENDING


@pytest.mark.django_db
def test_download_document_marks_retryable_s3_failures_for_celery_retry(monkeypatch):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 1",
        title="Test bill",
        status="Introduced",
    )
    document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        source_url="https://example.test/hr1.xml",
    )
    storage_error = ClientError(
        {
            "Error": {"Code": "ServiceUnavailable", "Message": "Try again"},
            "ResponseMetadata": {"HTTPStatusCode": 503},
        },
        "PutObject",
    )
    monkeypatch.setattr(
        tasks,
        "download_url",
        lambda *args: downloaded_document(b"<bill />", "application/xml"),
    )
    monkeypatch.setattr(
        tasks,
        "upload_and_metadata",
        lambda *args, **kwargs: (_ for _ in ()).throw(storage_error),
    )

    with pytest.raises(Exception) as raised:
        tasks.download_document(document.id)

    assert raised.type.__name__ == "RetryableDocumentStorageError"
    assert any(
        error.__name__ == "RetryableDocumentStorageError"
        for error in tasks.download_document.autoretry_for
    )


@pytest.mark.django_db
def test_download_document_closes_spooled_file_when_extraction_fails(monkeypatch):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 402",
        title="Bounded document bill",
        status="Introduced",
    )
    document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        source_url="https://example.test/bill.pdf",
    )
    spool = SpooledTemporaryFile(max_size=2, mode="w+b")
    spool.write(b"%PDF-test")
    spool.seek(0)
    downloaded = document_download.DownloadedDocument(
        file=spool,
        content_type="application/pdf",
        size=9,
        checksum="test-checksum",
    )
    monkeypatch.setattr(tasks, "download_url", lambda *args, **kwargs: downloaded)
    monkeypatch.setattr(
        tasks,
        "extract_document_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            document_download.MalformedDocumentError("Malformed PDF")
        ),
    )

    with pytest.raises(document_download.MalformedDocumentError, match="Malformed PDF"):
        tasks._download_document_impl(document.id)

    assert spool.closed


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("content_type", "payload"),
    [
        (
            "application/xml",
            b"<bill><legis-body><section><enum>2.</enum><header>Reports</header>"
            b"<text>The Secretary shall publish a report.</text>"
            b"</section></legis-body></bill>",
        ),
        (
            "text/html",
            b"<html><body><p>SEC. 2. REPORTS</p>"
            b"<p>The Secretary shall publish a report.</p></body></html>",
        ),
        (
            "text/plain",
            b"SEC. 2. REPORTS\nThe Secretary shall publish a report.",
        ),
    ],
)
def test_downloaded_congress_text_reaches_legal_nlp_v2(
    monkeypatch, content_type, payload
):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 1",
        title="Test bill",
        status="Introduced",
    )
    document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        source_url="https://example.test/hr1",
    )
    monkeypatch.setattr(
        tasks,
        "download_url",
        lambda *args: downloaded_document(payload, content_type),
    )
    monkeypatch.setattr(
        tasks,
        "upload_and_metadata",
        lambda *args, **kwargs: ("congress/119/hr-1/introduced", len(payload)),
    )
    monkeypatch.setattr(
        "apps.legislation.tasks.enqueue_document_contract", lambda document: None
    )

    tasks._download_document_impl(document.id)

    document.refresh_from_db()
    result = extract_contract(document=document, bill=bill)
    assert result.schema_version == "2.0-legal-nlp"
    assert result.contract_json["requirements"][0]["actor"] == "The Secretary"
    assert result.contract_json["requirements"][0]["action"] == "publish a report"


@pytest.mark.django_db
def test_downloaded_nested_congress_xml_reaches_legal_nlp_v2(monkeypatch):
    payload = (
        b"<bill><legis-body><division><enum>A</enum><header>Programs</header>"
        b"<subchapter><enum>I</enum><header>Reports</header><section>"
        b"<enum>2.</enum><header>Duties</header><subparagraph><enum>(1)</enum>"
        b"<subitem><enum>(AA)</enum><text>The Secretary shall publish a grant "
        b"report.</text></subitem></subparagraph></section></subchapter>"
        b"</division></legis-body></bill>"
    )
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 5",
        title="Nested hierarchy test bill",
        status="Introduced",
    )
    document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        source_url="https://example.test/hr5.xml",
    )
    monkeypatch.setattr(
        tasks,
        "download_url",
        lambda *args: downloaded_document(payload, "application/xml"),
    )
    monkeypatch.setattr(
        tasks,
        "upload_and_metadata",
        lambda *args, **kwargs: ("congress/119/hr-5/introduced.xml", len(payload)),
    )
    monkeypatch.setattr(
        "apps.legislation.tasks.enqueue_document_contract", lambda document: None
    )

    tasks._download_document_impl(document.id)

    document.refresh_from_db()
    result = extract_contract(document=document, bill=bill)
    assert "DIVISION A Programs" in document.extracted_text
    assert "SUBCHAPTER I Reports" in document.extracted_text
    assert "(AA) The Secretary shall publish a grant report." in document.extracted_text
    assert result.schema_version == "2.0-legal-nlp"
    assert result.contract_json["requirements"][0]["actor"] == "The Secretary"
    assert result.contract_json["requirements"][0]["action"] == (
        "publish a grant report"
    )


@pytest.mark.django_db
@pytest.mark.parametrize("content_type", [None, "application/octet-stream"])
def test_document_extension_fallback_parses_congress_xml_without_a_useful_mime_type(
    monkeypatch, content_type
):
    payload = (
        b"<bill><legis-body><section><enum>2.</enum><header>Reports</header>"
        b"<text>The Secretary shall publish a report.</text>"
        b"</section></legis-body></bill>"
    )
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 2",
        title="Test bill",
        status="Introduced",
    )
    document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        source_url="https://example.test/hr2.xml",
    )
    monkeypatch.setattr(
        tasks,
        "download_url",
        lambda *args: downloaded_document(payload, content_type),
    )
    monkeypatch.setattr(
        tasks,
        "upload_and_metadata",
        lambda *args, **kwargs: ("congress/119/hr-2/introduced.xml", len(payload)),
    )
    monkeypatch.setattr(
        "apps.legislation.tasks.enqueue_document_contract", lambda document: None
    )

    tasks._download_document_impl(document.id)

    document.refresh_from_db()
    result = extract_contract(document=document, bill=bill)
    assert document.extracted_text == (
        "SEC. 2. Reports\nThe Secretary shall publish a report."
    )
    assert result.schema_version == "2.0-legal-nlp"


@pytest.mark.django_db
def test_downloaded_xml_quoted_amendment_payload_falls_back_without_current_claims(
    monkeypatch,
):
    payload = (
        b"<bill><legis-body><section><enum>2.</enum><header>Amendments</header>"
        b"<paragraph><enum>(a)</enum><text>Section 3 of the Food Act is amended "
        b"by striking subsection (u) and inserting the following:</text>"
        b"<quoted-block><subsection><enum>(u)</enum><header>Plan</header>"
        b"<paragraph><enum>(1)</enum><text>The Secretary shall change the market "
        b"baskets.</text></paragraph></subsection></quoted-block></paragraph>"
        b"</section></legis-body></bill>"
    )
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 3",
        title="Food Amendment Act",
        status="Introduced",
    )
    document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        source_url="https://example.test/hr3.xml",
    )
    monkeypatch.setattr(
        tasks,
        "download_url",
        lambda *args: downloaded_document(payload, "application/xml"),
    )
    monkeypatch.setattr(
        tasks,
        "upload_and_metadata",
        lambda *args, **kwargs: ("congress/119/hr-3/introduced.xml", len(payload)),
    )
    monkeypatch.setattr(
        "apps.legislation.tasks.enqueue_document_contract", lambda document: None
    )

    tasks._download_document_impl(document.id)

    document.refresh_from_db()
    result = extract_contract(document=document, bill=bill)
    assert result.schema_version == "1.1-deterministic"
    assert result.fallback_reason == "no_supported_claims"


@pytest.mark.django_db
def test_downloaded_xml_direct_quoted_funding_falls_back_without_current_claims(
    monkeypatch,
):
    payload = (
        b"<bill><legis-body><section><enum>2.</enum><header>Amendments</header>"
        b"<paragraph><enum>(a)</enum><text>Section 3 of the Food Act is amended "
        b"by inserting the following:</text><quoted-block><text>There are "
        b"appropriated $100,000 for fiscal year 2027.</text></quoted-block>"
        b"</paragraph></section></legis-body></bill>"
    )
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 4",
        title="Food Amendment Act",
        status="Introduced",
    )
    document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        source_url="https://example.test/hr4.xml",
    )
    monkeypatch.setattr(
        tasks,
        "download_url",
        lambda *args: downloaded_document(payload, "application/xml"),
    )
    monkeypatch.setattr(
        tasks,
        "upload_and_metadata",
        lambda *args, **kwargs: ("congress/119/hr-4/introduced.xml", len(payload)),
    )
    monkeypatch.setattr(
        "apps.legislation.tasks.enqueue_document_contract", lambda document: None
    )

    tasks._download_document_impl(document.id)

    document.refresh_from_db()
    result = extract_contract(document=document, bill=bill)
    assert result.schema_version == "1.1-deterministic"
    assert result.fallback_reason == "no_supported_claims"


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
    assert (
        result.name,
        result.chamber,
        result.party,
        result.state,
        result.district,
    ) == (
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
    Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 303",
        title="Legislator bill",
        status="Introduced",
        sponsor=representative,
    )
    Bill.objects.create(
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
    now = datetime(2026, 1, 2, 12, 3, tzinfo=UTC)
    monkeypatch.setattr(tasks.timezone, "now", lambda: now)
    monkeypatch.setattr(
        tasks.dispatch_ingestion_work, "delay", lambda: dispatched.append(True)
    )
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
            datetime(2026, 1, 2, 12, 0, tzinfo=UTC),
            {"bill_key": "119-hr-101"},
        ),
        (
            "119-hr-303",
            IngestionWorkStatus.PENDING,
            datetime(2026, 1, 2, 12, 0, tzinfo=UTC),
            {"bill_key": "119-hr-303"},
        ),
        (
            "119-s-202",
            IngestionWorkStatus.PENDING,
            datetime(2026, 1, 2, 12, 0, tzinfo=UTC),
            {"bill_key": "119-s-202"},
        ),
    ]


@pytest.mark.django_db
def test_sync_representatives_ingests_the_complete_current_roster_before_retiring_stale_rows(
    monkeypatch,
):
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
                    "state": "California",
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
            "lastname": "Doe",
            "state": "California",
            "officialWebsiteUrl": "https://doe.house.gov",
            "depiction": {"imageUrl": "https://images.example.com/doe.jpg"},
            "terms": [{"chamber": "House of Representatives", "stateCode": "CA"}],
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
def test_sync_representatives_does_not_retire_existing_members_after_an_incomplete_pull(
    monkeypatch,
):
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
        lambda congress, current_member=True, limit=250, offset=0: (
            [{"bioguideId": "C000001", "name": "Doe, Jane"}] if offset == 0 else []
        ),
    )
    monkeypatch.setattr(
        tasks,
        "member_detail",
        lambda bioguide_id: (_ for _ in ()).throw(
            CongressAPIError("member unavailable")
        ),
    )

    with pytest.raises(CongressAPIError, match="member unavailable"):
        tasks.sync_representatives(congress=119)

    stale.refresh_from_db()
    assert stale.is_current is True
    assert not Representative.objects.filter(bioguide_id="C000001").exists()
