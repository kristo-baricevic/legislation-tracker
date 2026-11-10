from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.congress.models import Representative
from apps.campaign_finance.models import CandidateIdentity, RepresentativeCandidate, FinanceSnapshot, OutsideSpendingScan
from apps.ingestion.models import IngestionWorkItem
from apps.research.models import ResearchRun
from apps.research.services import request_research
from apps.research.tasks import process_research

pytestmark = pytest.mark.django_db


@pytest.fixture
def history_scope(monkeypatch):
    from django.core.cache import cache
    cache.delete('fec-period-discovery:S6IL00151')
    user = get_user_model().objects.create_user(username='history-reader')
    rep = Representative.objects.create(bioguide_id='D000563', name='Durbin, Richard', chamber='senate', state='IL')
    candidate = CandidateIdentity.objects.create(fec_id='S6IL00151', name='Durbin, Richard', office='S', state='IL')
    RepresentativeCandidate.objects.create(representative=rep, candidate=candidate, periods=[2026], verified=True,
        evidence_url='https://www.fec.gov/data/candidate/S6IL00151/')
    monkeypatch.setattr('apps.campaign_finance.periods.get_page', lambda *a: {
        'results': [{'candidate_id': 'S6IL00151', 'cycles': [2014, 2016, 2018, 2020, 2022, 2024, 2026]}],
        'pagination': {'pages': 1}})
    return rep, user


def run_history(rep):
    work = IngestionWorkItem.objects.get(kind='representative_research', payload_json__stage='history')
    work.status = 'processing'
    work.dispatch_token = 'history-test'
    work.lease_expires_at = timezone.now() + timedelta(minutes=5)
    work.save()
    process_research(work)
    return work


def test_one_research_downloads_last_ten_years_not_just_selected_year(history_scope):
    rep, user = history_scope
    request_research(rep.pk, 2026, user.pk)
    run_history(rep)
    assert set(ResearchRun.objects.filter(representative=rep).values_list('period', flat=True)) == {2018, 2020, 2022, 2024, 2026}
    for run in ResearchRun.objects.filter(representative=rep).exclude(period=2026):
        assert run.work_item.payload_json['stage'] == 'finance'
    # A redelivery must neither duplicate runs nor recursively fan out histories.
    run_history(rep)
    assert ResearchRun.objects.filter(representative=rep).count() == 5
    assert IngestionWorkItem.objects.filter(payload_json__stage='history').count() == 1


def test_saved_selected_year_still_queues_history_and_reuses_saved_older_year(history_scope):
    rep, user = history_scope
    for period in (2020, 2026):
        run = ResearchRun.objects.create(representative=rep, requester=user, period=period, status='partial')
        snapshot = FinanceSnapshot.objects.create(representative=rep, run=run, period=period, active=True,
            published_at=timezone.now(), candidate_ids=['S6IL00151'])
        OutsideSpendingScan.objects.create(snapshot=snapshot, candidate_id='S6IL00151', complete=True)
    returned = request_research(rep.pk, 2026, user.pk, refresh=False)
    assert returned.pk == run.pk
    run_history(rep)
    assert ResearchRun.objects.filter(representative=rep, period=2020).count() == 1
    assert ResearchRun.objects.filter(representative=rep).count() == 5


def test_backfill_researches_saved_cycle_missing_outside_spending(history_scope):
    rep, user = history_scope
    old = ResearchRun.objects.create(representative=rep, requester=user, period=2020, status='partial')
    snapshot = FinanceSnapshot.objects.create(representative=rep, run=old, period=2020, active=True,
        published_at=timezone.now(), candidate_ids=['S6IL00151'])
    request_research(rep.pk, 2026, user.pk)
    run_history(rep)
    replacement = ResearchRun.objects.get(representative=rep, period=2020, status='queued')
    assert replacement.work_item.payload_json['stage'] == 'finance'
    snapshot.refresh_from_db()
    assert snapshot.active


def test_history_does_not_queue_records_after_identity_revoked(history_scope):
    rep, user = history_scope
    request_research(rep.pk, 2026, user.pk)
    mapping = RepresentativeCandidate.objects.get(representative=rep)
    mapping.verified = False
    mapping.save()
    run_history(rep)
    assert ResearchRun.objects.filter(representative=rep).count() == 1


def test_all_year_spending_keeps_polling_for_history_before_snapshots_exist(history_scope):
    from rest_framework.test import APIClient
    from apps.campaign_finance.models import OutsideSpendingScan
    rep, user = history_scope
    run = request_research(rep.pk, 2026, user.pk)
    snapshot = FinanceSnapshot.objects.create(representative=rep, run=run, period=2026, candidate_ids=['S6IL00151'])
    OutsideSpendingScan.objects.create(snapshot=snapshot, candidate_id='S6IL00151', complete=True)
    url = f'/api/representatives/{rep.pk}/outside-spending/?all_periods=true'
    assert APIClient().get(url).data['status'] == 'collecting'
    work = run_history(rep)
    work.status = 'succeeded'
    work.save()
    assert APIClient().get(url).data['status'] == 'collecting'


def test_history_discovery_failure_is_retriable_not_silent_success(history_scope, monkeypatch):
    from apps.campaign_finance.fec_client import FECError
    rep, user = history_scope
    request_research(rep.pk, 2026, user.pk)
    def unavailable(*args):
        raise FECError('fec_source_unavailable', 503)
    monkeypatch.setattr('apps.campaign_finance.periods.get_page', unavailable)
    with pytest.raises(FECError):
        run_history(rep)
    assert ResearchRun.objects.filter(representative=rep).count() == 1


def test_overviews_are_dispatched_before_donation_detail_backlogs(history_scope, monkeypatch):
    from apps.ingestion.tasks import dispatch_ingestion_work, process_ingestion_work_item
    rep, user = history_scope
    run = request_research(rep.pk, 2026, user.pk)
    # The older work has already reached slow itemized receipts.
    run.work_item.payload_json.update(stage='finance', finance_phase='receipts')
    run.work_item.save()
    monkeypatch.setattr(process_ingestion_work_item, 'apply_async', lambda *a, **k: type('Result', (), {'id': 'dispatch-test'})())
    dispatch_ingestion_work(batch_size=0)
    history = IngestionWorkItem.objects.get(payload_json__stage='history')
    run.work_item.refresh_from_db()
    assert history.status == 'dispatched'
    assert run.work_item.status == 'pending'


def test_historical_finance_job_reports_running_when_it_starts(history_scope, monkeypatch):
    rep, user = history_scope
    request_research(rep.pk, 2026, user.pk)
    run_history(rep)
    run = ResearchRun.objects.get(representative=rep, period=2020)
    work = run.work_item
    work.status = 'processing'
    work.dispatch_token = 'period-test'
    work.lease_expires_at = timezone.now() + timedelta(minutes=5)
    work.save()
    monkeypatch.setattr('apps.campaign_finance.research.get_page', lambda *a: {'results': [], 'pagination': {'pages': 0}})
    process_research(work)
    run.refresh_from_db()
    assert run.status == 'running'
    assert run.sections['finance']['status'] == 'running'
