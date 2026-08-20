from datetime import datetime, timezone

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.legislation.models import Bill


@pytest.mark.django_db(transaction=True)
def test_vote_session_migration_preserves_unknown_legacy_sessions():
    executor = MigrationExecutor(connection)
    executor.migrate([("congress", "0005_representative_roster_fields")])
    old_apps = executor.loader.project_state(
        [("congress", "0005_representative_roster_fields")]
    ).apps
    Vote = old_apps.get_model("congress", "Vote")

    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 99",
        title="Legacy vote bill",
        status="Introduced",
    )
    vote = Vote.objects.create(
        bill_id=bill.id,
        chamber="house",
        roll_number=1,
        vote_date=datetime(2026, 1, 2, tzinfo=timezone.utc),
        result="Passed",
    )

    executor = MigrationExecutor(connection)
    executor.migrate([("congress", "0006_vote_session_number")])
    migrated_apps = executor.loader.project_state(
        [("congress", "0006_vote_session_number")]
    ).apps
    MigratedVote = migrated_apps.get_model("congress", "Vote")

    assert MigratedVote.objects.get(pk=vote.pk).session_number is None
