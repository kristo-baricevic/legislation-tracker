"""Snapshot FEC's three processed outside-spending aggregates, not raw notices.

The provider aggregates revisions; refreshes create a new snapshot rather than
adding new totals to the old scan. Each page is committed with its checkpoint
under the research worker's lease and representative locks.
"""

import re
from decimal import Decimal, InvalidOperation

from django.db import transaction

from .models import OutsideSpendingScan, OutsideSpendingTotal

ENDPOINTS = {
    "independent": "schedules/schedule_e/by_candidate/",
    "communication": "communication_costs/by_candidate/",
    "electioneering": "electioneering/by_candidate/",
}


def ensure_outside_scans(snapshot):
    for candidate in snapshot.candidate_ids:
        for category in ENDPOINTS:
            OutsideSpendingScan.objects.get_or_create(
                snapshot=snapshot, candidate_id=candidate, category=category
            )


def outside_complete(snapshot):
    expected = {
        (candidate, category)
        for candidate in snapshot.candidate_ids
        for category in ENDPOINTS
    }
    return bool(expected) and expected == {
        (scan.candidate_id, scan.category)
        for scan in snapshot.outside_scans.all()
        if scan.complete
    }


def outside_page(scan):
    from .fec_client import get_page

    return get_page(
        ENDPOINTS[scan.category],
        {
            "candidate_id": scan.candidate_id,
            "cycle": scan.snapshot.period,
            "per_page": 100,
            "page": scan.page,
            "sort": "committee_id",
        },
    )


def normalize_outside_total(row, candidate, period, *, category="independent"):
    if category not in ENDPOINTS:
        raise ValueError("invalid_outside_category")
    if row.get("candidate_id") != candidate or row.get("cycle") != period:
        raise ValueError("outside_spending_scope_mismatch")
    spender = str(row.get("committee_id", ""))
    position = (
        "M" if category == "electioneering" else row.get("support_oppose_indicator")
    )
    allowed = (
        {"M"}
        if category == "electioneering"
        else {"S", "O", "24F", "24N"} if category == "communication" else {"S", "O"}
    )
    if not re.fullmatch(r"C\d{8}", spender) or position not in allowed:
        raise ValueError("invalid_outside_spender")
    try:
        amount = Decimal(str(row["total"]))
        if (
            not amount.is_finite()
            or amount < 0
            or amount >= Decimal("1e18")
            or amount != amount.quantize(Decimal(".01"))
        ):
            raise ValueError("invalid_outside_amount")
    except (KeyError, InvalidOperation):
        raise ValueError("invalid_outside_amount") from None
    return dict(
        spender_id=spender,
        spender_name=str(row.get("committee_name") or spender)[:255],
        position=position,
        amount=amount,
    )


@transaction.atomic
def persist_outside_page(scan, page):
    if scan.complete:
        return
    pages = page["pagination"].get("pages")
    if (
        type(pages) is not int
        or pages < 0
        or pages > 1000
        or page["pagination"].get("page", scan.page) != scan.page
    ):
        raise ValueError("invalid_outside_pagination")
    count = page["pagination"].get("count")
    if count is not None and (type(count) is not int or count < 0):
        raise ValueError("invalid_outside_count")
    if not page["results"] and scan.page < pages:
        raise ValueError("empty_outside_page")
    for raw in page["results"]:
        fields = normalize_outside_total(
            raw, scan.candidate_id, scan.snapshot.period, category=scan.category
        )
        # A duplicate group across pages means upstream ordering changed. Retry
        # must not quietly publish an incomplete ranking.
        if OutsideSpendingTotal.objects.filter(
            scan=scan, spender_id=fields["spender_id"], position=fields["position"]
        ).exists():
            raise ValueError("duplicate_outside_group")
        OutsideSpendingTotal.objects.create(scan=scan, **fields)
    complete = scan.page >= pages
    if complete and count is not None and scan.totals.count() != count:
        raise ValueError("outside_spending_count_mismatch")
    scan.complete = complete
    scan.page += 1
    scan.save(update_fields=["complete", "page"])
