from datetime import timedelta
from decimal import Decimal
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


def test_all_year_donations_use_one_snapshot_per_period_and_match_pie(scope):
    from apps.research.models import ResearchRun
    from apps.campaign_finance.models import FinanceTransaction
    rep, run, snapshot, committee = scope
    for period, amount, active in [(2024, 999, False), (2024, 100, True), (2022, 200, True)]:
        old_run = ResearchRun.objects.create(representative=rep, period=period, status="partial")
        saved = FinanceSnapshot.objects.create(run=old_run, representative=rep, period=period, active=active, published_at=timezone.now())
        FinanceTransaction.objects.create(snapshot=saved, committee=committee, source_key=str(saved.pk), kind="contribution", amount=amount)
    FinanceTransaction.objects.create(snapshot=snapshot, committee=committee, source_key="current", kind="contribution", amount=300)
    url = f"/api/representatives/{rep.pk}/contributors/?all_periods=true"
    result = APIClient().get(url).data
    assert result["count"] == 3
    assert sum(Decimal(row["amount"]) for row in result["results"]) == 600
    pie = APIClient().get(url + "&by_size=true").data
    assert Decimal(pie["total"]) == 600


def test_overview_ready_while_donation_collection_continues(scope):
    from apps.campaign_finance.models import OutsideSpendingScan
    from apps.campaign_finance.progress import finance_progress
    rep, run, snapshot, committee = scope
    run.work_item.payload_json.update(stage="finance", finance_phase="receipts")
    run.work_item.save()
    snapshot.committee_links = [{"committee_id": committee.pk}]
    snapshot.save()
    totals = FinanceResearchCheckpoint.objects.create(snapshot=snapshot, committee=committee, schedule="totals")
    FinanceResearchCheckpoint.objects.create(snapshot=snapshot, committee=committee, schedule="a")
    OutsideSpendingScan.objects.create(snapshot=snapshot, candidate_id=snapshot.candidate_ids[0], complete=True)
    assert finance_progress(snapshot)["overview_ready"] is False
    totals.complete = True
    totals.save()
    progress = finance_progress(snapshot)
    assert progress["overview_ready"] is True
    assert progress["collecting"] is True


def test_research_api_reuses_saved_snapshot_unless_refresh_requested(scope):
    rep, run, snapshot, _ = scope
    run.status = "partial"
    run.save()
    snapshot.active = True
    snapshot.published_at = timezone.now()
    snapshot.save()
    client = APIClient()
    client.force_authenticate(get_user_model().objects.get(username="reader"))
    url = f"/api/representatives/{rep.pk}/research/"
    assert client.post(url, {"period": 2026}).data["id"] == str(run.pk)
    assert client.post(url, {"period": 2026, "refresh": True}).data["id"] != str(run.pk)


def test_fec_periods_are_available_before_download_and_identity_is_reused(scope, monkeypatch):
    from apps.campaign_finance.identity import resolve_candidate
    from apps.campaign_finance.periods import discover_periods
    rep, _, _, _ = scope
    mapping = RepresentativeCandidate.objects.get(representative=rep)
    calls = []
    def fetch(path, params):
        calls.append(params)
        return {"results": [{"candidate_id": mapping.candidate_id, "cycles": [2024, 2026]}], "pagination": {"pages": 1}}
    monkeypatch.setattr("apps.campaign_finance.periods.get_page", fetch)
    assert discover_periods(rep) == [2026, 2024]
    assert resolve_candidate(rep.pk, 2024).candidate_ids == [mapping.candidate_id]
    assert discover_periods(rep) == [2026, 2024]
    assert len(calls) == 1
    mapping.verified = False
    mapping.save()
    assert discover_periods(rep) == []
    assert resolve_candidate(rep.pk, 2024).candidate_ids == []


def test_research_continuation_uses_research_queue_not_bill_queue(scope, monkeypatch):
    from apps.ingestion.tasks import process_ingestion_work_item, dispatch_ingestion_work
    rep, run, snapshot, committee = scope
    work = run.work_item
    work.payload_json.update(stage="finance", finance_phase="receipts")
    work.save()
    FinanceResearchCheckpoint.objects.create(snapshot=snapshot, committee=committee, schedule="totals")
    monkeypatch.setattr("apps.campaign_finance.research.get_page", lambda *args: {"results": [], "pagination": {"pages": 1}})
    calls = []
    monkeypatch.setattr(dispatch_ingestion_work, "apply_async", lambda *args, **kwargs: calls.append(kwargs))
    process_ingestion_work_item.apply(args=[work.pk]).get()
    assert any(call.get("queue") == "research" and call.get("kwargs") == {"batch_size": 0} for call in calls)


def test_donation_sizes_sum_dollars_across_all_records_and_exact_boundaries(scope):
    from apps.campaign_finance.models import FinanceTransaction
    rep, run, snapshot, committee = scope
    for index, amount in enumerate(["199.99", "200", "999.99", "1000", "4999.99", "5000"] + ["10"] * 21):
        FinanceTransaction.objects.create(snapshot=snapshot, committee=committee, source_key=str(index), amount=amount, kind="contribution")
    FinanceTransaction.objects.create(snapshot=snapshot, committee=committee, source_key="refund", amount=9000, kind="refund")
    FinanceTransaction.objects.create(snapshot=snapshot, committee=committee, source_key="excluded", amount=9000, kind="contribution", effective=False)
    response = APIClient().get(f"/api/representatives/{rep.pk}/contributors/?period=2026&by_size=true").data
    assert [float(row["amount"]) for row in response["results"]] == [409.99, 1199.99, 5999.99, 5000]
    assert float(response["total"]) == 12609.97


def test_top_donors_aggregate_all_receipts_not_just_first_page(scope):
    from apps.campaign_finance.models import Contributor, FinanceTransaction
    rep, run, snapshot, committee = scope
    first = Contributor.objects.create(name="Repeat donor", kind="individual")
    second = Contributor.objects.create(name="Single donor", kind="committee")
    for index in range(25):
        FinanceTransaction.objects.create(snapshot=snapshot, committee=committee, contributor=first,
            source_key=str(index), amount=10, kind="contribution")
    FinanceTransaction.objects.create(snapshot=snapshot, committee=committee, contributor=second,
        source_key="single", amount=200, kind="contribution")
    FinanceTransaction.objects.create(snapshot=snapshot, committee=committee, contributor=second,
        source_key="excluded", amount=900, kind="contribution", effective=False)
    FinanceTransaction.objects.create(snapshot=snapshot, committee=committee, contributor=first,
        source_key="refund", amount=50, kind="refund")
    result = APIClient().get(f"/api/representatives/{rep.pk}/contributors/?period=2026&aggregate=true").data
    assert [(row["name"], float(row["amount"])) for row in result["results"]] == [("Repeat donor", 250), ("Single donor", 200)]


def test_available_periods_exclude_empty_invalidated_and_unpublished_data(scope):
    from apps.research.models import ResearchRun
    rep, run, draft, committee = scope
    for period in [2024, 2022, 2020, 2018]:
        old_run = ResearchRun.objects.create(representative=rep, period=period, status="partial")
        snapshot = FinanceSnapshot.objects.create(run=old_run, representative=rep, period=period,
            active=period != 2018, invalidated=period == 2020, published_at=timezone.now())
        FinanceResearchCheckpoint.objects.create(snapshot=snapshot, committee=committee, schedule="totals", complete=True,
            source_totals={"records": [] if period == 2022 else [{"receipts": 0}]})
    url = f"/api/representatives/{rep.pk}/research/?period=2026"
    assert APIClient().get(url).data["available_periods"] == [2024]
    FinanceResearchCheckpoint.objects.create(snapshot=draft, committee=committee, schedule="totals", complete=True,
        source_totals={"records": [{"receipts": 1200}]})
    assert APIClient().get(url).data["available_periods"] == [2026, 2024]
    from apps.campaign_finance.models import FinanceTransaction
    empty_snapshot = FinanceSnapshot.objects.get(representative=rep, period=2022)
    FinanceTransaction.objects.create(snapshot=empty_snapshot, committee=committee, source_key="refund",
        amount=-50, kind="refund", effective=True)
    assert APIClient().get(url).data["available_periods"] == [2026, 2024, 2022]
    FinanceTransaction.objects.filter(snapshot=empty_snapshot).update(effective=False)
    assert APIClient().get(url).data["available_periods"] == [2026, 2024]


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
    from apps.campaign_finance.models import OutsideSpendingScan
    OutsideSpendingScan.objects.create(snapshot=snapshot, candidate_id=snapshot.candidate_ids[0], complete=True)
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
        if path.endswith("/by_candidate/"):
            return {"results": [], "pagination": {"pages": 0}}
        assert params["line_number"] in {"F3-11B", "F3-11C", "F3-20B", "F3-20C", "F3-11AI", "F3-20A"}
        return {"results": [], "pagination": {"last_indexes": {}}}
    monkeypatch.setattr("apps.campaign_finance.research.get_page", upstream)
    for _ in range(13):
        process_ingestion_work_item.apply(args=[work.pk]).get()
        work.refresh_from_db()
        if work.status == "succeeded":
            break
    assert calls == ["candidate/H0NY00001/committees/", "schedules/schedule_e/by_candidate/", "committee/C00000001/totals/", "F3-11B", "F3-11C", "F3-20B", "F3-20C", "F3-11AI", "F3-20A"]
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
