"""Resolve the active federal Congress at execution time."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

WASHINGTON_DC = ZoneInfo("America/New_York")


def current_congress(on_date=None) -> int:
    """Return the Congress active on the Washington, DC civil date."""

    override = str(getattr(settings, "CURRENT_CONGRESS_OVERRIDE", "") or "").strip()
    if override:
        try:
            congress = int(override)
        except ValueError as exc:
            raise ValueError(
                "CURRENT_CONGRESS_OVERRIDE must be a positive integer"
            ) from exc
        if congress < 1:
            raise ValueError("CURRENT_CONGRESS_OVERRIDE must be a positive integer")
        return congress

    if on_date is None:
        civil_date = timezone.now().astimezone(WASHINGTON_DC).date()
    elif isinstance(on_date, datetime):
        instant = on_date
        if timezone.is_naive(instant):
            instant = instant.replace(tzinfo=WASHINGTON_DC)
        civil_date = instant.astimezone(WASHINGTON_DC).date()
    elif isinstance(on_date, date):
        civil_date = on_date
    else:
        raise TypeError("on_date must be a date, datetime, or None")

    start_year = civil_date.year if civil_date.year % 2 else civil_date.year - 1
    if civil_date.year % 2 and (civil_date.month, civil_date.day) < (1, 3):
        start_year -= 2
    return ((start_year - 1789) // 2) + 1


def current_congress_session(on_date=None) -> int:
    """Return session 1 or 2 for the Congress active on the supplied date."""

    if on_date is None:
        civil_date = timezone.now().astimezone(WASHINGTON_DC).date()
    elif isinstance(on_date, datetime):
        instant = on_date
        if timezone.is_naive(instant):
            instant = instant.replace(tzinfo=WASHINGTON_DC)
        civil_date = instant.astimezone(WASHINGTON_DC).date()
    elif isinstance(on_date, date):
        civil_date = on_date
    else:
        raise TypeError("on_date must be a date, datetime, or None")

    congress = current_congress(civil_date)
    congress_start_year = 1789 + (congress - 1) * 2
    return 1 if civil_date.year == congress_start_year else 2
