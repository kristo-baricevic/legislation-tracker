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


def request_research(representative_id: int, period: int, user_id: int, *, refresh=True, include_history=True) -> ResearchRun:
    run = _request_period(representative_id, period, user_id, refresh=refresh, finance_only=not include_history)
    if include_history:
        from apps.campaign_finance.history import queue_history
        queue_history(run, explicit=True)
    return run


def _request_period(representative_id, period, user_id, *, refresh, finance_only):
    validate_period(period)
    with transaction.atomic():
        Representative.objects.select_for_update().get(pk=representative_id)
        ResearchRun.objects.filter(representative_id=representative_id, period=period, status__in=["queued", "running"], work_item__status="dead").update(status="failed", finished_at=timezone.now())
        existing = ResearchRun.objects.filter(representative_id=representative_id, period=period, status__in=["queued", "running"]).first()
        if existing:
            return existing
        if not refresh:
            from apps.campaign_finance.models import FinanceSnapshot
            saved = FinanceSnapshot.objects.filter(representative_id=representative_id, period=period, active=True, invalidated=False, published_at__isnull=False).select_related("run").first()
            if saved:
                if not finance_only:
                    return saved.run
                from apps.campaign_finance.identity import resolve_candidate
                identity = resolve_candidate(representative_id, period)
                if identity.status == "verified":
                    expected = set(identity.candidate_ids)
                    scanned = set(saved.outside_scans.filter(complete=True).values_list("candidate_id", flat=True))
                    if expected and expected == scanned == set(saved.candidate_ids):
                        return saved.run
        run = ResearchRun.objects.create(representative_id=representative_id, period=period, requester_id=user_id)
        payload = {"run_id": str(run.pk), "refresh": refresh, "include_history": not finance_only}
        if finance_only:
            payload["stage"] = "finance"
        run.work_item = enqueue_ingestion_work(kind="representative_research", dedupe_key=str(run.pk), source_updated_at=run.created_at, payload_json=payload)
        run.save(update_fields=["work_item"])
        return run
