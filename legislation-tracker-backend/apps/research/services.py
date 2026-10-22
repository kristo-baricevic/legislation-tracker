from django.db import transaction
from django.utils import timezone
from apps.congress.models import Representative
from apps.ingestion.work_queue import enqueue_ingestion_work
from .models import ResearchRun


def validate_period(period):
    current = timezone.now().year
    if type(period) is not int or period % 2 or not 1980 <= period <= current + current % 2:
        raise ValueError("Choose an even reporting-period year from 1980 through the current period.")
    return period


def request_research(representative_id: int, period: int, user_id: int) -> ResearchRun:
    validate_period(period)
    with transaction.atomic():
        Representative.objects.select_for_update().get(pk=representative_id)
        ResearchRun.objects.filter(representative_id=representative_id, period=period, status__in=["queued", "running"], work_item__status="dead").update(status="failed", finished_at=timezone.now())
        existing = ResearchRun.objects.filter(representative_id=representative_id, period=period, status__in=["queued", "running"]).first()
        if existing:
            return existing
        run = ResearchRun.objects.create(representative_id=representative_id, period=period, requester_id=user_id)
        run.work_item = enqueue_ingestion_work(kind="representative_research", dedupe_key=str(run.pk), source_updated_at=run.created_at, payload_json={"run_id": str(run.pk)})
        run.save(update_fields=["work_item"])
        return run
