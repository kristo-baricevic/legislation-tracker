import pytest
from types import SimpleNamespace
from apps.campaign_finance.identity import candidate_search_name, verified_match


def representative(**changes):
    return SimpleNamespace(name="Rep. Ocasio-Cortez, Alexandria [D-NY-14]", chamber="house", state="NY", district="14", is_current=True, **changes)


def candidate(**changes):
    return {"candidate_id": "H8NY15148", "name": "OCASIO-CORTEZ, ALEXANDRIA", "office": "H", "state": "NY", "district": "14", **changes}


def test_display_markup_is_not_sent_to_fec():
    assert candidate_search_name(representative()) == "Ocasio-Cortez, Alexandria"


def test_unique_exact_identity_can_be_verified():
    assert verified_match(representative(), [candidate()], 2026, 2026) == "H8NY15148"


@pytest.mark.parametrize("rows", [[candidate(district="13")], [candidate(state="CA")], [candidate(office="S")], [candidate(name="OCASIO-CORTEZ, OTHER")], [candidate(), candidate(candidate_id="H8NY15149")]])
def test_mismatch_or_ambiguity_never_auto_verifies(rows):
    assert verified_match(representative(), rows, 2026, 2026) is None


def test_historical_period_does_not_use_current_district_as_proof():
    assert verified_match(representative(), [candidate()], 2024, 2026) is None


@pytest.mark.django_db
@pytest.mark.parametrize("matches", [True, False])
def test_existing_verified_mapping_extends_only_after_fresh_match(monkeypatch, matches):
    from datetime import datetime, timedelta, UTC
    from django.utils import timezone
    from django.contrib.auth import get_user_model
    from apps.congress.models import Representative
    from apps.research.services import request_research
    from apps.campaign_finance.research import process_finance
    from apps.campaign_finance.models import CandidateIdentity, RepresentativeCandidate
    from apps.campaign_finance.identity import resolve_candidate
    now = datetime(2028, 6, 1, tzinfo=UTC)
    monkeypatch.setattr(timezone, "now", lambda: now)
    rep = Representative.objects.create(bioguide_id="O000172", name="Alexandria Ocasio-Cortez", chamber="house", state="NY", district="14", is_current=True)
    identity = CandidateIdentity.objects.create(fec_id="H8NY15148", name=rep.name, office="H", state="NY")
    mapping = RepresentativeCandidate.objects.create(representative=rep, candidate=identity, periods=[2026], verified=True, evidence_url="https://www.fec.gov/data/candidate/H8NY15148/")
    from apps.research.models import ResearchRun
    from apps.campaign_finance.models import FinanceSnapshot
    previous_run = ResearchRun.objects.create(representative=rep, period=2026, status="partial")
    snapshot = FinanceSnapshot.objects.create(representative=rep, period=2026, run=previous_run, candidate_ids=[identity.pk], active=True)
    run = request_research(rep.pk, 2028, get_user_model().objects.create_user(username="reader").pk)
    work = run.work_item
    work.status = "processing"; work.dispatch_token = "lease"; work.lease_expires_at = now + timedelta(minutes=5); work.save()
    monkeypatch.setattr("apps.campaign_finance.research.get_page", lambda *args: {"results": [candidate(district="14" if matches else "13")], "pagination": {"pages": 1}})
    process_finance(work)
    mapping.refresh_from_db()
    assert mapping.periods == ([2026, 2028] if matches else [2026])
    assert resolve_candidate(rep.pk, 2028).status == ("verified" if matches else "not_found")
    snapshot.refresh_from_db()
    assert snapshot.active and not snapshot.invalidated


@pytest.mark.django_db
@pytest.mark.parametrize("found", [True, False])
def test_discovery_continues_verified_match_or_reports_no_match(monkeypatch, found):
    from datetime import timedelta
    from django.utils import timezone
    from django.contrib.auth import get_user_model
    from apps.congress.models import Representative
    from apps.research.services import request_research
    from apps.campaign_finance.research import process_finance
    from apps.campaign_finance.models import RepresentativeCandidate
    rep = Representative.objects.create(bioguide_id="O000172", name="Rep. Ocasio-Cortez, Alexandria [D-NY-14]", chamber="house", state="NY", district="14", is_current=True)
    run = request_research(rep.pk, 2026, get_user_model().objects.create_user(username="reader").pk)
    work = run.work_item
    work.status = "processing"; work.dispatch_token = "lease"; work.lease_expires_at = timezone.now() + timedelta(minutes=5); work.save()
    def page(path, params):
        assert params["q"] == "Ocasio-Cortez, Alexandria"
        return {"results": [candidate()] if found else [], "pagination": {"pages": 1}}
    monkeypatch.setattr("apps.campaign_finance.research.get_page", page)
    process_finance(work)
    run.refresh_from_db(); work.refresh_from_db()
    if found:
        assert run.status == "running"
        assert RepresentativeCandidate.objects.get(representative=rep).verified
        assert work.payload_json["stage"] == "finance"
    else:
        assert run.status == "partial"
        assert run.sections["finance"]["reason"] == "candidate_not_found"
