"""Read-only previews; unfinished scans never replace published snapshots."""
from .models import FinanceSnapshot
from apps.research.models import ResearchRun


def latest_preview(representative_id, period):
    run = ResearchRun.objects.filter(representative_id=representative_id, period=period).select_related("work_item").order_by("-created_at").first()
    if not run or run.status not in {"queued", "running"} or (run.work_item and run.work_item.status == "dead"):
        return None
    return FinanceSnapshot.objects.filter(run=run, invalidated=False, published_at__isnull=True).first()


def finance_progress(snapshot):
    if not snapshot:
        return None
    checkpoints = list(snapshot.checkpoints.all())
    totals = [cp.source_totals for cp in checkpoints if cp.schedule == "totals" and cp.complete]
    return {"snapshot": str(snapshot.pk), "collecting": snapshot.published_at is None,
            "pages_loaded": sum(len(cp.page_hashes) for cp in checkpoints),
            "streams_completed": sum(cp.complete for cp in checkpoints), "streams_total": len(checkpoints),
            "totals_loaded": len(totals), "official_totals": totals}
