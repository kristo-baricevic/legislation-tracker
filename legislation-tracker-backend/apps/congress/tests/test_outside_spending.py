from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.campaign_finance.models import FinanceSnapshot
from apps.congress.models import Representative
from apps.research.models import ResearchRun

pytestmark = pytest.mark.django_db


def test_durbin_processed_fec_groups_survive_all_years_read():
    # Live aggregate values checked on 2026-11-17; no live calls in the test.
    from django.utils import timezone

    from apps.campaign_finance.models import OutsideSpendingScan
    from apps.campaign_finance.outside import persist_outside_page

    rep = Representative.objects.create(bioguide_id="D000563", name="Dick Durbin")
    groups = {
        2020: [
            ("C00483693", "S", "10.00"),
            ("C00489799", "S", "59.76"),
            ("C00571588", "O", "77000.00"),
        ],
        2026: [("C00489799", "S", "8.67")],
    }
    for cycle in (2016, 2018, 2020, 2022, 2024, 2026):
        run = ResearchRun.objects.create(
            representative=rep, period=cycle, status="partial"
        )
        snapshot = FinanceSnapshot.objects.create(
            run=run,
            representative=rep,
            period=cycle,
            active=True,
            published_at=timezone.now(),
            candidate_ids=["S6IL00151"],
        )
        scan = OutsideSpendingScan.objects.create(
            snapshot=snapshot, candidate_id="S6IL00151"
        )
        rows = [
            dict(
                candidate_id="S6IL00151",
                cycle=cycle,
                committee_id=committee,
                support_oppose_indicator=side,
                total=amount,
            )
            for committee, side, amount in groups.get(cycle, [])
        ]
        persist_outside_page(
            scan,
            {
                "results": rows,
                "pagination": {
                    "count": len(rows),
                    "page": 1,
                    "pages": 1 if rows else 0,
                },
            },
        )
    data = (
        APIClient()
        .get(f"/api/representatives/{rep.pk}/outside-spending/?all_periods=true")
        .data
    )
    assert Decimal(data["support"]) == Decimal("78.43")
    assert Decimal(data["oppose"]) == Decimal("77000.00")
    assert data["count"] == 4
    assert (
        data["status"] == "partial"
    )  # Legacy Schedule E-only snapshots need the other categories.


def test_missing_historical_period_is_not_reported_as_complete():
    from django.utils import timezone

    from apps.campaign_finance.models import (
        CandidateIdentity,
        OutsideSpendingScan,
        RepresentativeCandidate,
    )

    rep = Representative.objects.create(bioguide_id="D000563", name="Dick Durbin")
    candidate = CandidateIdentity.objects.create(
        fec_id="S6IL00151",
        reporting_periods={"checked_cycle": 2026, "periods": [2020, 2026]},
    )
    RepresentativeCandidate.objects.create(
        representative=rep,
        candidate=candidate,
        verified=True,
        periods=[2026],
        evidence_url="https://www.fec.gov/data/candidate/S6IL00151/",
    )
    run = ResearchRun.objects.create(representative=rep, period=2026, status="partial")
    snapshot = FinanceSnapshot.objects.create(
        run=run,
        representative=rep,
        period=2026,
        active=True,
        published_at=timezone.now(),
        candidate_ids=[candidate.pk],
    )
    OutsideSpendingScan.objects.create(
        snapshot=snapshot, candidate_id=candidate.pk, complete=True
    )
    data = (
        APIClient()
        .get(f"/api/representatives/{rep.pk}/outside-spending/?all_periods=true")
        .data
    )
    assert data["status"] == "partial"
    assert 2020 in data["failed_periods"]


@pytest.mark.parametrize("count", [2, -1, True])
def test_final_page_cannot_hide_missing_groups(count):
    from apps.campaign_finance.models import OutsideSpendingScan
    from apps.campaign_finance.outside import persist_outside_page

    rep = Representative.objects.create(bioguide_id="T000096", name="Test")
    run = ResearchRun.objects.create(representative=rep, period=2026)
    snapshot = FinanceSnapshot.objects.create(run=run, representative=rep, period=2026)
    scan = OutsideSpendingScan.objects.create(
        snapshot=snapshot, candidate_id="S6IL00151"
    )
    row = {
        "candidate_id": "S6IL00151",
        "cycle": 2026,
        "committee_id": "C00489799",
        "support_oppose_indicator": "S",
        "total": "8.67",
    }
    with pytest.raises(ValueError):
        persist_outside_page(
            scan,
            {"results": [row], "pagination": {"page": 1, "pages": 1, "count": count}},
        )
    scan.refresh_from_db()
    assert not scan.complete
    assert scan.totals.count() == 0


def test_outside_pages_batch_periods_and_reuse_totals_until_data_changes():
    from django.core.cache import cache
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from django.utils import timezone

    from apps.campaign_finance.models import OutsideSpendingScan, OutsideSpendingTotal

    cache.clear()
    rep = Representative.objects.create(bioguide_id="T000097", name="Test")
    for period in range(2016, 2028, 2):
        run = ResearchRun.objects.create(
            representative=rep, period=period, status="succeeded"
        )
        snapshot = FinanceSnapshot.objects.create(
            run=run,
            representative=rep,
            period=period,
            active=True,
            published_at=timezone.now(),
            candidate_ids=["H0NY00001"],
        )
        scan = OutsideSpendingScan.objects.create(
            snapshot=snapshot, candidate_id="H0NY00001", complete=True
        )
        row = OutsideSpendingTotal.objects.create(
            scan=scan,
            spender_id="C00000001",
            spender_name="Group",
            position="S",
            amount=100,
        )
    url = f"/api/representatives/{rep.pk}/outside-spending/?all_periods=true"
    client = APIClient()
    first = client.get(url).data
    with CaptureQueriesContext(connection) as queries:
        second = client.get(url).data
    assert Decimal(second["support"]) == 600
    assert (
        len(queries) <= 13
    )  # One bounded query also tracks outside-only backfill jobs.
    assert not any("SUM(" in q["sql"] for q in queries)
    assert second["revision"] == first["revision"]
    from apps.legislation.models import Bill

    Bill.objects.create(jurisdiction="federal", session=119, bill_number="HR 99")
    assert client.get(url).data["revision"] == first["revision"]
    OutsideSpendingTotal.objects.filter(pk=row.pk).update(amount=250)
    third = client.get(url).data
    assert Decimal(third["support"]) == 750
    assert third["revision"] != first["revision"]
    stale = client.get(url + f"&revision={first['revision']}&cursor=20")
    assert stale.status_code == 409


def test_all_periods_combines_cycles_without_counting_replaced_snapshots():
    from django.utils import timezone

    from apps.campaign_finance.models import OutsideSpendingScan, OutsideSpendingTotal

    rep = Representative.objects.create(bioguide_id="T000098", name="Test")
    for period, amount, active in [
        (2024, 100, False),
        (2024, 200, True),
        (2026, 300, True),
    ]:
        run = ResearchRun.objects.create(
            representative=rep, period=period, status="partial"
        )
        snapshot = FinanceSnapshot.objects.create(
            run=run,
            representative=rep,
            period=period,
            active=active,
            published_at=timezone.now(),
            candidate_ids=["H0NY00001"],
        )
        scan = OutsideSpendingScan.objects.create(
            snapshot=snapshot, candidate_id="H0NY00001", complete=True
        )
        OutsideSpendingTotal.objects.create(
            scan=scan,
            spender_id="C00000001",
            spender_name="Group",
            position="S",
            amount=amount,
        )
    result = (
        APIClient()
        .get(f"/api/representatives/{rep.pk}/outside-spending/?all_periods=true")
        .data
    )
    assert result["count"] == 2
    assert Decimal(result["support"]) == 500
    assert {row["period"] for row in result["results"]} == {2024, 2026}
    assert all(
        f"cycle={row['period']}" in row["source_url"] for row in result["results"]
    )


def test_outside_spending_pages_are_idempotent_and_separate_from_donations():
    from apps.campaign_finance.models import OutsideSpendingScan
    from apps.campaign_finance.outside import persist_outside_page

    rep = Representative.objects.create(bioguide_id="T000099", name="Test")
    run = ResearchRun.objects.create(representative=rep, period=2026, status="running")
    snapshot = FinanceSnapshot.objects.create(
        run=run, representative=rep, period=2026, candidate_ids=["H0NY00001"]
    )
    scan = OutsideSpendingScan.objects.create(
        snapshot=snapshot, candidate_id="H0NY00001"
    )
    row = {
        "candidate_id": "H0NY00001",
        "committee_id": "C00000001",
        "committee_name": "Example Super PAC",
        "cycle": 2026,
        "support_oppose_indicator": "S",
        "total": "1250000.25",
    }
    page = {
        "results": [row, {**row, "support_oppose_indicator": "O", "total": "50"}],
        "pagination": {"pages": 1, "page": 1},
    }
    persist_outside_page(scan, page)
    persist_outside_page(scan, page)
    for category in ["communication", "electioneering"]:
        other = OutsideSpendingScan.objects.create(
            snapshot=snapshot, candidate_id="H0NY00001", category=category
        )
        persist_outside_page(
            other, {"results": [], "pagination": {"page": 1, "pages": 0, "count": 0}}
        )
    assert scan.totals.count() == 2
    assert snapshot.transactions.count() == 0
    response = (
        APIClient()
        .get(f"/api/representatives/{rep.pk}/outside-spending/?period=2026")
        .data
    )
    assert Decimal(response["support"]) == Decimal("1250000.25")
    assert Decimal(response["oppose"]) == 50
    assert response["status"] == "available"
    assert response["count"] == 2
    snapshot.invalidated = True
    snapshot.save()
    assert (
        APIClient()
        .get(f"/api/representatives/{rep.pk}/outside-spending/?period=2026")
        .data["status"]
        == "not_researched"
    )


@pytest.mark.parametrize(
    "change",
    [
        {"candidate_id": "H0NY00002"},
        {"cycle": 2024},
        {"support_oppose_indicator": "?"},
        {"total": "NaN"},
        {"total": "-10"},
    ],
)
def test_outside_spending_rejects_wrong_scope_and_invalid_amounts(change):
    from apps.campaign_finance.outside import normalize_outside_total

    row = {
        "candidate_id": "H0NY00001",
        "committee_id": "C00000001",
        "cycle": 2026,
        "support_oppose_indicator": "S",
        "total": "10",
    }
    with pytest.raises(ValueError):
        normalize_outside_total({**row, **change}, "H0NY00001", 2026)
