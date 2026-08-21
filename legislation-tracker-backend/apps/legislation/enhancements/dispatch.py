import logging

logger = logging.getLogger(__name__)


def request_enhancement_dispatch(attempt_id: int) -> None:
    """Best-effort wake; the periodic database dispatcher remains authoritative."""
    try:
        from apps.legislation.tasks import dispatch_bill_enhancement_attempts

        dispatch_bill_enhancement_attempts.delay(attempt_ids=[attempt_id])
    # Broker/client failures vary by transport. This is deliberately broad:
    # the database row remains authoritative and the periodic dispatcher will
    # retry the wake without exposing a transport exception to the API caller.
    except Exception:  # noqa: BLE001
        logger.warning(
            "Could not wake bill enhancement dispatcher",
            extra={"attempt_id": attempt_id, "category": "dispatch_wake_failed"},
        )
