"""One aggregate page per durable delivery, without re-downloading donations."""

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.congress.models import Representative
from apps.ingestion.models import IngestionWorkItem
from apps.ingestion.work_queue import enqueue_ingestion_work
from apps.research.models import ResearchRun
from apps.research.tasks import continue_work, fenced_work

from .identity import resolve_candidate
from .models import FinanceSnapshot, OutsideSpendingScan
from .outside import (
    ensure_outside_scans,
    outside_complete,
    outside_page,
    persist_outside_page,
)


def saved_snapshot(representative_id, period):
    return (
        FinanceSnapshot.objects.filter(
            representative_id=representative_id, period=period, invalidated=False
        )
        .filter(Q(active=True) | Q(run__status__in=["queued", "running"]))
        .order_by("-active", "-created_at")
        .first()
    )


def queue_outside_period(representative_id, period, user_id):
    from apps.research.services import validate_period

    validate_period(period)
    with transaction.atomic():
        Representative.objects.select_for_update().get(pk=representative_id)
        identity = resolve_candidate(representative_id, period)
        if identity.status != "verified":
            return None
        if ResearchRun.objects.filter(
            representative_id=representative_id,
            period=period,
            status__in=["queued", "running"],
            work_item__status__in=["pending", "dispatched", "processing"],
        ).exists():
            return None  # The normal research job already collects all categories.
        snapshot = saved_snapshot(representative_id, period)
        if (
            snapshot
            and set(snapshot.candidate_ids) == set(identity.candidate_ids)
            and outside_complete(snapshot)
        ):
            return None
        key = f"outside:{representative_id}:{period}"
        active = IngestionWorkItem.objects.filter(
            kind="representative_research",
            dedupe_key=key,
            status__in=["pending", "dispatched", "processing"],
        ).first()
        if active:
            return active
        return enqueue_ingestion_work(
            kind="representative_research",
            dedupe_key=key,
            source_updated_at=timezone.now(),
            payload_json={
                "stage": "outside_backfill",
                "representative_id": representative_id,
                "period": period,
                "requester_id": user_id,
            },
        )


def process_outside_backfill(work):
    with transaction.atomic():
        current = fenced_work(work)
        if current is None:
            return {"status": "superseded"}
        rep_id, period = (
            current.payload_json["representative_id"],
            current.payload_json["period"],
        )
        Representative.objects.select_for_update().get(pk=rep_id)
        identity = resolve_candidate(rep_id, period)
        if identity.status != "verified":
            raise ValueError("outside_identity_unavailable")
        snapshot = saved_snapshot(rep_id, period)
        if snapshot is None:
            run = ResearchRun.objects.filter(
                representative_id=rep_id,
                period=period,
                status__in=["queued", "running"],
            ).first()
            standalone = run is None
            if standalone:
                run = ResearchRun.objects.create(
                    representative_id=rep_id,
                    period=period,
                    requester_id=current.payload_json.get("requester_id"),
                    status="partial",
                    sections={
                        "finance": {
                            "status": "partial",
                            "reason": "outside_spending_only",
                        }
                    },
                )
            snapshot = FinanceSnapshot.objects.create(
                run=run,
                representative_id=rep_id,
                period=period,
                candidate_ids=identity.candidate_ids,
                active=standalone,
                normalization_version="fec-2-filtered",
                published_at=timezone.now() if standalone else None,
            )
        if set(snapshot.candidate_ids) != set(identity.candidate_ids):
            raise ValueError("outside_identity_changed")
        ensure_outside_scans(snapshot)
        scan = (
            snapshot.outside_scans.filter(complete=False)
            .order_by("candidate_id", "category")
            .first()
        )
        if scan is None:
            return {"status": "succeeded"}
        expected_page = scan.page
    page = outside_page(scan)
    with transaction.atomic():
        current = fenced_work(work)
        if current is None:
            return {"status": "superseded"}
        Representative.objects.select_for_update().get(pk=rep_id)
        if resolve_candidate(rep_id, period) != identity:
            raise ValueError("outside_identity_changed")
        # A normal research refresh may publish a newer snapshot during I/O.
        selected = saved_snapshot(rep_id, period)
        if selected is None or selected.pk != snapshot.pk:
            continue_work(current, "outside_backfill")
            return {"status": "running"}
        scan = OutsideSpendingScan.objects.select_for_update().get(pk=scan.pk)
        if not scan.complete and scan.page == expected_page:
            persist_outside_page(scan, page)
        continue_work(current, "outside_backfill")
    return {"status": "running"}
