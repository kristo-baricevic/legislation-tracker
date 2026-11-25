from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.congress import committee_sync
from apps.congress.current import current_congress
from apps.congress.models import (
    Committee,
    CommitteeMembership,
    CommitteeRosterSnapshot,
    Representative,
)
from apps.ingestion.models import IngestionWorkItem
from apps.ingestion.tasks import _process_durable_work, process_ingestion_work_item

pytestmark = pytest.mark.django_db


def test_missing_rosters_queue_one_durable_shared_job():
    with patch("apps.ingestion.work_queue._request_dispatch"):
        first = committee_sync.ensure_committee_rosters()
        second = committee_sync.ensure_committee_rosters()
    assert first.pk == second.pk
    assert first.kind == "committee_roster"
    assert first.payload_json == {"congress": current_congress()}
    assert IngestionWorkItem.objects.count() == 1


def test_inflight_roster_survives_day_boundary_without_duplicate():
    first = committee_sync.ensure_committee_rosters()
    IngestionWorkItem.objects.filter(pk=first.pk).update(
        source_updated_at=timezone.now() - timedelta(days=2), status="processing"
    )
    assert committee_sync.ensure_committee_rosters().pk == first.pk
    assert IngestionWorkItem.objects.count() == 1


def test_roster_failure_is_persisted_for_retry():
    item = committee_sync.ensure_committee_rosters()
    with patch.object(
        committee_sync,
        "sync_committee_memberships",
        side_effect=RuntimeError("source offline"),
    ):
        process_ingestion_work_item(item.pk)
    item.refresh_from_db()
    assert item.status == "pending"
    assert item.attempt_count == 1
    assert "source offline" in item.last_error
    assert item.available_at > timezone.now()


def test_durable_roster_stage_calls_validated_sync():
    item = committee_sync.ensure_committee_rosters()
    with patch.object(
        committee_sync, "sync_committee_memberships", return_value=[]
    ) as sync:
        _process_durable_work(item)
    sync.assert_called_once_with(congress=current_congress())


def test_fresh_rosters_are_reused_and_stale_rosters_are_refreshed():
    congress = current_congress()
    rep = Representative.objects.create(
        bioguide_id="T000001", name="Test", chamber="house", state="NY"
    )
    committee = Committee.objects.create(
        system_code="hsag", name="Agriculture", chamber="house"
    )
    CommitteeMembership.objects.create(
        representative=rep, committee=committee, congress=congress
    )
    for chamber in ("house", "senate"):
        CommitteeRosterSnapshot.objects.create(
            congress=congress,
            chamber=chamber,
            source_url="https://example.gov/roster",
            source_hash="a" * 64,
            published_at=timezone.now(),
            assignment_count=1,
            representative_count=1,
        )
    assert committee_sync.ensure_committee_rosters() is None
    assert not IngestionWorkItem.objects.exists()
    CommitteeRosterSnapshot.objects.update(
        updated_at=timezone.now() - timedelta(days=2)
    )
    assert committee_sync.ensure_committee_rosters().kind == "committee_roster"


def test_research_request_also_queues_shared_committee_rosters():
    from django.contrib.auth import get_user_model

    from apps.research.services import request_research

    rep = Representative.objects.create(
        bioguide_id="T000001", name="Test", chamber="house", state="NY"
    )
    user = get_user_model().objects.create_user(
        username="test", email="test@example.com"
    )
    run = request_research(rep.pk, 2026, user.pk, include_history=False)
    assert run.work_item.kind == "representative_research"
    assert IngestionWorkItem.objects.filter(kind="committee_roster").count() == 1
    request_research(rep.pk, 2026, user.pk, include_history=False)
    assert IngestionWorkItem.objects.filter(kind="committee_roster").count() == 1
