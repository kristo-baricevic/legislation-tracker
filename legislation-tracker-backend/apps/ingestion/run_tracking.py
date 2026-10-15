"""Shared manual/Beat discovery claims. No claims of exactly-once publication."""

import uuid
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import IngestionRun, IngestionState

LEASE = timedelta(minutes=20)


def validate_scope(jurisdiction, congress):
    if (
        jurisdiction != "federal"
        or isinstance(congress, bool)
        or not 1 <= congress <= 200
    ):
        raise ValueError("Unsupported ingestion scope")


def claim_run(jurisdiction, congress, request_key=None, trigger="scheduled"):
    try:
        return _claim_run(jurisdiction, congress, request_key, trigger)
    except IntegrityError:
        # A different scope can concurrently win this globally unique key.
        previous = (
            IngestionRun.objects.filter(request_key=request_key).first()
            if request_key
            else None
        )
        if previous and (previous.jurisdiction, previous.congress) == (
            jurisdiction,
            congress,
        ):
            return previous, False
        raise ValueError("Conflicting discovery request") from None


def _claim_run(jurisdiction, congress, request_key=None, trigger="scheduled"):
    validate_scope(jurisdiction, congress)
    now = timezone.now()
    with transaction.atomic():
        state, _ = IngestionState.objects.get_or_create(
            jurisdiction=jurisdiction, congress=congress
        )
        IngestionState.objects.select_for_update().get(pk=state.pk)
        now = timezone.now()
        if request_key:
            previous = (
                IngestionRun.objects.select_for_update()
                .filter(request_key=request_key)
                .first()
            )
            if previous:
                if (previous.jurisdiction, previous.congress) != (
                    jurisdiction,
                    congress,
                ):
                    raise ValueError("Idempotency key belongs to another scope")
                if (
                    previous.status in ["pending", "running"]
                    and previous.lease_expires_at <= now
                ):
                    previous.status = "unknown"
                    previous.finished_at = now
                    previous.error_code = "lease_expired"
                    previous.save(update_fields=["status", "finished_at", "error_code"])
                return previous, False
        IngestionRun.objects.filter(
            jurisdiction=jurisdiction,
            congress=congress,
            status__in=["pending", "running"],
            lease_expires_at__lte=now,
        ).update(status="unknown", finished_at=now, error_code="lease_expired")
        active = IngestionRun.objects.filter(
            jurisdiction=jurisdiction,
            congress=congress,
            status__in=["pending", "running"],
        ).first()
        if active:
            return active, False
        return (
            IngestionRun.objects.create(
                jurisdiction=jurisdiction,
                congress=congress,
                request_key=request_key or uuid.uuid4().hex,
                trigger=trigger,
                lease_expires_at=now + LEASE,
            ),
            True,
        )


def heartbeat(run_id):
    if not IngestionRun.objects.filter(
        pk=run_id, status="running", lease_expires_at__gt=timezone.now()
    ).update(lease_expires_at=timezone.now() + LEASE):
        raise RuntimeError("Discovery claim expired or superseded")


def execute_discovery(implementation, jurisdiction, congress, run_id=None):
    if run_id is None:
        run, created = claim_run(jurisdiction, congress)
        if not created:
            return {"run_id": str(run.id), "status": run.status, "coalesced": True}
        run_id = run.id
    with transaction.atomic():
        run = IngestionRun.objects.select_for_update().get(pk=run_id)
        if (run.jurisdiction, run.congress) != (jurisdiction, congress):
            raise ValueError("Run scope mismatch")
        if run.status != "pending":
            return {"run_id": str(run.id), "status": run.status, "coalesced": True}
        if run.lease_expires_at <= timezone.now():
            run.status = "unknown"
            run.error_code = "lease_expired"
            run.finished_at = timezone.now()
            run.save()
            return {"run_id": str(run.id), "status": "unknown"}
        run.status = "running"
        run.started_at = timezone.now()
        run.lease_expires_at = timezone.now() + LEASE
        run.save()
    try:
        result = implementation(
            jurisdiction=jurisdiction, congress=congress, run_id=run_id
        )
        IngestionRun.objects.filter(pk=run_id, status="running").update(
            status="succeeded",
            finished_at=timezone.now(),
            discovered_count=result["discovered"],
            created_count=result["created"],
        )
        return result
    except Exception:
        IngestionRun.objects.filter(pk=run_id, status="running").update(
            status="failed", finished_at=timezone.now(), error_code="discovery_failed"
        )
        raise
