"""SELECT/GET-only estimate of bill identities creating new work in the next poll."""

import hashlib
import json
import time
from datetime import datetime

from django.utils import timezone

from .congress_client import CongressAPIError, _request, normalize_bill_list
from .discovery_semantics import (
    UNKNOWN_SOURCE_UPDATED_AT,
    _parse_congress_update_datetime,
    discovery_from_date_time,
    revision_creates_work,
)
from .models import IngestionState, IngestionWorkItem
from .source_inventory import BILL_TYPES, MAX_PAGES, MAX_SECONDS


def observation_basis(jurisdiction, congress):
    cursor = (
        IngestionState.objects.filter(jurisdiction=jurisdiction, congress=congress)
        .values_list("last_bill_update_seen_at", flat=True)
        .first()
    )
    # Work uniqueness/persistence is global by kind/key/revision, not by scope fields.
    rows = list(
        IngestionWorkItem.objects.filter(
            kind="bill", dedupe_key__startswith=f"{congress}-"
        )
        .order_by("dedupe_key", "source_updated_at")
        .values_list("dedupe_key", "source_updated_at")
    )
    encoded = [(key, stamp.isoformat()) for key, stamp in rows]
    basis = {
        "jurisdiction": jurisdiction,
        "congress": congress,
        "bill_types": list(BILL_TYPES),
        "cursor_at": cursor.isoformat() if cursor else None,
        "from_date_time": discovery_from_date_time(cursor),
        "work_revision_digest": hashlib.sha256(
            json.dumps(encoded).encode()
        ).hexdigest(),
    }
    return basis, rows


def observe_discoverable(
    congress, jurisdiction="federal", *, deadline=None, page_budget=MAX_PAGES
):
    if (
        jurisdiction != "federal"
        or not isinstance(congress, int)
        or isinstance(congress, bool)
        or not 1 <= congress <= 200
    ):
        raise ValueError("Unsupported discovery scope")
    started = time.monotonic()
    deadline = deadline if deadline is not None else started + MAX_SECONDS
    basis, rows = observation_basis(jurisdiction, congress)
    result = {
        "ready_to_start": None,
        "incremental_discoverable_count_available": False,
        "discovery_source_complete": False,
        "discovery_basis": basis,
        "discovery_checked_started_at": timezone.now().isoformat(),
        "discovery_pages_examined": 0,
        "discovery_error_code": None,
        "readiness_semantics": "Distinct bill identities whose observed source revision would create new bill work; includes updates, not retries of existing revisions.",
    }
    candidates = {}
    try:
        for bill_type in BILL_TYPES:
            offset = 0
            expected = None
            seen = set()
            while True:
                if (
                    time.monotonic() >= deadline
                    or result["discovery_pages_examined"] >= page_budget
                ):
                    raise ValueError("scan_budget_exceeded")
                params = {"sort": "updateDate desc", "limit": 250, "offset": offset}
                if basis["from_date_time"]:
                    params["fromDateTime"] = basis["from_date_time"]
                data = _request("GET", f"bill/{congress}/{bill_type}", params=params)
                result["discovery_pages_examined"] += 1
                if time.monotonic() >= deadline:
                    raise ValueError("scan_budget_exceeded")
                raw = data.get("bills")
                pagination = data.get("pagination")
                count = (
                    pagination.get("count") if isinstance(pagination, dict) else None
                )
                if (
                    not isinstance(raw, list)
                    or not isinstance(count, int)
                    or isinstance(count, bool)
                    or count < 0
                ):
                    raise ValueError("invalid_source_page")
                if expected is not None and count != expected:
                    raise ValueError("source_inventory_changed")
                expected = count
                items = normalize_bill_list(data, congress, bill_type)
                for item in items:
                    number = item["number"]
                    if not number.isdigit() or int(number) < 1:
                        raise ValueError("invalid_source_identity")
                    key = f"{congress}-{bill_type}-{number}"
                    if key in seen:
                        raise ValueError("source_inventory_changed")
                    seen.add(key)
                    revision = (
                        _parse_congress_update_datetime(item.get("updateDate"))
                        or UNKNOWN_SOURCE_UPDATED_AT
                    )
                    candidates[key] = max(candidates.get(key, revision), revision)
                if len(seen) == count:
                    break
                if not items or len(items) != 250 or len(seen) > count:
                    raise ValueError("incomplete_source_inventory")
                offset += 250
                time.sleep(0.3)
        result["discovery_source_complete"] = True
        if observation_basis(jurisdiction, congress)[0] != basis:
            raise ValueError("discovery_basis_changed")
        latest = {}
        for key, revision in rows:
            latest[key] = max(latest.get(key, revision), revision)
        result["ready_to_start"] = sum(
            revision_creates_work(latest.get(key), revision)
            for key, revision in candidates.items()
        )
        result["incremental_discoverable_count_available"] = True
    except Exception as exc:
        allowed = {
            "scan_budget_exceeded",
            "invalid_source_page",
            "source_inventory_changed",
            "invalid_source_identity",
            "incomplete_source_inventory",
            "discovery_basis_changed",
        }
        result["discovery_error_code"] = (
            str(exc)
            if isinstance(exc, ValueError) and str(exc) in allowed
            else "source_check_unavailable"
        )
        if isinstance(exc, CongressAPIError) and exc.status_code == 429:
            result["discovery_error_code"] = "source_rate_limited"
            result["retry_after_seconds"] = max(
                180, min(86400, exc.retry_after_seconds or 180)
            )
    result["discovery_checked_completed_at"] = timezone.now().isoformat()
    return result


def discoverable_snapshot_available(snapshot, jurisdiction, congress):
    try:
        stamp = datetime.fromisoformat(snapshot["discovery_checked_completed_at"])
        if timezone.is_naive(stamp):
            return False
        age = (timezone.now() - stamp).total_seconds()
        return (
            bool(snapshot.get("incremental_discoverable_count_available"))
            and bool(snapshot.get("discovery_source_complete"))
            and 0 <= age <= 300
            and snapshot.get("discovery_basis")
            == observation_basis(jurisdiction, congress)[0]
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
