import uuid
from datetime import datetime

from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Max
from django.utils import timezone
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .discoverable_readiness import discoverable_snapshot_available
from .models import IngestionRun, IngestionState, IngestionWorkItem
from .run_tracking import claim_run, validate_scope
from .source_inventory import BILL_TYPES, snapshot_key


def scope_from(data):
    from .tasks import current_congress

    jurisdiction = data.get("jurisdiction", "federal")
    raw = data.get("congress", current_congress())
    if isinstance(raw, bool) or not (
        isinstance(raw, int) or isinstance(raw, str) and raw.isascii() and raw.isdigit()
    ):
        raise ValueError("Unsupported ingestion scope")
    congress = int(raw)
    validate_scope(jurisdiction, congress)
    if "bill_types" in data and data.get("bill_types") not in ("hr,s", ["hr", "s"]):
        raise ValueError("Unsupported bill types")
    if "bill_type" in data:
        raise ValueError("Unsupported bill type parameter")
    return jurisdiction, congress


class IngestionTelemetryView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        try:
            jurisdiction, congress = scope_from(request.query_params)
        except (ValueError, TypeError):
            return Response({"error": "Unsupported ingestion scope"}, status=400)
        now = timezone.now()
        work = IngestionWorkItem.objects.filter(
            jurisdiction=jurisdiction, congress=congress
        )
        state = IngestionState.objects.filter(
            jurisdiction=jurisdiction, congress=congress
        ).first()
        run = (
            IngestionRun.objects.filter(jurisdiction=jurisdiction, congress=congress)
            .order_by("-created_at")
            .first()
        )
        return Response(
            {
                "observed_at": now,
                "jurisdiction": jurisdiction,
                "congress": congress,
                "last_discovery_completed_at": state.last_polled_at if state else None,
                "last_successful_work_item_at": work.filter(
                    status="succeeded"
                ).aggregate(value=Max("completed_at"))["value"],
                "counts_by_kind_and_status": list(
                    work.values("kind", "status")
                    .annotate(count=Count("id"))
                    .order_by("kind", "status")
                ),
                "runnable_pending": work.filter(
                    status="pending", available_at__lte=now
                ).count(),
                "scheduled_pending": work.filter(
                    status="pending", available_at__gt=now
                ).count(),
                "stale_leases": work.filter(
                    status__in=["dispatched", "processing"], lease_expires_at__lte=now
                ).count(),
                "recent_work_states": list(
                    work.order_by("-updated_at").values(
                        "id", "kind", "status", "updated_at", "attempt_count"
                    )[:20]
                ),
                "discovery_run": (
                    {
                        "id": str(run.id),
                        "status": (
                            "unknown"
                            if run.status in ["pending", "running"]
                            and run.lease_expires_at <= now
                            else run.status
                        ),
                        "started_at": run.started_at,
                        "finished_at": run.finished_at,
                        "discovered": run.discovered_count,
                        "created": run.created_count,
                        "error_code": run.error_code,
                    }
                    if run
                    else None
                ),
                "downstream_run_completion_available": False,
            }
        )


class SourceReadinessView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        try:
            jurisdiction, congress = scope_from(request.query_params)
        except (ValueError, TypeError):
            return Response({"error": "Unsupported ingestion scope"}, status=400)
        snapshot = cache.get(snapshot_key(jurisdiction, congress, BILL_TYPES))
        if not snapshot:
            return Response(
                {
                    "available": False,
                    "ready_to_start": None,
                    "reason": "No source inventory snapshot",
                }
            )
        age = None
        try:
            completed = datetime.fromisoformat(snapshot["checked_completed_at"])
            if timezone.is_aware(completed):
                elapsed = (timezone.now() - completed).total_seconds()
                if elapsed >= 0:
                    age = elapsed
        except (KeyError, TypeError, ValueError, OverflowError):
            pass
        available = bool(snapshot.get("complete")) and age is not None and age <= 300
        discoverable_available = available and discoverable_snapshot_available(
            snapshot, jurisdiction, congress
        )
        return Response(
            {
                **snapshot,
                "age_seconds": age,
                "available": available,
                "ready_to_start": snapshot.get("ready_to_start")
                if discoverable_available
                else None,
                "incremental_discoverable_count_available": discoverable_available,
                "missing_unqueued_metadata": (
                    snapshot.get("missing_unqueued_metadata") if available else None
                ),
                "missing_bill_metadata": (
                    snapshot.get("missing_bill_metadata") if available else None
                ),
                "already_scheduled_or_blocked": (
                    snapshot.get("already_scheduled_or_blocked") if available else None
                ),
                "reason": None if available else "Source check incomplete or stale",
            }
        )


def start_discovery(request):
    from .tasks import poll_congress

    try:
        jurisdiction, congress = scope_from(request.data)
        key = (
            request.headers.get("Idempotency-Key")
            or request.data.get("idempotency_key")
            or uuid.uuid4().hex
        )
        if not isinstance(key, str):
            raise ValueError("Invalid idempotency key")
        if len(key) > 128 or not key.isascii() or not key.strip():
            raise ValueError("Invalid idempotency key")
        run, created = claim_run(jurisdiction, congress, key, "manual")
    except (ValueError, TypeError):
        return Response({"error": "Unsupported scope or idempotency key"}, status=400)
    if not created and run.request_key != key:
        return Response(
            {
                "run_id": str(run.id),
                "status": run.status,
                "error": "Discovery already active; this request was not accepted",
            },
            status=409,
        )
    response = Response(
        {
            "task_id": run.task_id or None,
            "task_name": "poll_congress",
            "jurisdiction": jurisdiction,
            "congress": congress,
            "run_id": str(run.id),
            "status": run.status,
            "coalesced": not created,
        },
        status=202,
    )
    if created:

        def publish():
            try:
                result = poll_congress.delay(
                    jurisdiction=jurisdiction, congress=congress, run_id=str(run.id)
                )
                IngestionRun.objects.filter(pk=run.id).update(task_id=result.id)
                response.data["task_id"] = result.id
            except Exception:
                IngestionRun.objects.filter(pk=run.id, status="pending").update(
                    status="unknown",
                    error_code="publication_uncertain",
                    finished_at=timezone.now(),
                )
                response.data.update(
                    status="unknown", error="Task publication could not be confirmed"
                )
                response.status_code = 503

        # Never publish work whose claim transaction can still roll back.
        transaction.on_commit(publish)
    return response
