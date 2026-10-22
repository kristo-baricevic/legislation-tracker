import pytest
from django.contrib.auth import get_user_model
from apps.congress.models import Representative

pytestmark = pytest.mark.django_db


def test_research_request_is_persistent_and_joins_active_run():
    from apps.research.services import request_research
    from apps.research.models import ResearchRun
    rep = Representative.objects.create(bioguide_id="T000001", name="Test", chamber="house", state="NY")
    user = get_user_model().objects.create_user(username="research", email="research@example.test", password="test")
    first = request_research(rep.pk, 2026, user.pk)
    second = request_research(rep.pk, 2026, user.pk)
    assert first.pk == second.pk
    assert ResearchRun.objects.count() == 1
    assert first.status == "queued"


def test_only_verified_period_scoped_candidate_mappings_are_resolved():
    from apps.campaign_finance.models import CandidateIdentity, RepresentativeCandidate
    from apps.campaign_finance.identity import resolve_candidate
    rep = Representative.objects.create(bioguide_id="T000002", name="Test", chamber="senate", state="NY")
    candidate = CandidateIdentity.objects.create(fec_id="S0NY00001", name="Test", office="S", state="NY")
    mapping = RepresentativeCandidate.objects.create(representative=rep, candidate=candidate, periods=[2024, 2026])
    assert resolve_candidate(rep.pk, 2026).status == "needs_review"
    mapping.verified = True
    mapping.evidence_url = "https://www.fec.gov/data/candidate/S0NY00001/"
    mapping.save()
    assert resolve_candidate(rep.pk, 2026).candidate_ids == ["S0NY00001"]
    assert resolve_candidate(rep.pk, 2022).status == "not_found"


def test_invalid_period_does_not_create_work():
    from apps.research.services import request_research
    with pytest.raises(ValueError):
        request_research(1, 2025, 1)


@pytest.mark.django_db(transaction=True)
def test_concurrent_research_requests_join_one_postgres_run(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import connection, close_old_connections
    from apps.research.services import request_research
    from apps.research.models import ResearchRun
    if connection.vendor != "postgresql":
        pytest.skip("Requires real PostgreSQL row locks")
    rep = Representative.objects.create(bioguide_id="T000009", name="Test", chamber="house", state="NY")
    user = get_user_model().objects.create_user(username="concurrent")
    monkeypatch.setattr("apps.ingestion.tasks.dispatch_ingestion_work.delay", lambda: None)
    barrier = Barrier(2)
    def request():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            return request_research(rep.pk, 2026, user.pk).pk
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(request) for _ in range(2)]
        ids = [job.result(timeout=10) for job in jobs]
    assert ids[0] == ids[1]
    assert ResearchRun.objects.count() == 1
