from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.changelog import tasks


def test_partition_maintenance_task_reports_created_partitions(monkeypatch):
    monkeypatch.setattr(
        tasks,
        "ensure_change_log_partitions",
        lambda months_ahead: ["changelog_changelog_2026_09"],
    )

    assert tasks.ensure_change_log_partitions_task.run(months_ahead=3) == {
        "created": ["changelog_changelog_2026_09"],
        "months_ahead": 3,
    }


def test_partition_maintenance_command_is_explicit_and_bounded(monkeypatch):
    from apps.changelog.management.commands import ensure_changelog_partitions

    observed = []
    monkeypatch.setattr(
        ensure_changelog_partitions,
        "ensure_change_log_partitions",
        lambda months_ahead: observed.append(months_ahead)
        or ["changelog_changelog_2026_09"],
    )
    output = StringIO()

    call_command("ensure_changelog_partitions", "--months-ahead", "3", stdout=output)

    assert observed == [3]
    assert output.getvalue() == "created=1 partitions=changelog_changelog_2026_09\n"


@pytest.mark.parametrize(
    "arguments", [("--months-ahead", "-1"), ("--months-ahead", "-2")]
)
def test_partition_maintenance_command_rejects_negative_horizons(arguments):
    with pytest.raises(CommandError, match="zero or greater"):
        call_command("ensure_changelog_partitions", *arguments)
