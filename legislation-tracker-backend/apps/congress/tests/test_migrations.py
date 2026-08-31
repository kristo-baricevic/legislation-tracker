from datetime import UTC, datetime

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


def _applied_apps():
    executor = MigrationExecutor(connection)
    return executor.loader.project_state(
        list(executor.loader.applied_migrations)
    ).apps


@pytest.mark.django_db(transaction=True)
def test_vote_session_migration_preserves_unknown_legacy_sessions():
    executor = MigrationExecutor(connection)
    latest_targets = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("congress", "0005_representative_roster_fields")])
        old_apps = _applied_apps()
        Vote = old_apps.get_model("congress", "Vote")
        Bill = old_apps.get_model("legislation", "Bill")

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
            vote_date=datetime(2026, 1, 2, tzinfo=UTC),
            result="Passed",
        )

        executor = MigrationExecutor(connection)
        executor.migrate([("congress", "0006_vote_session_number")])
        migrated_apps = _applied_apps()
        MigratedVote = migrated_apps.get_model("congress", "Vote")

        assert MigratedVote.objects.get(pk=vote.pk).session_number is None
    finally:
        MigrationExecutor(connection).migrate(latest_targets)


@pytest.mark.django_db(transaction=True)
def test_vote_scope_migration_rejects_ambiguous_legacy_roll_call_identity():
    executor = MigrationExecutor(connection)
    latest_targets = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("congress", "0006_vote_session_number")])
        old_apps = _applied_apps()
        Bill = old_apps.get_model("legislation", "Bill")
        Vote = old_apps.get_model("congress", "Vote")
        bills = [
            Bill.objects.create(
                jurisdiction="federal",
                session=119,
                bill_number=f"HR {number}",
                title=f"Legacy bill {number}",
                status="Introduced",
            )
            for number in (100, 101)
        ]
        for bill in bills:
            Vote.objects.create(
                bill_id=bill.id,
                chamber="house",
                session_number=1,
                roll_number=10,
                vote_date=datetime(2026, 1, 2, tzinfo=UTC),
                result="Passed",
            )

        with pytest.raises(RuntimeError, match="ambiguous legacy vote identity"):
            MigrationExecutor(connection).migrate(
                [("congress", "0007_vote_scope_and_identity")]
            )

        Vote.objects.filter(bill_id=bills[1].id).delete()
    finally:
        MigrationExecutor(connection).migrate(latest_targets)


@pytest.mark.django_db(transaction=True)
def test_vote_scope_migration_refuses_lossy_reverse_with_procedural_votes():
    executor = MigrationExecutor(connection)
    latest_targets = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("congress", "0007_vote_scope_and_identity")])
        apps = _applied_apps()
        Vote = apps.get_model("congress", "Vote")
        vote = Vote.objects.create(
            bill_id=None,
            congress=119,
            chamber="senate",
            session_number=1,
            roll_number=11,
            vote_date=datetime(2026, 1, 2, tzinfo=UTC),
            result="Agreed",
        )

        with pytest.raises(RuntimeError, match="procedural votes without bills"):
            MigrationExecutor(connection).migrate(
                [("congress", "0006_vote_session_number")]
            )

        Vote.objects.filter(pk=vote.pk).delete()
    finally:
        MigrationExecutor(connection).migrate(latest_targets)
