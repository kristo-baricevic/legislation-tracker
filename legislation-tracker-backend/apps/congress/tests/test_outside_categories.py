from decimal import Decimal
import pytest
from django.utils import timezone
from apps.congress.models import Representative
from apps.research.models import ResearchRun
from apps.campaign_finance.models import FinanceSnapshot, OutsideSpendingScan
from apps.campaign_finance.outside import persist_outside_page, normalize_outside_total

pytestmark = pytest.mark.django_db


def test_communication_transaction_codes_keep_distinct_source_groups():
    from rest_framework.test import APIClient
    rep = Representative.objects.create(bioguide_id='T000002', name='Example')
    run = ResearchRun.objects.create(representative=rep, period=2022, status='partial')
    snapshot = FinanceSnapshot.objects.create(run=run, representative=rep, period=2022,
        active=True, published_at=timezone.now(), candidate_ids=['H8IL06139'])
    scan = OutsideSpendingScan.objects.create(snapshot=snapshot, candidate_id='H8IL06139', category='communication')
    rows = [dict(candidate_id='H8IL06139', cycle=2022, committee_id='C70000112',
        support_oppose_indicator=side, total=amount) for side, amount in [('24F', '375.00'), ('S', '100.00'), ('24N', '50.00')]]
    persist_outside_page(scan, {'results': rows, 'pagination': {'page': 1, 'pages': 1, 'count': 3}})
    assert scan.totals.count() == 3
    data = APIClient().get(f'/api/representatives/{rep.pk}/outside-spending/?period=2022&position=S').data
    assert Decimal(data['support']) == 475
    assert Decimal(data['oppose']) == 50
    assert data['count'] == 2
    assert all(row['position'] == 'S' for row in data['results'])


def test_durbin_missing_communication_costs_are_separate_from_schedule_e():
    rep = Representative.objects.create(bioguide_id='D000563', name='Dick Durbin')
    run = ResearchRun.objects.create(representative=rep, period=2020, status='partial')
    snapshot = FinanceSnapshot.objects.create(run=run, representative=rep, period=2020,
        active=True, published_at=timezone.now(), candidate_ids=['S6IL00151'])
    for category, rows in [('independent', [('C00571588', 'O', '77000.00')]),
                           ('communication', [('C70002472', 'S', '11690.78'), ('C70002563', 'S', '52833.72')]),
                           ('electioneering', [])]:
        scan = OutsideSpendingScan.objects.create(snapshot=snapshot, candidate_id='S6IL00151', category=category)
        persist_outside_page(scan, {'results': [dict(candidate_id='S6IL00151', cycle=2020,
            committee_id=spender, support_oppose_indicator=side, total=amount) for spender, side, amount in rows],
            'pagination': {'page': 1, 'pages': 1 if rows else 0, 'count': len(rows)}})
    assert snapshot.outside_scans.count() == 3
    scan = snapshot.outside_scans.get(category='communication')
    assert sum(scan.totals.values_list('amount', flat=True)) == Decimal('64524.50')
    assert snapshot.transactions.count() == 0


def test_electioneering_is_a_mention_not_inferred_support():
    row = {'candidate_id': 'P80001571', 'cycle': 2020, 'committee_id': 'C30000848',
           'committee_name': 'NATIONAL EDUCATION ASSOCIATION', 'total': '194899.15'}
    result = normalize_outside_total(row, 'P80001571', 2020, category='electioneering')
    assert result['position'] == 'M'
    assert result['amount'] == Decimal('194899.15')
    with pytest.raises(ValueError):
        normalize_outside_total(row, 'P80001571', 2020, category='independent')


def test_outside_backfill_preserves_snapshot_and_reuses_completed_work(monkeypatch):
    from datetime import timedelta
    from apps.campaign_finance.models import CandidateIdentity, RepresentativeCandidate
    from apps.campaign_finance.outside_backfill import queue_outside_period, process_outside_backfill
    rep = Representative.objects.create(bioguide_id='D000563', name='Durbin')
    candidate = CandidateIdentity.objects.create(fec_id='S6IL00151')
    RepresentativeCandidate.objects.create(representative=rep, candidate=candidate,
        periods=[2020], verified=True, evidence_url='https://www.fec.gov/data/candidate/S6IL00151/')
    run = ResearchRun.objects.create(representative=rep, period=2020, status='partial')
    snapshot = FinanceSnapshot.objects.create(run=run, representative=rep, period=2020,
        active=True, published_at=timezone.now(), candidate_ids=[candidate.pk], totals={'saved_donations': '123'})
    OutsideSpendingScan.objects.create(snapshot=snapshot, candidate_id=candidate.pk, complete=True)
    calls = []
    def page(path, params):
        calls.append(path)
        assert path != 'schedules/schedule_e/by_candidate/'
        rows = [dict(candidate_id=candidate.pk, cycle=2020, committee_id='C70002563',
            support_oppose_indicator='S', total='52833.72')] if path == 'communication_costs/by_candidate/' else []
        return {'results': rows, 'pagination': {'page': 1, 'pages': 1 if rows else 0, 'count': len(rows)}}
    monkeypatch.setattr('apps.campaign_finance.fec_client.get_page', page)
    work = queue_outside_period(rep.pk, 2020, None)
    assert queue_outside_period(rep.pk, 2020, None).pk == work.pk
    work.status, work.dispatch_token = 'processing', 'test'
    work.lease_expires_at = timezone.now() + timedelta(minutes=5)
    work.save()
    for _ in range(5):
        work.refresh_from_db()
        if process_outside_backfill(work)['status'] == 'succeeded':
            break
    else:
        pytest.fail('Backfill did not finish')
    snapshot.refresh_from_db()
    assert snapshot.totals == {'saved_donations': '123'}
    assert snapshot.active
    assert snapshot.outside_scans.filter(complete=True).count() == 3
    assert len(calls) == 2
    assert queue_outside_period(rep.pk, 2020, None) is None


def test_outside_backfill_fences_stale_delivery(monkeypatch):
    from apps.campaign_finance.outside_backfill import process_outside_backfill
    from apps.ingestion.models import IngestionWorkItem
    work = IngestionWorkItem.objects.create(kind='representative_research', dedupe_key='outside:missing',
        source_updated_at=timezone.now(), payload_json={'stage': 'outside_backfill', 'representative_id': 999, 'period': 2020})
    monkeypatch.setattr('apps.campaign_finance.fec_client.get_page', lambda *a: pytest.fail('Stale delivery called FEC'))
    assert process_outside_backfill(work)['status'] == 'superseded'


def test_durbin_scope_and_category_totals_do_not_claim_lifetime_coverage():
    from rest_framework.test import APIClient
    from apps.campaign_finance.outside import ensure_outside_scans
    rep = Representative.objects.create(bioguide_id='D000563', name='Dick Durbin')
    for cycle, category, amount, side in [(2014, 'independent', '717747.51', 'O'),
            (2020, 'communication', '64524.50', 'S'), (2020, 'independent', '69.76', 'S')]:
        run, _ = ResearchRun.objects.get_or_create(representative=rep, period=cycle, defaults={'status': 'partial'})
        snapshot, _ = FinanceSnapshot.objects.get_or_create(run=run, defaults=dict(representative=rep,
            period=cycle, active=True, published_at=timezone.now(), candidate_ids=['S6IL00151']))
        ensure_outside_scans(snapshot)
        scan = snapshot.outside_scans.get(category=category)
        persist_outside_page(scan, {'results': [dict(candidate_id='S6IL00151', cycle=cycle,
            committee_id='C00489799', support_oppose_indicator=side, total=amount)],
            'pagination': {'page': 1, 'pages': 1, 'count': 1}})
    client = APIClient()
    url = f'/api/representatives/{rep.pk}/outside-spending/?all_periods=true'
    all_years = client.get(url + '&scope=all_years').data
    recent = client.get(url + '&scope=last_ten_years').data
    assert all_years['start_year'] == 2013
    assert recent['start_year'] == 2019
    assert all_years['count'] == 3 and recent['count'] == 2
    assert recent['status'] == 'partial'  # Empty categories have not been checked.
    assert all_years['revision'] != recent['revision']
    assert client.get(url + '&scope=last_ten_years&revision=' + all_years['revision']).status_code == 409
    assert {row['category'] for row in recent['results']} == {'communication', 'independent'}
    assert any('/communication-costs/' in row['source_url'] for row in recent['results'])


def test_electioneering_api_does_not_add_mentions_to_support():
    from rest_framework.test import APIClient
    from apps.campaign_finance.outside import ensure_outside_scans
    rep = Representative.objects.create(bioguide_id='T000001', name='Example')
    run = ResearchRun.objects.create(representative=rep, period=2020, status='partial')
    snapshot = FinanceSnapshot.objects.create(run=run, representative=rep, period=2020,
        active=True, published_at=timezone.now(), candidate_ids=['P80001571'])
    ensure_outside_scans(snapshot)
    for scan in snapshot.outside_scans.all():
        rows = [dict(candidate_id='P80001571', cycle=2020, committee_id='C30000848',
                     total='194899.15')] if scan.category == 'electioneering' else []
        persist_outside_page(scan, {'results': rows, 'pagination': {'page': 1, 'pages': int(bool(rows)), 'count': len(rows)}})
    data = APIClient().get(f'/api/representatives/{rep.pk}/outside-spending/?period=2020').data
    assert data['status'] == 'available'
    assert Decimal(data['support']) == Decimal(data['oppose']) == 0
    assert Decimal(data['mentions']) == Decimal('194899.15')
    assert data['results'][0]['position'] == 'M'
    assert 'support_oppose_indicator' not in data['results'][0]['source_url']


def test_command_queues_all_known_years_and_reuses_jobs(monkeypatch):
    from django.core.management import call_command
    from apps.campaign_finance.models import CandidateIdentity, RepresentativeCandidate
    from apps.ingestion.models import IngestionWorkItem
    rep = Representative.objects.create(bioguide_id='D000563', name='Durbin')
    candidate = CandidateIdentity.objects.create(fec_id='S6IL00151', reporting_periods={'periods': [2014, 2020, 2026]})
    RepresentativeCandidate.objects.create(representative=rep, candidate=candidate,
        periods=[2026], verified=True, evidence_url='https://www.fec.gov/')
    monkeypatch.setattr('apps.congress.management.commands.backfill_outside_spending.discover_periods',
                        lambda *a, **kw: [2014, 2020, 2026])
    call_command('backfill_outside_spending', representative_id=rep.pk, scope='last_ten_years')
    assert IngestionWorkItem.objects.count() == 2
    call_command('backfill_outside_spending', all_researched=True)
    call_command('backfill_outside_spending', all_researched=True)
    assert set(IngestionWorkItem.objects.values_list('payload_json__period', flat=True)) == {2014, 2020, 2026}
    assert IngestionWorkItem.objects.count() == 3


def test_backfill_uses_real_durable_delivery_and_does_not_block_later_donation_research(monkeypatch):
    from apps.campaign_finance.models import CandidateIdentity, RepresentativeCandidate
    from apps.campaign_finance.outside_backfill import queue_outside_period
    from apps.ingestion.tasks import process_ingestion_work_item
    from apps.research.services import request_research
    rep = Representative.objects.create(bioguide_id='D000563', name='Durbin')
    candidate = CandidateIdentity.objects.create(fec_id='S6IL00151')
    RepresentativeCandidate.objects.create(representative=rep, candidate=candidate,
        periods=[2014], verified=True, evidence_url='https://www.fec.gov/')
    calls = []
    def fetch(path, params):
        calls.append(path)
        return {'results': [], 'pagination': {'page': 1, 'pages': 0, 'count': 0}}
    monkeypatch.setattr('apps.campaign_finance.fec_client.get_page', fetch)
    monkeypatch.setattr('apps.ingestion.tasks.dispatch_ingestion_work.apply_async', lambda *a, **kw: None)
    work = queue_outside_period(rep.pk, 2014, None)
    for _ in range(4):
        process_ingestion_work_item.apply(args=[work.pk]).get()
        work.refresh_from_db()
    assert work.status == 'succeeded'
    assert set(calls) == {'communication_costs/by_candidate/', 'electioneering/by_candidate/', 'schedules/schedule_e/by_candidate/'}
    assert len(calls) == 3
    snapshot = FinanceSnapshot.objects.get(representative=rep, period=2014)
    assert snapshot.active
    new_run = request_research(rep.pk, 2014, None, refresh=False, include_history=False)
    assert new_run.pk != snapshot.run_id  # An outside-only snapshot is not completed donation research.
    assert new_run.status == 'queued'
