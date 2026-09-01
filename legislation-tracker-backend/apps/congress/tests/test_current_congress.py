from datetime import UTC, date, datetime

import pytest
from django.test import override_settings

from apps.congress.current import current_congress, current_congress_session


@pytest.mark.parametrize(
    ("on_date", "expected"),
    [
        (date(2027, 1, 2), 119),
        (date(2027, 1, 3), 120),
        (date(2029, 1, 2), 120),
        (date(2029, 1, 3), 121),
    ],
)
def test_current_congress_changes_on_january_third(on_date, expected):
    assert current_congress(on_date) == expected


@pytest.mark.parametrize(
    ("on_date", "expected"),
    [
        (date(2027, 1, 2), 2),
        (date(2027, 1, 3), 1),
        (date(2028, 12, 31), 2),
    ],
)
def test_current_congress_session_preserves_the_january_third_boundary(
    on_date, expected
):
    assert current_congress_session(on_date) == expected


def test_current_congress_uses_the_washington_civil_date_for_instants():
    instant = datetime(2027, 1, 3, 3, 0, tzinfo=UTC)

    assert current_congress(instant) == 119


@override_settings(CURRENT_CONGRESS_OVERRIDE="121")
def test_current_congress_supports_an_environment_override():
    assert current_congress(date(2027, 1, 2)) == 121


@override_settings(CURRENT_CONGRESS_OVERRIDE="not-a-number")
def test_current_congress_rejects_an_invalid_override():
    with pytest.raises(ValueError, match="CURRENT_CONGRESS_OVERRIDE"):
        current_congress(date(2027, 1, 2))
