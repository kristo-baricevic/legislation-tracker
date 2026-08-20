"""Helpers for persisting pipeline work before asking Celery to deliver it."""
from __future__ import annotations

import logging
from datetime import timezone as dt_timezone

from django.db import transaction
from django.utils import timezone

from apps.ingestion.models import IngestionWorkItem

logger = logging.getLogger(__name__)


def enqueue_ingestion_work(
    *,
    kind: str,
    dedupe_key: str,
    source_updated_at,
    payload_json: dict,
    jurisdiction: str = "federal",
    congress: int | None = None,
) -> IngestionWorkItem:
    """Persist work before triggering the best-effort Celery dispatcher.

    A broker failure after this function returns cannot discard the work: beat
    will dispatch the pending row on its next run.
    """
    if timezone.is_naive(source_updated_at):
        source_updated_at = timezone.make_aware(source_updated_at, dt_timezone.utc)

    with transaction.atomic():
        work_item, _ = IngestionWorkItem.objects.get_or_create(
            kind=kind,
            dedupe_key=dedupe_key,
            source_updated_at=source_updated_at,
            defaults={
                "jurisdiction": jurisdiction,
                "congress": congress,
                "payload_json": payload_json,
                "available_at": timezone.now(),
            },
        )
        transaction.on_commit(_request_dispatch)
    return work_item


def _request_dispatch() -> None:
    """Wake the dispatcher now; the persisted row remains safe if this fails."""
    try:
        from apps.ingestion.tasks import dispatch_ingestion_work

        dispatch_ingestion_work.delay()
    except Exception:
        logger.exception("Could not trigger durable ingestion work dispatcher")
