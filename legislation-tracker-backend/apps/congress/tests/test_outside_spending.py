from decimal import Decimal
import pytest
from rest_framework.test import APIClient
from apps.congress.models import Representative
from apps.research.models import ResearchRun
from apps.campaign_finance.models import FinanceSnapshot

pytestmark = pytest.mark.django_db


def test_all_periods_combines_cycles_without_counting_replaced_snapshots():
    from apps.campaign_finance.models import OutsideSpendingScan, OutsideSpendingTotal
    from django.utils import timezone
    rep = Representative.objects.create(bioguide_id="T000098", name="Test")
    for period, amount, active in [(2024, 100, False), (2024, 200, True), (2026, 300, True)]:
        run = ResearchRun.objects.create(representative=rep, period=period, status="partial")
        snapshot = FinanceSnapshot.objects.create(run=run, representative=rep, period=period, active=active, published_at=timezone.now(), candidate_ids=["H0NY00001"])
        scan = OutsideSpendingScan.objects.create(snapshot=snapshot, candidate_id="H0NY00001", complete=True)
        OutsideSpendingTotal.objects.create(scan=scan, spender_id="C00000001", spender_name="Group", position="S", amount=amount)
    result = APIClient().get(f"/api/representatives/{rep.pk}/outside-spending/?all_periods=true").data
    assert result["count"] == 2
    assert Decimal(result["support"]) == 500
    assert {row["period"] for row in result["results"]} == {2024, 2026}
    assert all(f"cycle={row['period']}" in row["source_url"] for row in result["results"])


def test_outside_spending_pages_are_idempotent_and_separate_from_donations():
    from apps.campaign_finance.outside import persist_outside_page
    from apps.campaign_finance.models import OutsideSpendingScan
    rep = Representative.objects.create(bioguide_id="T000099", name="Test")
    run = ResearchRun.objects.create(representative=rep, period=2026, status="running")
    snapshot = FinanceSnapshot.objects.create(run=run, representative=rep, period=2026, candidate_ids=["H0NY00001"])
    scan = OutsideSpendingScan.objects.create(snapshot=snapshot, candidate_id="H0NY00001")
    row = {"candidate_id": "H0NY00001", "committee_id": "C00000001", "committee_name": "Example Super PAC", "cycle": 2026, "support_oppose_indicator": "S", "total": "1250000.25"}
    page = {"results": [row, {**row, "support_oppose_indicator": "O", "total": "50"}], "pagination": {"pages": 1, "page": 1}}
    persist_outside_page(scan, page)
    persist_outside_page(scan, page)
    assert scan.totals.count() == 2
    assert snapshot.transactions.count() == 0
    response = APIClient().get(f"/api/representatives/{rep.pk}/outside-spending/?period=2026").data
    assert Decimal(response["support"]) == Decimal("1250000.25")
    assert Decimal(response["oppose"]) == 50
    assert response["status"] == "available"
    assert response["count"] == 2
    snapshot.invalidated = True
    snapshot.save()
    assert APIClient().get(f"/api/representatives/{rep.pk}/outside-spending/?period=2026").data["status"] == "not_researched"


@pytest.mark.parametrize("change", [{"candidate_id": "H0NY00002"}, {"cycle": 2024}, {"support_oppose_indicator": "?"}, {"total": "NaN"}, {"total": "-10"}])
def test_outside_spending_rejects_wrong_scope_and_invalid_amounts(change):
    from apps.campaign_finance.outside import normalize_outside_total
    row = {"candidate_id": "H0NY00001", "committee_id": "C00000001", "cycle": 2026, "support_oppose_indicator": "S", "total": "10"}
    with pytest.raises(ValueError):
        normalize_outside_total({**row, **change}, "H0NY00001", 2026)
