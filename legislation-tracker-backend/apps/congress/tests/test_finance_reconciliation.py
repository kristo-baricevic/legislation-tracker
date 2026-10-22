from decimal import Decimal


def test_reconciliation_compares_only_identical_coverage():
    from apps.campaign_finance.snapshots import compare_totals
    official = {"coverage_start_date": "2025-01-01", "coverage_end_date": "2026-12-31", "individual_itemized_contributions": "100", "political_party_committee_contributions": "0", "other_political_committee_contributions": "50", "contribution_refunds": "25"}
    assert compare_totals(2026, [official], Decimal("150"), Decimal("25")) == "matched"
    assert compare_totals(2026, [official], Decimal("100"), Decimal("25")) == "mismatch"
    assert compare_totals(2026, [{**official, "coverage_end_date": "2026-06-30"}], Decimal("150"), Decimal("25")) == "incomparable_coverage"
    assert compare_totals(2026, [], Decimal("0"), Decimal("0")) == "unavailable"


def test_missing_or_nonfinite_totals_cannot_reconcile_as_zero():
    from apps.campaign_finance.snapshots import compare_totals
    official = {"coverage_start_date": "2025-01-01", "coverage_end_date": "2026-12-31"}
    assert compare_totals(2026, [official], Decimal("0"), Decimal("0")) == "unavailable"
