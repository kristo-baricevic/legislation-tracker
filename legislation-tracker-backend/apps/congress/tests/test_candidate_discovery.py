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
