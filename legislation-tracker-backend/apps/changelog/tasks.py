"""Operational tasks for ChangeLog storage maintenance."""

import logging

from celery import shared_task

from apps.changelog.partitions import ensure_change_log_partitions

logger = logging.getLogger(__name__)


@shared_task
def ensure_change_log_partitions_task(months_ahead=12):
    """Keep the current and future monthly PostgreSQL partitions available."""
    created = ensure_change_log_partitions(months_ahead=months_ahead)
    logger.info(
        "ChangeLog partition maintenance complete",
        extra={"created_partitions": created},
    )
    return {"created": created, "months_ahead": months_ahead}
