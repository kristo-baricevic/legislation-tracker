"""Pure semantics shared by discovery and its read-only readiness observation."""

from datetime import UTC, datetime, timedelta

from django.utils import timezone

CURSOR_OVERLAP = timedelta(minutes=5)
UNKNOWN_SOURCE_UPDATED_AT = datetime(1970, 1, 1, tzinfo=UTC)


def _ensure_utc_aware(dt):
    """Normalize DB or parsed datetimes so comparisons never mix naive vs aware."""
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, UTC)
    return dt


def _parse_congress_update_datetime(value):
    """Parse bill list updateDate (string or datetime); return UTC-aware or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
        except Exception:
            return None
    else:
        return None
    return _ensure_utc_aware(dt)


def discovery_from_date_time(cursor):
    return (
        (_ensure_utc_aware(cursor) - CURSOR_OVERLAP).strftime("%Y-%m-%dT%H:%M:%SZ")
        if cursor
        else None
    )


def revision_creates_work(latest_revision, source_revision):
    return latest_revision is None or latest_revision < source_revision
