"""Helpers for persisting pipeline work before asking Celery to deliver it."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import TrackedBill
from apps.ingestion.models import (
    BillTrackingRequest,
    BillTrackingRequestStatus,
    IngestionWorkItem,
    IngestionWorkStatus,
)
from apps.legislation.models import Bill

logger = logging.getLogger(__name__)
MANUAL_BILL_SOURCE_UPDATED_AT = datetime(1970, 1, 1, tzinfo=UTC)


def _replace_superseded_pending_work(queryset, *, replacement):
    # Roll-call payloads carry bill associations not present in independent
    # vote discovery. A newer timestamp is not a complete replacement.
    if replacement.kind == "roll_call_vote":
        return
    stale_ids = list(queryset.values_list("pk", flat=True))
    if not stale_ids:
        return
    BillTrackingRequest.objects.filter(work_item_id__in=stale_ids).update(
        work_item=replacement
    )
    IngestionWorkItem.objects.filter(pk__in=stale_ids).delete()


def enqueue_ingestion_work(
    *,
    kind: str,
    dedupe_key: str,
    source_updated_at,
    payload_json: dict,
    jurisdiction: str = "federal",
    congress: int | None = None,
    dependency_keys: list[str] | None = None,
) -> IngestionWorkItem:
    """Persist work before triggering the best-effort Celery dispatcher.

    A broker failure after this function returns cannot discard the work: beat
    will dispatch the pending row on its next run.
    """
    work_item, _created = persist_ingestion_work(
        kind=kind,
        dedupe_key=dedupe_key,
        source_updated_at=source_updated_at,
        payload_json=payload_json,
        jurisdiction=jurisdiction,
        congress=congress,
        dependency_keys=dependency_keys,
    )
    with transaction.atomic():
        transaction.on_commit(_request_dispatch)
    return work_item


def persist_ingestion_work(
    *,
    kind: str,
    dedupe_key: str,
    source_updated_at,
    payload_json: dict,
    jurisdiction: str = "federal",
    congress: int | None = None,
    dependency_keys: list[str] | None = None,
) -> tuple[IngestionWorkItem, bool]:
    """Persist the newest source revision without retaining stale pending work.

    Durable history that has started or completed is preserved. Only work that
    has never been attempted is superseded, because every ingestion stage reads
    the current upstream or database state rather than replaying a snapshot.
    """
    if timezone.is_naive(source_updated_at):
        source_updated_at = timezone.make_aware(source_updated_at, UTC)

    with transaction.atomic():
        existing = list(
            IngestionWorkItem.objects.select_for_update()
            .filter(kind=kind, dedupe_key=dedupe_key)
            .order_by("-source_updated_at", "-id")
        )
        latest = existing[0] if existing else None
        if latest is not None and latest.source_updated_at > source_updated_at:
            _replace_superseded_pending_work(
                IngestionWorkItem.objects.filter(
                    kind=kind,
                    dedupe_key=dedupe_key,
                    status=IngestionWorkStatus.PENDING,
                    attempt_count=0,
                    source_updated_at__lt=latest.source_updated_at,
                ),
                replacement=latest,
            )
            return latest, False

        exact = next(
            (item for item in existing if item.source_updated_at == source_updated_at),
            None,
        )
        if exact is None:
            work_item, created = IngestionWorkItem.objects.get_or_create(
                kind=kind,
                dedupe_key=dedupe_key,
                source_updated_at=source_updated_at,
                defaults={
                    "jurisdiction": jurisdiction,
                    "congress": congress,
                    "payload_json": payload_json,
                    "dependency_keys": sorted(set(dependency_keys or [])),
                    "available_at": timezone.now(),
                },
            )
        else:
            work_item = exact
            created = False

        _replace_superseded_pending_work(
            IngestionWorkItem.objects.filter(
                kind=kind,
                dedupe_key=dedupe_key,
                status=IngestionWorkStatus.PENDING,
                attempt_count=0,
                source_updated_at__lt=source_updated_at,
            ).exclude(pk=work_item.pk),
            replacement=work_item,
        )
        return work_item, created


def _request_dispatch() -> None:
    """Wake the dispatcher now; the persisted row remains safe if this fails."""
    try:
        from apps.ingestion.tasks import dispatch_ingestion_work

        dispatch_ingestion_work.delay()
    except Exception:
        logger.exception("Could not trigger durable ingestion work dispatcher")


def enqueue_manual_bill_request(
    *,
    user,
    congress: int,
    bill_type: str,
    bill_number: str,
    jurisdiction: str = "federal",
) -> tuple[IngestionWorkItem, BillTrackingRequest]:
    """Persist manual ingestion work and its user-owned tracking intent atomically."""
    normalized_bill_type = str(bill_type).strip().lower()
    normalized_bill_number = str(bill_number).strip()
    dedupe_key = f"{congress}-{normalized_bill_type}-{normalized_bill_number}"

    with transaction.atomic():
        work_item, _ = IngestionWorkItem.objects.get_or_create(
            kind="bill",
            dedupe_key=dedupe_key,
            source_updated_at=MANUAL_BILL_SOURCE_UPDATED_AT,
            defaults={
                "jurisdiction": jurisdiction,
                "congress": congress,
                "payload_json": {"bill_key": dedupe_key},
                "available_at": timezone.now(),
            },
        )
        work_item = IngestionWorkItem.objects.select_for_update().get(pk=work_item.pk)
        tracking_request, _ = BillTrackingRequest.objects.get_or_create(
            user=user,
            jurisdiction=jurisdiction,
            congress=congress,
            bill_type=normalized_bill_type,
            bill_number=normalized_bill_number,
            defaults={"work_item": work_item},
        )
        tracking_request = BillTrackingRequest.objects.select_for_update().get(
            pk=tracking_request.pk
        )
        bill = Bill.objects.filter(
            jurisdiction=jurisdiction,
            session=congress,
            bill_number=_bill_number_display(
                normalized_bill_type,
                normalized_bill_number,
            ),
        ).first()
        tracked_bill_exists = (
            bill is not None
            and TrackedBill.objects.filter(
                user=tracking_request.user,
                bill=bill,
            ).exists()
        )
        if (
            tracking_request.status == BillTrackingRequestStatus.FULFILLED
            and not tracked_bill_exists
        ):
            tracking_request.status = BillTrackingRequestStatus.PENDING
            tracking_request.bill = None
            tracking_request.fulfilled_at = None
            tracking_request.save(
                update_fields=["status", "bill", "fulfilled_at", "updated_at"]
            )

        if bill is None and work_item.status == IngestionWorkStatus.SUCCEEDED:
            work_item.status = IngestionWorkStatus.PENDING
            work_item.attempt_count = 0
            work_item.available_at = timezone.now()
            work_item.lease_expires_at = None
            work_item.celery_task_id = ""
            work_item.dispatch_token = ""
            work_item.last_error = ""
            work_item.completed_at = None
            work_item.save(
                update_fields=[
                    "status",
                    "attempt_count",
                    "available_at",
                    "lease_expires_at",
                    "celery_task_id",
                    "dispatch_token",
                    "last_error",
                    "completed_at",
                    "updated_at",
                ]
            )
        if bill is not None:
            fulfill_tracking_requests_for_bill(
                bill,
                bill_type=normalized_bill_type,
                bill_number=normalized_bill_number,
            )
            tracking_request.refresh_from_db()
        transaction.on_commit(_request_dispatch)
    return work_item, tracking_request


def fulfill_tracking_requests_for_bill(
    bill: Bill,
    *,
    bill_type: str,
    bill_number: str,
) -> int:
    """Fulfill every pending manual tracking intent for a persisted bill."""
    pending_requests = list(
        BillTrackingRequest.objects.select_for_update().filter(
            jurisdiction=bill.jurisdiction,
            congress=bill.session,
            bill_type=str(bill_type).strip().lower(),
            bill_number=str(bill_number).strip(),
            status=BillTrackingRequestStatus.PENDING,
        )
    )
    fulfilled_at = timezone.now()
    for tracking_request in pending_requests:
        TrackedBill.objects.get_or_create(
            user=tracking_request.user,
            bill=bill,
        )
        tracking_request.bill = bill
        tracking_request.status = BillTrackingRequestStatus.FULFILLED
        tracking_request.fulfilled_at = fulfilled_at
        tracking_request.save(
            update_fields=["bill", "status", "fulfilled_at", "updated_at"]
        )
    return len(pending_requests)


def _bill_number_display(bill_type: str, bill_number: str) -> str:
    return f"{bill_type.upper()} {bill_number}"
