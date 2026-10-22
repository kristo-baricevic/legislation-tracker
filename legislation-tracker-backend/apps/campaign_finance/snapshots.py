"""Compare itemized records only against comparable official reporting scopes."""
from decimal import Decimal, InvalidOperation
from django.db.models import Sum


def compare_totals(period, records, contributions, refunds):
    if len(records) != 1:
        return "unavailable"
    row = records[0]
    if (str(row.get("coverage_start_date", ""))[:10] != f"{period - 1}-01-01"
            or str(row.get("coverage_end_date", ""))[:10] != f"{period}-12-31"):
        return "incomparable_coverage"
    try:
        values = [Decimal(str(row[key])) for key in (
            "individual_itemized_contributions", "political_party_committee_contributions",
            "other_political_committee_contributions", "contribution_refunds",
        )]
    except (KeyError, InvalidOperation, TypeError):
        return "unavailable"
    if not all(value.is_finite() for value in values):
        return "unavailable"
    return "matched" if sum(values[:3]) == contributions and values[3] == refunds else "mismatch"


def reconciliation(snapshot):
    results = []
    for checkpoint in snapshot.checkpoints.filter(schedule="totals"):
        rows = snapshot.transactions.filter(committee=checkpoint.committee, effective=True)
        contributions = rows.filter(kind="contribution").aggregate(value=Sum("amount"))["value"] or Decimal(0)
        refunds = rows.filter(kind="refund").aggregate(value=Sum("amount"))["value"] or Decimal(0)
        results.append({"committee": checkpoint.committee_id, "status": compare_totals(
            snapshot.period, checkpoint.source_totals.get("records", []), contributions, refunds
        )})
    # Even matched totals do not establish an atomic upstream snapshot or
    # resolve every excluded earmark/adjustment. Coverage remains explicit.
    return results
