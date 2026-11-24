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


@pytest.mark.parametrize("title", ["REP.", "SEN.", "Representative", "Senator", "HON."])
def test_provider_titles_are_not_name_parts(title):
    assert verified_match(representative(), [candidate(name=f"OCASIO-CORTEZ, ALEXANDRIA {title}")], 2026, 2026) == "H8NY15148"


@pytest.mark.parametrize("title", ["Rep", "Sen", "Del"])
def test_abbreviated_prefix_without_period_is_normalized(title):
    from apps.congress.names import normalize_person_name
    assert normalize_person_name(f"{title} Smith, Jane [D-NY-14]") == "Smith, Jane"
    assert normalize_person_name("Amit Sen") == "Amit Sen"


def test_normalization_preserves_real_name_parts():
    from apps.congress.names import normalize_person_name
    assert normalize_person_name("Rep. O’Neill-Smith, José B. Jr. [D-NY-14]") == "O’Neill-Smith, José B. Jr."
    assert normalize_person_name("Sen, Amit") == "Sen, Amit"
    assert normalize_person_name("Robert B. Aderholt REP.") == "Robert B. Aderholt"
    assert normalize_person_name(normalize_person_name("Rep. Jane Doe [D-NY-1]")) == "Jane Doe"


@pytest.mark.django_db
def test_names_are_normalized_at_sponsor_and_directory_ingestion():
    from apps.ingestion.tasks import get_or_create_representative_from_sponsor, _member_profile
    rep = get_or_create_representative_from_sponsor({"bioguideId": "A000055", "fullName": "Rep. Aderholt, Robert B. [R-AL-4]", "state": "AL", "district": 4})
    assert rep.name == "Aderholt, Robert B."
    assert rep.chamber == "house"
    profile = _member_profile({"bioguideId": "A000055", "name": "Aderholt, Robert B. REP."}, {})
    assert profile["name"] == "Aderholt, Robert B."


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
@pytest.mark.parametrize("previously_blocked", [True, False, "missing_evidence"])
def test_discovery_continues_verified_match_or_reports_no_match(monkeypatch, found, previously_blocked):
    from datetime import timedelta
    from django.utils import timezone
    from django.contrib.auth import get_user_model
    from apps.congress.models import Representative
    from apps.research.services import request_research
    from apps.campaign_finance.research import process_finance
    from apps.campaign_finance.models import RepresentativeCandidate, CandidateIdentity
    rep = Representative.objects.create(bioguide_id="O000172", name="Rep. Ocasio-Cortez, Alexandria [D-NY-14]", chamber="house", state="NY", district="14", is_current=True)
    if previously_blocked:
        identity = CandidateIdentity.objects.create(fec_id="H8NY15148", name="OCASIO-CORTEZ, ALEXANDRIA REP.", office="H", state="NY")
        RepresentativeCandidate.objects.create(representative=rep, candidate=identity, periods=[2024, 2026], verified=previously_blocked == "missing_evidence", evidence_url="")
    run = request_research(rep.pk, 2026, get_user_model().objects.create_user(username="reader").pk)
    work = run.work_item
    work.status = "processing"; work.dispatch_token = "lease"; work.lease_expires_at = timezone.now() + timedelta(minutes=5); work.save()
    def page(path, params):
        assert params["q"] in {"Ocasio-Cortez, Alexandria", "Ocasio-Cortez"}
        return {"results": [candidate()] if found else [], "pagination": {"pages": 1}}
    monkeypatch.setattr("apps.campaign_finance.research.get_page", page)
    process_finance(work)
    run.refresh_from_db(); work.refresh_from_db()
    if found:
        assert run.status == "running"
        mapping = RepresentativeCandidate.objects.get(representative=rep)
        assert mapping.verified and mapping.evidence_url
        assert mapping.periods == [2026]
        assert work.payload_json["stage"] == "finance"
    else:
        assert run.status == "partial"
        assert run.sections["finance"]["reason"] == "candidate_not_found"

@pytest.mark.django_db
@pytest.mark.parametrize("legacy_suggestion", [None, "unreviewed", "revoked"])
def test_fuzzy_discovery_requires_explicit_cycle_scoped_confirmation(monkeypatch, legacy_suggestion):
    from datetime import timedelta
    from django.utils import timezone
    from django.contrib.auth import get_user_model
    from rest_framework.test import APIClient
    from apps.congress.models import Representative
    from apps.campaign_finance.identity import resolve_candidate
    from apps.campaign_finance.models import FinanceSnapshot
    from apps.campaign_finance.research import process_finance
    from apps.research.services import request_research

    rep = Representative.objects.create(name='García, Jesús G. “Chuy”', bioguide_id="G000586",
        chamber="house", state="IL", district="4")
    user = get_user_model().objects.create_user(username="reader")
    run = request_research(rep.pk, 2026, user.pk)
    work = run.work_item
    work.status = "processing"
    work.dispatch_token = "lease"
    work.lease_expires_at = timezone.now() + timedelta(minutes=5)
    work.save()
    queries = []
    def page(path, params):
        assert path == "candidates/search/"
        queries.append(params["q"])
        rows = [] if params["q"] != "Garcia" else [
            candidate(name="GARCIA, JESUS", candidate_id="H8IL04134", state="IL", district="04"),
            candidate(name="GARCIA, PATTY", candidate_id="H6IL04153", state="IL", district="04")]
        return {"results": rows, "pagination": {"pages": 1}}
    monkeypatch.setattr("apps.campaign_finance.research.get_page", page)
    process_finance(work)
    run.refresh_from_db()
    assert queries == [rep.name, "Garcia"]
    assert [r["candidate_id"] for r in run.sections["finance"]["candidates"]] == ["H8IL04134"]
    assert resolve_candidate(rep.pk, 2026).status == "not_found"
    assert not FinanceSnapshot.objects.filter(run=run).exists()
    client = APIClient()
    url = f"/api/representatives/{rep.pk}/research-runs/{run.pk}/confirm-candidate/"
    choice = {"candidate_id": "H8IL04134"}
    if legacy_suggestion:
        from apps.campaign_finance.models import CandidateIdentity, RepresentativeCandidate
        suggestion = CandidateIdentity.objects.create(fec_id=choice["candidate_id"], office="H", state="IL")
        mapping = RepresentativeCandidate.objects.create(representative=rep, candidate=suggestion, periods=[2024, 2026],
            evidence_url="https://www.fec.gov/data/candidate/H8IL04134/")
        if legacy_suggestion == "revoked":
            from django.contrib import admin
            admin.site._registry[RepresentativeCandidate].save_model(None, mapping, None, True)
    assert client.post(url, choice).status_code in (401, 403)
    client.force_authenticate(user)
    assert client.post(url, {"candidate_id": "H6IL04153"}).status_code == 400
    if legacy_suggestion == "revoked":
        assert client.post(url, choice).status_code == 409
        assert resolve_candidate(rep.pk, 2026).status == "needs_review"
        return
    assert client.post(url, choice).status_code == 202
    assert resolve_candidate(rep.pk, 2026).candidate_ids == ["H8IL04134"]
    assert resolve_candidate(rep.pk, 2024).status == "not_found"
    assert client.post(url, choice).status_code == 409
    from apps.campaign_finance.models import RepresentativeCandidate
    mapping = RepresentativeCandidate.objects.get(representative=rep, candidate_id=choice["candidate_id"])
    mapping.verified = False
    mapping.save()
    mapping.refresh_from_db()
    assert mapping.revoked
    assert resolve_candidate(rep.pk, 2026).status == "needs_review"
