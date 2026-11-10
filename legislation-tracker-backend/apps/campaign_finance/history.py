"""Durably queue the last ten calendar years, independently of receipts."""
from django.db import transaction
from django.utils import timezone

from apps.congress.models import Representative
from apps.ingestion.models import IngestionWorkItem
from apps.ingestion.work_queue import enqueue_ingestion_work
from apps.research.models import ResearchRun
from apps.research.tasks import fenced_work, is_latest_run
from .identity import resolve_candidate
from .periods import discover_periods


def queue_history(run, *, explicit=False):
    if resolve_candidate(run.representative_id, run.period).status != 'verified':
        return None  # The finance worker schedules this after identity discovery.
    # Serialize concurrent clicks, but release this lock before source I/O.
    with transaction.atomic():
        Representative.objects.select_for_update().get(pk=run.representative_id)
        key = f'history:{run.pk}'
        latest = IngestionWorkItem.objects.filter(kind='representative_research', dedupe_key=key).order_by('-source_updated_at').first()
        if latest and (not explicit or latest.status in {'pending', 'dispatched', 'processing'}):
            return latest
        return enqueue_ingestion_work(kind='representative_research', dedupe_key=key,
            source_updated_at=timezone.now(), payload_json={'run_id': str(run.pk), 'stage': 'history'})


def process_history(work):
    from apps.research.services import request_research
    run = ResearchRun.objects.select_related('representative').get(pk=work.payload_json['run_id'])
    identity = resolve_candidate(run.representative_id, run.period)
    if identity.status != 'verified':
        return {'status': 'identity_unavailable'}
    # Include whole reporting cycles overlapping the last ten calendar years.
    # Older saved records remain available; they are not automatically backfilled.
    # A failed discovery raises for durable retry instead of marking history done.
    year = timezone.now().year
    periods = [period for period in discover_periods(run.representative, strict=True)
               if year - 9 <= period <= year + year % 2]
    with transaction.atomic():
        if fenced_work(work) is None:
            return {'status': 'superseded'}
        Representative.objects.select_for_update().get(pk=run.representative_id)
        if not is_latest_run(run) or resolve_candidate(run.representative_id, run.period) != identity:
            return {'status': 'superseded'}
        for period in periods:
            if period != run.period:
                request_research(run.representative_id, period, run.requester_id,
                                 refresh=False, include_history=False)
    return {'status': 'succeeded', 'periods': periods}
