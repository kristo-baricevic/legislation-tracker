from decimal import Decimal

import pytest
from django.db import connection
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_category_migration_preserves_legacy_totals_and_blocks_lossy_rollback():
    old = [("campaign_finance", "0010_outside_revision_triggers")]
    new = [("campaign_finance", "0012_communication_position_codes")]
    executor = MigrationExecutor(connection)
    executor.migrate(old)
    try:
        apps = executor.loader.project_state(old).apps
        rep = apps.get_model("congress", "Representative").objects.create(
            bioguide_id="D000563", name="Durbin"
        )
        run = apps.get_model("research", "ResearchRun").objects.create(
            representative_id=rep.pk, period=2020
        )
        snapshot = apps.get_model("campaign_finance", "FinanceSnapshot").objects.create(
            representative_id=rep.pk,
            run_id=run.pk,
            period=2020,
            candidate_ids=["S6IL00151"],
        )
        scan = apps.get_model("campaign_finance", "OutsideSpendingScan").objects.create(
            snapshot_id=snapshot.pk, candidate_id="S6IL00151", complete=True, page=2
        )
        total = apps.get_model(
            "campaign_finance", "OutsideSpendingTotal"
        ).objects.create(
            scan_id=scan.pk, spender_id="C00571588", position="O", amount="77000.00"
        )
        executor = MigrationExecutor(connection)
        executor.migrate(new)
        apps = executor.loader.project_state(new).apps
        scans = apps.get_model("campaign_finance", "OutsideSpendingScan")
        assert scans.objects.get(pk=scan.pk).category == "independent"
        assert scans.objects.get(pk=scan.pk).complete
        assert apps.get_model("campaign_finance", "OutsideSpendingTotal").objects.get(
            pk=total.pk
        ).amount == Decimal("77000.00")
        additional = scans.objects.create(
            snapshot_id=snapshot.pk, candidate_id="S6IL00151", category="communication"
        )
        with pytest.raises(IrreversibleError):
            MigrationExecutor(connection).migrate(old)
        additional.delete()
        MigrationExecutor(connection).migrate(
            old
        )  # Safe rollback when only legacy data remains.
    finally:
        MigrationExecutor(connection).migrate(new)
