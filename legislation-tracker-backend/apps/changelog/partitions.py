"""PostgreSQL monthly-partition maintenance for the append-only ChangeLog."""

from datetime import date, datetime
from datetime import timezone as datetime_timezone

from django.db import connection as django_connection
from django.db import transaction
from django.utils import timezone

CHANGELOG_TABLE = "changelog_changelog"
_ADVISORY_LOCK_KEY = "legislation-tracker:changelog-partitions"


class ChangeLogPartitioningError(RuntimeError):
    """Raised when PostgreSQL partition maintenance finds an invalid parent."""


def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def month_bounds(value: date) -> tuple[datetime, datetime]:
    """Return UTC timestamptz bounds for the date's calendar month.

    ``created_at`` is a PostgreSQL ``timestamptz`` column. Supplying aware UTC
    values avoids letting a connection's session timezone shift a partition
    boundary away from midnight UTC.
    """
    start = _month_start(value)
    if start.month == 12:
        next_start = date(start.year + 1, 1, 1)
    else:
        next_start = date(start.year, start.month + 1, 1)
    return (
        datetime.combine(start, datetime.min.time(), tzinfo=datetime_timezone.utc),
        datetime.combine(next_start, datetime.min.time(), tzinfo=datetime_timezone.utc),
    )


def partition_name(value: date) -> str:
    """Return the fixed, generated name for the date's monthly partition."""
    start = _month_start(value)
    return f"{CHANGELOG_TABLE}_{start.year:04d}_{start.month:02d}"


def _month_starts(start: date, months_ahead: int) -> list[date]:
    starts = []
    current = _month_start(start)
    for _ in range(months_ahead + 1):
        starts.append(current)
        current = month_bounds(current)[1].date()
    return starts


def _is_partitioned_parent(cursor) -> bool:
    cursor.execute(
        "SELECT c.relkind = 'p' FROM pg_class AS c " "WHERE c.oid = to_regclass(%s)",
        [CHANGELOG_TABLE],
    )
    row = cursor.fetchone()
    return bool(row and row[0])


def _partition_exists(cursor, name: str) -> bool:
    cursor.execute("SELECT to_regclass(%s) IS NOT NULL", [name])
    row = cursor.fetchone()
    return bool(row and row[0])


def _utc_partition_bound(value: datetime) -> str:
    """Render a generated UTC boundary as a typed PostgreSQL literal."""
    utc_value = value.astimezone(datetime_timezone.utc)
    return utc_value.strftime("TIMESTAMPTZ '%Y-%m-%d %H:%M:%S+00'")


def ensure_change_log_partitions(
    *, months_ahead: int = 12, connection=None, today: date | None = None
) -> list[str]:
    """Create this month's and future PostgreSQL ChangeLog partitions idempotently."""
    if months_ahead < 0:
        raise ValueError("months_ahead must be zero or greater")

    connection = connection or django_connection
    if connection.vendor != "postgresql":
        return []

    today = today or timezone.now().date()
    created = []
    with transaction.atomic(using=connection.alias), connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))", [_ADVISORY_LOCK_KEY]
        )
        if not _is_partitioned_parent(cursor):
            raise ChangeLogPartitioningError(
                f"{CHANGELOG_TABLE} is not a PostgreSQL partitioned table"
            )

        for start in _month_starts(today, months_ahead):
            name = partition_name(start)
            if _partition_exists(cursor, name):
                continue
            start_bound, end = month_bounds(start)
            cursor.execute(
                f"CREATE TABLE {connection.ops.quote_name(name)} "
                f"PARTITION OF {connection.ops.quote_name(CHANGELOG_TABLE)} "
                f"FOR VALUES FROM ({_utc_partition_bound(start_bound)}) "
                f"TO ({_utc_partition_bound(end)})"
            )
            created.append(name)
    return created
