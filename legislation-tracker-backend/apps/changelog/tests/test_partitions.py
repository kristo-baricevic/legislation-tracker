from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime

import pytest
from django.db import connection, connections
from django.db.migrations.executor import MigrationExecutor

from apps.changelog.models import ChangeLog
from apps.changelog.partitions import (
    ensure_change_log_partitions,
    month_bounds,
    partition_name,
)
from apps.legislation.models import Bill

POSTGRESQL_ONLY = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="requires PostgreSQL partitions"
)

_PRE_PARTITION_MIGRATION = (
    "changelog",
    "0002_rename_changelog_c_created_2a3b4c_idx_changelog_c_created_64c4f2_idx_and_more",
)
_PARTITION_MIGRATION = ("changelog", "0003_partition_by_created_at")
_EXPECTED_PARENT_INDEXES = {
    "changelog_c_bill_id_2b8ac2_idx",
    "changelog_c_change__7f1933_idx",
    "changelog_c_created_64c4f2_idx",
    "changelog_changelog_bill_id_a3ee17ab",
    "changelog_changelog_change_type_f10a7310",
    "changelog_changelog_change_type_f10a7310_like",
    "changelog_changelog_contract_id_da17a066",
    "changelog_changelog_created_at_fb264109",
    "changelog_changelog_document_id_29ce49b9",
    "changelog_changelog_pkey",
    "changelog_created_bill_idx",
}


def _applied_apps():
    executor = MigrationExecutor(connection)
    return executor.loader.project_state(
        list(executor.loader.applied_migrations)
    ).apps


def test_month_bounds_roll_over_december():
    assert month_bounds(date(2026, 12, 25)) == (
        datetime(2026, 12, 1, tzinfo=UTC),
        datetime(2027, 1, 1, tzinfo=UTC),
    )


def test_partition_name_uses_the_month_start():
    assert partition_name(date(2026, 8, 31)) == "changelog_changelog_2026_08"


@pytest.mark.skipif(connection.vendor != "sqlite", reason="covers the SQLite fallback")
@pytest.mark.django_db
def test_partition_maintenance_is_a_noop_on_sqlite():
    assert connection.vendor == "sqlite"
    assert ensure_change_log_partitions(connection=connection) == []


@POSTGRESQL_ONLY
@pytest.mark.django_db(transaction=True)
def test_partition_migration_preserves_data_indexes_sequences_and_relations(request):
    """Exercise the real 0002 -> 0003 -> 0002 conversion on PostgreSQL."""
    executor = MigrationExecutor(connection)
    latest_targets = executor.loader.graph.leaf_nodes()
    request.addfinalizer(
        lambda: MigrationExecutor(connection).migrate(latest_targets)
    )
    executor.migrate([_PRE_PARTITION_MIGRATION])
    old_apps = _applied_apps()
    OldChangeLog = old_apps.get_model("changelog", "ChangeLog")
    OldBill = old_apps.get_model("legislation", "Bill")
    bill = OldBill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR PARTITION 1",
        title="Partition migration test",
        status="Introduced",
    )
    first = OldChangeLog.objects.create(
        bill_id=bill.id,
        change_type="status_update",
        new_value={"status": "introduced"},
    )
    second = OldChangeLog.objects.create(
        bill_id=bill.id,
        change_type="contract_update",
        old_value={"version": 1},
        new_value={"version": 2},
    )
    first_created_at = datetime(2026, 1, 31, 23, 59, tzinfo=UTC)
    second_created_at = datetime(2026, 2, 1, 0, 0, tzinfo=UTC)
    OldChangeLog.objects.filter(pk=first.pk).update(created_at=first_created_at)
    OldChangeLog.objects.filter(pk=second.pk).update(created_at=second_created_at)
    source_sequence_high_water_mark = second.pk + 50
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT setval("
            "pg_get_serial_sequence('changelog_changelog', 'id')::regclass, "
            "%s, true)",
            [source_sequence_high_water_mark],
        )

    try:
        executor = MigrationExecutor(connection)
        executor.migrate([_PARTITION_MIGRATION])
        partitioned_apps = _applied_apps()
        PartitionedChangeLog = partitioned_apps.get_model("changelog", "ChangeLog")
        PartitionedBill = partitioned_apps.get_model("legislation", "Bill")
        PartitionedBillDocument = partitioned_apps.get_model(
            "legislation", "BillDocument"
        )
        PartitionedBillContract = partitioned_apps.get_model(
            "legislation", "BillContract"
        )

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT relkind FROM pg_class "
                "WHERE oid = 'changelog_changelog'::regclass"
            )
            assert cursor.fetchone()[0] == "p"
            cursor.execute(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = current_schema() "
                "AND tablename = 'changelog_changelog'"
            )
            assert {row[0] for row in cursor.fetchall()} == _EXPECTED_PARENT_INDEXES
            cursor.execute(
                "SELECT bool_and(index_info.indisvalid) "
                "FROM pg_index AS index_info "
                "WHERE index_info.indrelid IN ("
                "SELECT inhrelid FROM pg_inherits "
                "WHERE inhparent = 'changelog_changelog'::regclass"
                ")"
            )
            assert cursor.fetchone()[0] is True
            cursor.execute(
                "SELECT tableoid::regclass::text FROM changelog_changelog "
                "WHERE id = %s AND created_at = %s",
                [first.pk, first_created_at],
            )
            assert cursor.fetchone()[0] == "changelog_changelog_2026_01"
            cursor.execute(
                "SELECT tableoid::regclass::text FROM changelog_changelog "
                "WHERE id = %s AND created_at = %s",
                [second.pk, second_created_at],
            )
            assert cursor.fetchone()[0] == "changelog_changelog_2026_02"

        assert PartitionedChangeLog.objects.get(pk=first.pk).new_value == {"status": "introduced"}
        assert PartitionedChangeLog.objects.get(pk=second.pk).old_value == {"version": 1}
        fresh = PartitionedChangeLog.objects.create(
            bill_id=bill.id,
            change_type="status_update",
            new_value={"status": "updated"},
        )
        assert fresh.pk == source_sequence_high_water_mark + 1

        relation_bill = PartitionedBill.objects.create(
            jurisdiction="federal",
            session=119,
            bill_number="HR PARTITION 2",
            title="Partition relation test",
            status="Introduced",
        )
        document = PartitionedBillDocument.objects.create(
            bill=relation_bill,
            version_label="Introduced",
        )
        contract = PartitionedBillContract.objects.create(
            bill=relation_bill,
            document=document,
            contract_hash="partition-test-contract",
        )
        related = PartitionedChangeLog.objects.create(
            bill=relation_bill,
            document=document,
            contract=contract,
            change_type="contract_update",
            new_value={"contract": "created"},
        )
        document.delete()
        related.refresh_from_db()
        assert related.document_id is None
        assert related.contract_id is None
        relation_bill.delete()
        assert not PartitionedChangeLog.objects.filter(pk=related.pk).exists()

        reverse_sequence_high_water_mark = fresh.pk + 50
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT setval("
                "pg_get_serial_sequence('changelog_changelog', 'id')::regclass, "
                "%s, true)",
                [reverse_sequence_high_water_mark],
            )

        executor = MigrationExecutor(connection)
        executor.migrate([_PRE_PARTITION_MIGRATION])
        restored_apps = _applied_apps()
        RestoredChangeLog = restored_apps.get_model("changelog", "ChangeLog")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT array_agg(attribute.attname ORDER BY key_column.ordinality) "
                "FROM pg_constraint AS pk_constraint "
                "JOIN unnest(pk_constraint.conkey) WITH ORDINALITY "
                "AS key_column(attnum, ordinality) ON TRUE "
                "JOIN pg_attribute AS attribute "
                "ON attribute.attrelid = pk_constraint.conrelid "
                "AND attribute.attnum = key_column.attnum "
                "WHERE pk_constraint.conrelid = 'changelog_changelog'::regclass "
                "AND pk_constraint.contype = 'p' "
                "GROUP BY pk_constraint.oid"
            )
            assert cursor.fetchone()[0] == ["id"]
        assert list(
            RestoredChangeLog.objects.filter(bill_id=bill.id)
            .order_by("id")
            .values_list("new_value", flat=True)
        ) == [
            {"status": "introduced"},
            {"version": 2},
            {"status": "updated"},
        ]
        restored = RestoredChangeLog.objects.create(
            bill_id=bill.id,
            change_type="status_update",
            new_value={"status": "restored"},
        )
        assert restored.pk == reverse_sequence_high_water_mark + 1
    finally:
        MigrationExecutor(connection).migrate(latest_targets)


@POSTGRESQL_ONLY
@pytest.mark.django_db(transaction=True)
def test_partition_maintenance_uses_utc_boundaries_when_session_timezone_differs():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR PARTITION 3",
        title="UTC partition boundary test",
        status="Introduced",
    )
    with connection.cursor() as cursor:
        cursor.execute("SET TIME ZONE 'America/Los_Angeles'")
    try:
        ensure_change_log_partitions(
            connection=connection, today=date(2030, 1, 1), months_ahead=1
        )
        event = ChangeLog.objects.create(
            bill=bill,
            change_type="status_update",
            new_value={"status": "updated"},
        )
        created_at = datetime(2030, 2, 1, 0, 0, tzinfo=UTC)
        ChangeLog.objects.filter(pk=event.pk).update(created_at=created_at)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tableoid::regclass::text FROM changelog_changelog "
                "WHERE id = %s AND created_at = %s",
                [event.pk, created_at],
            )
            assert cursor.fetchone()[0] == "changelog_changelog_2030_02"
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SET TIME ZONE 'UTC'")


@POSTGRESQL_ONLY
@pytest.mark.django_db(transaction=True)
def test_partition_maintenance_serializes_concurrent_creators():
    month = date(2031, 1, 1)

    def maintain_partitions():
        thread_connection = connections["default"]
        try:
            return ensure_change_log_partitions(
                connection=thread_connection, today=month, months_ahead=0
            )
        finally:
            thread_connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        created = list(executor.map(lambda _: maintain_partitions(), range(2)))

    assert sorted(partition for result in created for partition in result) == [
        "changelog_changelog_2031_01"
    ]
