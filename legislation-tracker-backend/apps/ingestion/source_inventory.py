"""Count-only source inventory: HTTP GETs and DB SELECTs, never ingestion tasks."""

import time

from django.utils import timezone

from apps.legislation.models import Bill

from .congress_client import CongressAPIError, _request
from .models import IngestionWorkItem

BILL_TYPES = ("hr", "s")
MAX_PAGES = 80
MAX_SECONDS = 120


def snapshot_key(jurisdiction, congress, bill_types=BILL_TYPES):
    return (
        f"ingestion-readiness:{jurisdiction}:{congress}:{','.join(sorted(bill_types))}"
    )


def canonical_local_keys(congress):
    # No task-module import: inspection must never acquire ingestion behavior.
    result = set()
    for number in Bill.objects.filter(
        jurisdiction="federal", session=congress
    ).values_list("bill_number", flat=True):
        parts = number.upper().replace(".", "").split()
        if len(parts) == 2 and parts[0].lower() in BILL_TYPES and parts[1].isdigit():
            result.add(f"{congress}-{parts[0].lower()}-{int(parts[1])}")
    return result


def scan_inventory(congress, jurisdiction="federal", bill_types=BILL_TYPES):
    if (
        jurisdiction != "federal"
        or not 1 <= congress <= 200
        or tuple(sorted(bill_types)) != BILL_TYPES
    ):
        raise ValueError("Unsupported inventory scope")
    started = time.monotonic()
    snapshot = {
        "source": "Congress.gov API",
        "jurisdiction": jurisdiction,
        "congress": congress,
        "bill_types": list(BILL_TYPES),
        "checked_started_at": timezone.now().isoformat(),
        "complete": False,
        "ready_to_start": None,
        "missing_unqueued_metadata": None,
        "incremental_discoverable_count_available": False,
        "missing_bill_metadata": None,
        "pages_examined": 0,
        "identities_examined": 0,
        "error_code": None,
    }
    keys = set()
    try:
        for bill_type in BILL_TYPES:
            offset = 0
            expected_count = None
            type_keys = set()
            while True:
                if (
                    snapshot["pages_examined"] >= MAX_PAGES
                    or time.monotonic() - started >= MAX_SECONDS
                ):
                    raise ValueError("scan_budget_exceeded")
                data = _request(
                    "GET",
                    f"bill/{congress}/{bill_type}",
                    params={"sort": "updateDate desc", "limit": 250, "offset": offset},
                )
                snapshot["pages_examined"] += 1
                if time.monotonic() - started >= MAX_SECONDS:
                    raise ValueError("scan_budget_exceeded")
                items = data.get("bills")
                pagination = data.get("pagination")
                if (
                    not isinstance(items, list)
                    or not isinstance(pagination, dict)
                    or not isinstance(pagination.get("count"), int)
                    or isinstance(pagination.get("count"), bool)
                ):
                    raise ValueError("invalid_source_page")
                count = pagination["count"]
                if count < 0 or (
                    expected_count is not None and expected_count != count
                ):
                    raise ValueError("source_inventory_changed")
                expected_count = count
                for item in items:
                    item = item.get("bill", item)
                    number = str(item.get("number", ""))
                    if (
                        not number.isdigit()
                        or int(number) < 1
                        or item.get("congress") != congress
                        or str(item.get("type", "")).lower() != bill_type
                    ):
                        raise ValueError("invalid_source_identity")
                    key = f"{congress}-{bill_type}-{int(number)}"
                    if key in type_keys:
                        raise ValueError("source_inventory_changed")
                    type_keys.add(key)
                    snapshot["identities_examined"] += 1
                if len(type_keys) == count:
                    break
                if not items or len(items) != 250 or len(type_keys) > count:
                    raise ValueError("incomplete_source_inventory")
                offset += 250
                time.sleep(0.3)
            keys.update(type_keys)
        missing = keys - canonical_local_keys(congress)
        existing = set(
            IngestionWorkItem.objects.filter(
                jurisdiction=jurisdiction,
                congress=congress,
                kind="bill",
                status__in=["pending", "dispatched", "processing", "blocked", "dead"],
            ).values_list("dedupe_key", flat=True)
        )
        snapshot.update(
            complete=True,
            missing_bill_metadata=len(missing),
            missing_unqueued_metadata=len(missing - existing),
            already_scheduled_or_blocked=len(missing & existing),
        )
    except Exception as exc:
        # Never serialize exception strings: provider errors may contain credentials.
        allowed = {
            "scan_budget_exceeded",
            "invalid_source_page",
            "source_inventory_changed",
            "invalid_source_identity",
            "incomplete_source_inventory",
        }
        snapshot["error_code"] = (
            str(exc)
            if isinstance(exc, ValueError) and str(exc) in allowed
            else "source_check_unavailable"
        )
        if isinstance(exc, CongressAPIError) and exc.status_code == 429:
            snapshot["error_code"] = "source_rate_limited"
            snapshot["retry_after_seconds"] = max(
                180, min(86400, exc.retry_after_seconds or 180)
            )
    snapshot["checked_completed_at"] = timezone.now().isoformat()
    return snapshot
