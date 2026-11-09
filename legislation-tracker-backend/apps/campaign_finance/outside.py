"""Snapshot FEC's processed Schedule E aggregates, never sum notices and filings.

The provider aggregates revisions; refreshes create a new snapshot rather than
adding new totals to the old scan. Each page is committed with its checkpoint
under the research worker's lease and representative locks.
"""
import re
from decimal import Decimal, InvalidOperation
from django.db import transaction
from .models import OutsideSpendingTotal


def normalize_outside_total(row, candidate, period):
    if row.get("candidate_id") != candidate or row.get("cycle") != period:
        raise ValueError("outside_spending_scope_mismatch")
    spender = str(row.get("committee_id", ""))
    position = row.get("support_oppose_indicator")
    if not re.fullmatch(r"C\d{8}", spender) or position not in {"S", "O"}:
        raise ValueError("invalid_outside_spender")
    try:
        amount = Decimal(str(row["total"]))
        if not amount.is_finite() or amount < 0 or amount >= Decimal("1e18") or amount != amount.quantize(Decimal(".01")):
            raise ValueError("invalid_outside_amount")
    except (KeyError, InvalidOperation):
        raise ValueError("invalid_outside_amount") from None
    return dict(spender_id=spender, spender_name=str(row.get("committee_name") or spender)[:255], position=position, amount=amount)


@transaction.atomic
def persist_outside_page(scan, page):
    if scan.complete:
        return
    pages = page["pagination"].get("pages")
    if not isinstance(pages, int) or pages < 0 or pages > 1000 or page["pagination"].get("page", scan.page) != scan.page:
        raise ValueError("invalid_outside_pagination")
    if not page["results"] and scan.page < pages:
        raise ValueError("empty_outside_page")
    for raw in page["results"]:
        fields = normalize_outside_total(raw, scan.candidate_id, scan.snapshot.period)
        # A duplicate group across pages means upstream ordering changed. Retry
        # must not quietly publish an incomplete ranking.
        if OutsideSpendingTotal.objects.filter(scan=scan, spender_id=fields["spender_id"], position=fields["position"]).exists():
            raise ValueError("duplicate_outside_group")
        OutsideSpendingTotal.objects.create(scan=scan, **fields)
    scan.complete = scan.page >= pages
    scan.page += 1
    scan.save(update_fields=["complete", "page"])
