from datetime import timedelta
import pytest
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.congress.models import Representative
from apps.research.services import request_research
from apps.campaign_finance.models import CandidateIdentity, RepresentativeCandidate, FinanceSnapshot, CampaignCommittee, FinanceResearchCheckpoint
from apps.campaign_finance.research import process_finance, persist_page
from apps.campaign_finance.fec_client import receipt_parameters

pytestmark = pytest.mark.django_db


@pytest.fixture
def scope():
    rep = Representative.objects.create(bioguide_id="T000090", name="Test", chamber="house", state="NY")
    candidate = CandidateIdentity.objects.create(fec_id="H0NY00001", name="Test", office="H", state="NY")
    RepresentativeCandidate.objects.create(representative=rep, candidate=candidate, verified=True, periods=[2026], evidence_url="https://www.fec.gov/")
    run = request_research(rep.pk, 2026, get_user_model().objects.create_user(username="reader").pk)
    run.status = "running"
    run.save()
    snapshot = FinanceSnapshot.objects.create(run=run, representative=rep, period=2026, candidate_ids=[candidate.pk])
    committee = CampaignCommittee.objects.create(fec_id="C00000001", name="Campaign")
    return rep, run, snapshot, committee


def test_totals_are_downloaded_before_receipts(scope, monkeypatch):
    rep, run, snapshot, committee = scope
    FinanceResearchCheckpoint.objects.create(snapshot=snapshot, committee=committee, schedule="a")
    totals = FinanceResearchCheckpoint.objects.create(snapshot=snapshot, committee=committee, schedule="totals")
    work = run.work_item
    work.payload_json.update(stage="finance", finance_phase="receipts")
    work.status = "processing"
    work.dispatch_token = "owner"
    work.lease_expires_at = timezone.now() + timedelta(minutes=5)
    work.save()
    def upstream(path, params):
        assert path == "committee/C00000001/totals/"
        return {"results": [{"receipts": 1200, "disbursements": 300}], "pagination": {"pages": 1}}
    monkeypatch.setattr("apps.campaign_finance.research.get_page", upstream)
    process_finance(work)
    totals.refresh_from_db()
    assert totals.complete
    response = APIClient().get(f"/api/representatives/{rep.pk}/research/?period=2026").data
    assert response["finance_progress"]["totals_loaded"] == 1
    assert response["finance_progress"]["official_totals"][0]["records"][0]["receipts"] == 1200
    assert response["snapshot"] == str(snapshot.pk)
    assert response["finance_progress"]["collecting"] is True


def test_partial_donors_visible_but_not_published_and_revocation_hides_them(scope):
    rep, run, snapshot, committee = scope
    cp = FinanceResearchCheckpoint.objects.create(snapshot=snapshot, committee=committee, schedule="a")
    persist_page(cp, {"results": [{"sub_id": "1", "committee_id": committee.pk, "contributor_id": "C00000002", "contributor_name": "Example PAC", "entity_type": "PAC", "line_number": "11C", "contribution_receipt_amount": 125}], "pagination": {"last_indexes": {"last_index": "1"}}})
    url = f"/api/representatives/{rep.pk}/contributors/?period=2026&snapshot={snapshot.pk}"
    result = APIClient().get(url)
    assert result.status_code == 200
    assert result.data["status"] == "collecting"
    assert result.data["results"][0]["amount"] == "125.00"
    connections = APIClient().get(f"/api/representatives/{rep.pk}/connections/?period=2026").data
    assert connections["finance_status"] == "collecting"
    assert connections["donors"][0]["amount"] == "125"
    snapshot.refresh_from_db()
    assert snapshot.published_at is None and not snapshot.active
    snapshot.invalidated = True
    snapshot.save()
    assert APIClient().get(url).status_code == 404


def test_refresh_keeps_published_snapshot_and_hides_unrelated_draft(scope):
    rep, run, draft, committee = scope
    from apps.research.models import ResearchRun
    old_run = ResearchRun.objects.create(representative=rep, period=2026, status="partial")
    old = FinanceSnapshot.objects.create(run=old_run, representative=rep, period=2026, active=True, published_at=timezone.now())
    # Make the running draft the latest request.
    ResearchRun.objects.filter(pk=old_run.pk).update(created_at=run.created_at - timedelta(days=1))
    response = APIClient().get(f"/api/representatives/{rep.pk}/research/?period=2026").data
    assert response["snapshot"] == str(old.pk)
    old.active = False; old.published_at = None; old.save()
    assert APIClient().get(f"/api/representatives/{rep.pk}/contributors/?period=2026&snapshot={old.pk}").status_code == 404


@pytest.mark.parametrize("schedule,line,date", [("a_11b", "F3-11B", "last_contribution_receipt_date"), ("a_11c", "F3-11C", "last_contribution_receipt_date"), ("b_20b", "F3-20B", "last_disbursement_date"), ("b_20c", "F3-20C", "last_disbursement_date")])
def test_each_filtered_stream_keeps_its_own_cursor(schedule, line, date):
    result = receipt_parameters("C00000001", 2026, {date: "2026-06-01", "last_index": "23"}, schedule)
    assert result["line_number"] == line
    assert result[date] == "2026-06-01"
    assert result["last_index"] == "23"


def test_legacy_cursor_is_not_silently_switched_to_filtered_query():
    assert "line_number" not in receipt_parameters("C00000001", 2026, {"last_index": "3"}, "a")


def test_new_scan_fetches_totals_and_committee_donors_before_individuals(scope, monkeypatch):
    rep, run, snapshot, committee = scope
    snapshot.delete()  # fixture draft only; exercise production snapshot creation
    from apps.ingestion.tasks import process_ingestion_work_item
    work = run.work_item
    work.payload_json.update(stage="finance")
    work.save()
    calls = []
    def upstream(path, params):
        calls.append(params.get("line_number", path))
        if path.endswith("/committees/"):
            return {"results": [{"committee_id": committee.pk, "designation": "P", "name": "Campaign"}], "pagination": {"pages": 1}}
        if path.endswith("/totals/"):
            return {"results": [{"receipts": 1000}], "pagination": {"pages": 1}}
        assert params["line_number"] in {"F3-11B", "F3-11C", "F3-20B", "F3-20C", "F3-11AI", "F3-20A"}
        return {"results": [], "pagination": {"last_indexes": {}}}
    monkeypatch.setattr("apps.campaign_finance.research.get_page", upstream)
    for _ in range(10):
        process_ingestion_work_item.apply(args=[work.pk]).get()
        work.refresh_from_db()
        if work.status == "succeeded":
            break
    assert calls == ["candidate/H0NY00001/committees/", "committee/C00000001/totals/", "F3-11B", "F3-11C", "F3-20B", "F3-20C", "F3-11AI", "F3-20A"]
    saved = FinanceSnapshot.objects.get(run=run)
    assert saved.active and saved.published_at
    assert saved.normalization_version == "fec-2-filtered"


def test_dead_job_does_not_expose_draft_as_success(scope):
    rep, run, snapshot, committee = scope
    work = run.work_item
    work.status = "dead"; work.save()
    url = f"/api/representatives/{rep.pk}"
    assert APIClient().get(f"{url}/research/?period=2026").data["snapshot"] is None
    assert APIClient().get(f"{url}/contributors/?period=2026&snapshot={snapshot.pk}").status_code == 404
