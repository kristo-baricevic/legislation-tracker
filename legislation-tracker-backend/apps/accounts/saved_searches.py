"""Private saved-search normalization, activity counts, and acknowledgements."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from django.core import signing
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.changelog.models import BillActivityClock
from apps.legislation.models import Bill
from apps.legislation.search import (
    BillSearchQuery,
    apply_bill_list_filters,
    matching_bill_queryset,
    search_bills,
)

from .models import SavedBillSearch

WATERMARK_SALT = "accounts.saved-bill-search.watermark"
WATERMARK_VERSION = 1
MAX_SAVED_SEARCHES = 25


@dataclass(frozen=True)
class SavedSearchWatermark:
    sequence: int
    captured_at: datetime


def canonical_saved_query(value: object) -> tuple[dict, str]:
    """Validate public bill params, removing pagination and default values."""
    if not isinstance(value, dict):
        raise ValueError("query must be an object")
    from apps.legislation.serializers import BillListQuerySerializer

    serializer = BillListQuerySerializer(data=value)
    if not serializer.is_valid():
        raise ValueError(serializer.errors)
    normalized: dict = {}
    for key, item in serializer.validated_data.items():
        if key in {"page", "page_size"}:
            continue
        if key == "sort" and item == ("relevance" if serializer.validated_data.get("q") else "recent_activity"):
            continue
        normalized[key] = item
    rendered = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return normalized, hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def create_saved_search(*, user, name: str, query_json: dict, normalized_hash: str):
    with transaction.atomic():
        type(user).objects.select_for_update().get(pk=user.pk)
        if SavedBillSearch.objects.filter(user=user).count() >= MAX_SAVED_SEARCHES:
            raise ValueError(f"A maximum of {MAX_SAVED_SEARCHES} saved searches is allowed.")
        try:
            return SavedBillSearch.objects.create(
                user=user,
                name=name,
                query_json=query_json,
                normalized_hash=normalized_hash,
            )
        except IntegrityError as exc:
            raise ValueError("A saved search already uses that name or query.") from exc


def saved_search_queryset(search: SavedBillSearch):
    return apply_bill_list_filters(
        Bill.objects.select_related("sponsor", "latest_contract").prefetch_related(
            "bill_topics__topic"
        ),
        search.query_json,
    )


def count_saved_search_new_results(searches):
    """Count matching bills with activity newer than each private acknowledgement."""
    searches = list(searches)
    if connection.vendor == "postgresql" and searches:
        statements = []
        parameters = []
        for search in searches:
            queryset = saved_search_queryset(search)
            if search.last_opened_activity_sequence is None:
                queryset = queryset.filter(last_activity_sequence__isnull=False)
            else:
                queryset = queryset.filter(
                    last_activity_sequence__gt=search.last_opened_activity_sequence
                )
            query = BillSearchQuery.from_params(search.query_json)
            if query.q:
                queryset = matching_bill_queryset(
                    queryset=queryset,
                    query_text=query.q,
                )
            sql, params = queryset.values("pk").order_by().query.sql_with_params()
            statements.append(
                f"SELECT %s AS search_id, COUNT(*) AS result_count FROM ({sql}) saved_match"
            )
            parameters.extend([search.id, *params])
        with connection.cursor() as cursor:
            cursor.execute(" UNION ALL ".join(statements), parameters)
            return {search_id: count for search_id, count in cursor.fetchall()}

    counts = {}
    for search in searches:
        queryset = saved_search_queryset(search)
        if search.last_opened_activity_sequence is None:
            queryset = queryset.filter(last_activity_sequence__isnull=False)
        else:
            queryset = queryset.filter(
                last_activity_sequence__gt=search.last_opened_activity_sequence
            )
        page = search_bills(
            queryset=queryset,
            query=BillSearchQuery.from_params(search.query_json),
        )
        counts[search.id] = page.count
    return counts


def issue_saved_search_watermark(*, user_id: int, search: SavedBillSearch, sequence: int, captured_at: datetime) -> str:
    return signing.dumps(
        {
            "v": WATERMARK_VERSION,
            "u": user_id,
            "s": search.id,
            "h": search.normalized_hash,
            "q": sequence,
            "t": captured_at.isoformat(),
        },
        salt=WATERMARK_SALT,
        compress=True,
    )


def verify_saved_search_watermark(*, value: str, user_id: int, search: SavedBillSearch) -> SavedSearchWatermark:
    try:
        payload = signing.loads(value, salt=WATERMARK_SALT)
        if not isinstance(payload, dict) or payload.get("v") != WATERMARK_VERSION:
            raise ValueError("unsupported watermark")
        if payload.get("u") != user_id or payload.get("s") != search.id:
            raise ValueError("watermark does not belong to this saved search")
        if payload.get("h") != search.normalized_hash or not isinstance(payload.get("q"), int):
            raise ValueError("watermark does not match the current query")
        captured_at = datetime.fromisoformat(payload["t"])
    except (KeyError, TypeError, ValueError, signing.BadSignature) as exc:
        raise ValueError("Invalid result watermark.") from exc
    return SavedSearchWatermark(sequence=payload["q"], captured_at=captured_at)


def saved_search_result_page(*, user, search: SavedBillSearch, page: int, page_size: int):
    """Read results and capture a clock-bound acknowledgement watermark."""
    with transaction.atomic():
        clock = BillActivityClock.objects.select_for_update().get(pk=1)
        captured_at = timezone.now()
        captured_sequence = clock.committed_sequence
    result = search_bills(
        queryset=saved_search_queryset(search),
        query=BillSearchQuery.from_params(
            {**search.query_json, "page": page, "page_size": page_size}
        ),
    )
    watermark = issue_saved_search_watermark(
        user_id=user.id,
        search=search,
        sequence=captured_sequence,
        captured_at=captured_at,
    )
    return result, watermark


def open_saved_search(*, user, search: SavedBillSearch, watermark_value: str):
    watermark = verify_saved_search_watermark(
        value=watermark_value,
        user_id=user.id,
        search=search,
    )
    with transaction.atomic():
        locked = SavedBillSearch.objects.select_for_update().get(pk=search.id, user=user)
        prior_sequence = locked.last_opened_activity_sequence
        if prior_sequence is None or watermark.sequence > prior_sequence:
            locked.last_opened_activity_sequence = watermark.sequence
            locked.last_opened_at = watermark.captured_at
            locked.save(
                update_fields=["last_opened_activity_sequence", "last_opened_at", "updated_at"]
            )
    return locked, prior_sequence
