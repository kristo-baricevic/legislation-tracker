from datetime import timedelta
from decimal import Decimal
import pytest
from django.utils import timezone
from django.contrib.auth import get_user_model
from apps.congress.models import Representative
from apps.research.models import ResearchRun
from apps.research.services import request_research
from apps.campaign_finance.models import CandidateIdentity, RepresentativeCandidate, FinanceSnapshot

pytestmark = pytest.mark.django_db


def test_new_mapping_invalidates_old_scope_and_revocation_cannot_be_published(monkeypatch):
    from apps.campaign_finance.research import process_finance
    rep = Representative.objects.create(bioguide_id="T000031", name="Test", chamber="house", state="NY")
    candidate = CandidateIdentity.objects.create(fec_id="H0NY00001", name="Test", office="H", state="NY")
    mapping = RepresentativeCandidate.objects.create(representative=rep, candidate=candidate, periods=[2026], verified=True, evidence_url="https://www.fec.gov/data/candidate/H0NY00001/")
    run = request_research(rep.pk, 2026, get_user_model().objects.create_user(username="reader").pk)
    snapshot = FinanceSnapshot.objects.create(run=run, representative=rep, period=2026, candidate_ids=[candidate.pk])
    mapping.verified = False
    mapping.save()
    mapping.verified = True
    mapping.save()
    work = run.work_item
    work.payload_json.update(stage="finance", finance_phase="receipts")
    work.status = "processing"
    work.dispatch_token = "owner"
    work.lease_expires_at = timezone.now() + timedelta(minutes=5)
    work.save()
    with pytest.raises(ValueError, match="identity_changed"):
        process_finance(work)
    snapshot.refresh_from_db()
    assert not snapshot.active
    other = CandidateIdentity.objects.create(fec_id="H0NY00002", name="Test", office="H", state="NY")
    snapshot.invalidated = False
    snapshot.save()
    RepresentativeCandidate.objects.create(representative=rep, candidate=other, periods=[2026])
    snapshot.refresh_from_db()
    assert snapshot.invalidated


def test_retry_after_http_date_is_honored():
    from apps.campaign_finance.fec_client import retry_after
    from email.utils import format_datetime
    now = timezone.now().replace(microsecond=0)
    assert retry_after(format_datetime(now + timedelta(seconds=120)), now=now) == 120
    assert retry_after("15", now=now) == 15
    assert retry_after("invalid", now=now) is None


def test_recorded_amended_receipts_and_refunds_have_separate_totals():
    import json
    from pathlib import Path
    from apps.campaign_finance.normalization import normalize_receipt, normalize_refund
    data = json.loads((Path(__file__).parent / "fixtures/fec_recorded_2026_10_22.json").read_text())
    receipts = [normalize_receipt(row) for row in data["committee_receipts"]["results"]]
    refunds = [normalize_refund(row) for row in data["refunds"]["results"]]
    assert sum(row["amount"] for row in receipts if row["effective"]) == Decimal("7000")
    assert sum(row["amount"] for row in refunds if row["effective"]) == Decimal("400")
    assert all(row["kind"] == "refund" for row in refunds)
    assert all(row["source_metadata"]["amendment_indicator"] == "A" for row in receipts)
    assert not {row["identity_key"] for row in refunds} & {row["identity_key"] for row in receipts}


@pytest.mark.parametrize("status,expected", [(429, "retrying"), (503, "retrying"), (401, "dead")])
def test_research_transport_failure_keeps_work_and_reports_terminal_errors(monkeypatch, status, expected):
    from apps.ingestion.tasks import process_ingestion_work_item
    from apps.campaign_finance.fec_client import FECError
    from rest_framework.test import APIClient
    rep = Representative.objects.create(bioguide_id="T000060", name="Test", chamber="house", state="NY")
    run = request_research(rep.pk, 2026, get_user_model().objects.create_user(username="reader").pk)
    work = run.work_item
    work.payload_json["stage"] = "finance"
    work.save()
    monkeypatch.setattr("apps.campaign_finance.research.get_page", lambda *a, **k: (_ for _ in ()).throw(FECError("fec_source_unavailable", status, 120)))
    before = timezone.now()
    result = process_ingestion_work_item.apply(args=[work.pk]).get()
    assert result["status"] == expected
    work.refresh_from_db()
    if status == 429:
        assert work.available_at >= before + timedelta(seconds=120)
        assert work.attempt_count == 0
    if expected == "dead":
        assert APIClient().get(f"/api/representatives/{rep.pk}/research/").data["status"] == "failed"


def test_broker_outage_does_not_lose_research_request(monkeypatch, django_capture_on_commit_callbacks):
    rep = Representative.objects.create(bioguide_id="T000061", name="Test", chamber="house", state="NY")
    user = get_user_model().objects.create_user(username="reader")
    monkeypatch.setattr("apps.ingestion.tasks.dispatch_ingestion_work.delay", lambda: (_ for _ in ()).throw(ConnectionError("broker unavailable")))
    with django_capture_on_commit_callbacks(execute=True):
        run = request_research(rep.pk, 2026, user.pk)
    run.refresh_from_db()
    assert run.work_item.status == "pending"
    assert request_research(rep.pk, 2026, user.pk).pk == run.pk


def test_changed_source_policy_during_fetch_cannot_relabel_evidence(monkeypatch, settings):
    from apps.research.models import ResearchSourcePolicy, RepresentativeBiography
    from apps.research.tasks import process_research
    settings.CONGRESS_API_KEY = ""
    settings.LEGISLATOR_WIKIPEDIA_ENABLED = False
    settings.FEC_API_KEY = ""
    rep = Representative.objects.create(bioguide_id="T000062", name="Jane Doe", chamber="house", state="NY", official_website_url="https://jane.house.gov")
    policy = ResearchSourcePolicy.objects.create(representative=rep, kind="biography", url="https://jane.house.gov/about", element_id="bio", identity_text="Jane Doe", approved=True, attribution="Office", license="Permission")
    run = request_research(rep.pk, 2026, get_user_model().objects.create_user(username="reader").pk)
    work = run.work_item
    work.status = "processing"
    work.dispatch_token = "owner"
    work.lease_expires_at = timezone.now() + timedelta(minutes=5)
    work.save()
    def fetch(old_policy):
        ResearchSourcePolicy.objects.filter(pk=old_policy.pk).update(url="https://jane.house.gov/other")
        return "Jane Doe served as a teacher. She served in local government."
    monkeypatch.setattr("apps.research.tasks.fetch_official_biography", fetch)
    process_research(work)
    assert not RepresentativeBiography.objects.filter(source__provider="official_member").exists()


def test_old_run_replay_cannot_publish_after_new_request(monkeypatch, settings):
    from apps.research.tasks import process_research
    settings.CONGRESS_API_KEY = ""
    settings.LEGISLATOR_WIKIPEDIA_ENABLED = False
    settings.FEC_API_KEY = ""
    rep = Representative.objects.create(bioguide_id="T000063", name="Test", chamber="house", state="NY")
    user = get_user_model().objects.create_user(username="reader")
    old = request_research(rep.pk, 2026, user.pk)
    old.status = "failed"
    old.save()
    new = request_research(rep.pk, 2026, user.pk)
    work = old.work_item
    work.status = "processing"
    work.dispatch_token = "replay"
    work.lease_expires_at = timezone.now() + timedelta(minutes=5)
    work.save()
    assert process_research(work)["status"] == "superseded"
    new.refresh_from_db()
    assert new.status == "queued"


def test_moving_candidate_mapping_invalidates_both_representatives():
    first = Representative.objects.create(bioguide_id="T000064", name="First", chamber="house", state="NY")
    second = Representative.objects.create(bioguide_id="T000065", name="Second", chamber="house", state="NY")
    candidate = CandidateIdentity.objects.create(fec_id="H0NY00001", name="Test", office="H", state="NY")
    mapping = RepresentativeCandidate.objects.create(representative=first, candidate=candidate, periods=[2026], verified=True, evidence_url="https://www.fec.gov/")
    snapshots = [FinanceSnapshot.objects.create(run=ResearchRun.objects.create(representative=rep, period=2026, status="partial"), representative=rep, period=2026, active=True) for rep in (first, second)]
    mapping.representative = second
    mapping.save()
    for snapshot in snapshots:
        snapshot.refresh_from_db()
        assert snapshot.invalidated and not snapshot.active
