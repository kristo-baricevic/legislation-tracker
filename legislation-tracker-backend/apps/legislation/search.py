"""Public bill-search query validation, ranking, and safe highlights."""

from __future__ import annotations

import re
from dataclasses import dataclass

from django.contrib.postgres.search import SearchHeadline, SearchQuery, SearchRank
from django.db import connection
from django.db.models import Exists, F, FloatField, OuterRef, Q, QuerySet, Subquery

from .models import Bill, BillSearchChunk

MAX_QUERY_BYTES = 512
MAX_QUERY_TOKENS = 32
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
MARKER_START = "\ue000"
MARKER_END = "\ue001"


@dataclass(frozen=True)
class SearchSegment:
    text: str
    matched: bool


@dataclass(frozen=True)
class SearchHighlight:
    kind: str
    segments: tuple[SearchSegment, ...]


@dataclass(frozen=True)
class BillSearchHit:
    bill_id: int
    rank: float | None
    highlights: tuple[SearchHighlight, ...]


@dataclass(frozen=True)
class BillSearchQuery:
    q: str | None = None
    sort: str = "recent_activity"
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

    @classmethod
    def from_params(cls, params: dict) -> BillSearchQuery:
        q = params.get("q") or None
        return cls(
            q=q,
            sort=params.get("sort") or ("relevance" if q else "recent_activity"),
            page=params.get("page", 1),
            page_size=params.get("page_size", DEFAULT_PAGE_SIZE),
        )


@dataclass(frozen=True)
class BillSearchPage:
    count: int
    hits: tuple[BillSearchHit, ...]


def normalize_search_text(value: str) -> str:
    normalized = re.sub(r"\s+", " ", (value or "")).strip()
    if not normalized:
        raise ValueError("q must not be blank")
    if len(normalized.encode("utf-8")) > MAX_QUERY_BYTES:
        raise ValueError(f"q must not exceed {MAX_QUERY_BYTES} UTF-8 bytes")
    if len(re.findall(r"\S+", normalized)) > MAX_QUERY_TOKENS:
        raise ValueError(f"q must not exceed {MAX_QUERY_TOKENS} tokens")
    return normalized


def plain_highlight_segments(text: str, query: str) -> tuple[SearchSegment, ...]:
    """Return escaped-by-construction text segments; never HTML from the database."""
    clean_text = (text or "").replace(MARKER_START, "").replace(MARKER_END, "")
    terms = [term for term in re.findall(r"[\w'-]+", query.lower()) if term]
    ranges: list[tuple[int, int]] = []
    lowered = clean_text.lower()
    for term in terms:
        for match in re.finditer(re.escape(term), lowered):
            ranges.append(match.span())
    if not ranges:
        return (SearchSegment(text=clean_text[:240], matched=False),) if clean_text else ()
    ranges.sort()
    merged: list[tuple[int, int]] = []
    for start, end in ranges:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    result: list[SearchSegment] = []
    cursor = 0
    for start, end in merged:
        if cursor < start:
            result.append(SearchSegment(text=clean_text[cursor:start], matched=False))
        result.append(SearchSegment(text=clean_text[start:end], matched=True))
        cursor = end
    if cursor < len(clean_text):
        result.append(SearchSegment(text=clean_text[cursor:], matched=False))
    return tuple(segment for segment in result if segment.text)


def parse_headline_segments(headline: str) -> tuple[SearchSegment, ...]:
    """Parse only paired sentinels; malformed values downgrade to plain text."""
    if not headline:
        return ()
    result: list[SearchSegment] = []
    cursor = 0
    matched = False
    while cursor < len(headline):
        next_marker = headline.find(MARKER_END if matched else MARKER_START, cursor)
        if next_marker < 0:
            if matched:
                return (SearchSegment(headline.replace(MARKER_START, "").replace(MARKER_END, ""), False),)
            result.append(SearchSegment(headline[cursor:], False))
            break
        result.append(SearchSegment(headline[cursor:next_marker], matched))
        cursor = next_marker + 1
        matched = not matched
    if matched:
        return (SearchSegment(headline.replace(MARKER_START, "").replace(MARKER_END, ""), False),)
    return tuple(segment for segment in result if segment.text)


def _recent_order(queryset: QuerySet[Bill]) -> QuerySet[Bill]:
    return queryset.order_by(F("last_activity_sequence").desc(nulls_last=True), "-id")


def _metadata_match(queryset: QuerySet[Bill], query_text: str) -> QuerySet[Bill]:
    matching = queryset
    for term in re.findall(r"[\w'-]+", query_text.lower()):
        matching = matching.filter(
            Q(title__icontains=term)
            | Q(summary__icontains=term)
            | Q(bill_number__icontains=term)
            | Q(status__icontains=term)
            | Q(sponsor__name__icontains=term)
            | Q(sponsor__bioguide_id__icontains=term)
            | Q(bill_topics__topic__name__icontains=term)
        )
    return matching.distinct()


def _fallback_metadata_search(
    *, queryset: QuerySet[Bill], query: BillSearchQuery
) -> BillSearchPage:
    matching = _metadata_match(queryset, query.q).order_by("id")
    count = matching.count()
    offset = (query.page - 1) * query.page_size
    bills = list(matching[offset : offset + query.page_size])
    return BillSearchPage(
        count=count,
        hits=tuple(
            BillSearchHit(
                bill_id=bill.id,
                rank=None,
                highlights=(
                    SearchHighlight(
                        kind="metadata",
                        segments=plain_highlight_segments(
                            "\n".join(part for part in (bill.title, bill.summary or "") if part),
                            query.q,
                        ),
                    ),
                ),
            )
            for bill in bills
        ),
    )


def matching_bill_queryset(
    *, queryset: QuerySet[Bill], query_text: str
) -> QuerySet[Bill]:
    """Return matching bills without evaluating the result set in Python."""
    if connection.vendor != "postgresql":
        return _metadata_match(queryset, query_text)

    search_query = SearchQuery(query_text, search_type="websearch", config="english")
    all_chunks = BillSearchChunk.objects.filter(bill_id=OuterRef("pk"))
    ranked_chunks = (
        all_chunks.filter(search_vector=search_query)
        .annotate(_rank=SearchRank(F("search_vector"), search_query))
        .order_by("-_rank", "id")
    )
    projected = queryset.annotate(
        _has_search_projection=Exists(all_chunks),
        _search_rank=Subquery(
            ranked_chunks.values("_rank")[:1], output_field=FloatField()
        ),
    )
    indexed_matches = projected.filter(_search_rank__isnull=False)
    unindexed_matches = _metadata_match(
        projected.filter(_has_search_projection=False), query_text
    )
    # Existing bills remain discoverable while the projection backfill rolls
    # out; once indexed, their complete metadata/contract/document projection
    # is authoritative.
    return indexed_matches.union(unindexed_matches)


def _postgres_search(*, queryset: QuerySet[Bill], query: BillSearchQuery) -> BillSearchPage:
    search_query = SearchQuery(query.q, search_type="websearch", config="english")
    matching = matching_bill_queryset(queryset=queryset, query_text=query.q)
    ranked = queryset.filter(pk__in=matching.values("pk")).annotate(
        _search_rank=Subquery(
            BillSearchChunk.objects.filter(
                bill_id=OuterRef("pk"), search_vector=search_query
            )
            .annotate(_rank=SearchRank(F("search_vector"), search_query))
            .order_by("-_rank", "id")
            .values("_rank")[:1],
            output_field=FloatField(),
        )
    )
    if query.sort == "recent_activity":
        ranked = ranked.order_by(
            F("last_activity_sequence").desc(nulls_last=True), "-id"
        )
    else:
        ranked = ranked.order_by(F("_search_rank").desc(nulls_last=True), "id")
    count = ranked.count()
    offset = (query.page - 1) * query.page_size
    page_rows = list(
        ranked.values_list("id", "_search_rank")[offset : offset + query.page_size]
    )
    page_ids = [bill_id for bill_id, _rank in page_rows]
    rank_by_id = {
        bill_id: float(rank) if rank is not None else None
        for bill_id, rank in page_rows
    }
    chunks = (
        BillSearchChunk.objects.filter(
            bill_id__in=page_ids, search_vector=search_query
        )
        .annotate(
            _rank=SearchRank(F("search_vector"), search_query),
            _headline=SearchHeadline(
                "text",
                search_query,
                config="english",
                start_sel=MARKER_START,
                stop_sel=MARKER_END,
                max_words=35,
                min_words=10,
                max_fragments=1,
            ),
        )
        .order_by("bill_id", "-_rank", "id")
    )
    grouped: dict[int, list[tuple[float, str, str]]] = {}
    for chunk in chunks:
        entries = grouped.setdefault(chunk.bill_id, [])
        if len(entries) < 3:
            entries.append((float(chunk._rank), chunk.kind, chunk._headline))
    unindexed_metadata = {
        bill_id: (title, summary)
        for bill_id, title, summary in queryset.filter(
            pk__in=[bill_id for bill_id in page_ids if bill_id not in grouped]
        ).values_list("id", "title", "summary")
    }

    def highlights_for(bill_id: int) -> tuple[SearchHighlight, ...]:
        if bill_id in grouped:
            return tuple(
                SearchHighlight(
                    kind=kind,
                    segments=parse_headline_segments(headline),
                )
                for _rank, kind, headline in grouped[bill_id]
            )
        title, summary = unindexed_metadata.get(bill_id, ("", ""))
        return (
            SearchHighlight(
                kind="metadata",
                segments=plain_highlight_segments(
                    "\n".join(part for part in (title, summary or "") if part),
                    query.q,
                ),
            ),
        )
    return BillSearchPage(
        count=count,
        hits=tuple(
            BillSearchHit(
                bill_id=bill_id,
                rank=rank_by_id[bill_id],
                highlights=highlights_for(bill_id),
            )
            for bill_id in page_ids
        ),
    )


def search_bills(*, queryset: QuerySet[Bill], query: BillSearchQuery) -> BillSearchPage:
    """Search a pre-filtered bill queryset and retain one safe response shape."""
    if not query.q:
        ordered = _recent_order(queryset)
        count = ordered.count()
        offset = (query.page - 1) * query.page_size
        return BillSearchPage(
            count=count,
            hits=tuple(
                BillSearchHit(bill_id=bill.id, rank=None, highlights=())
                for bill in ordered[offset : offset + query.page_size]
            ),
        )
    normalized = normalize_search_text(query.q)
    query = BillSearchQuery(
        q=normalized,
        sort=query.sort,
        page=query.page,
        page_size=query.page_size,
    )
    if connection.vendor != "postgresql":
        return _fallback_metadata_search(queryset=queryset, query=query)
    return _postgres_search(queryset=queryset, query=query)


def apply_bill_list_filters(queryset: QuerySet[Bill], params: dict) -> QuerySet[Bill]:
    """Apply the public list filters before search ranking or activity counts."""
    session = params.get("session") or params.get("congress")
    if session is not None:
        queryset = queryset.filter(session=session)
    if params.get("jurisdiction"):
        queryset = queryset.filter(jurisdiction=params["jurisdiction"].strip())
    if params.get("id") is not None:
        queryset = queryset.filter(pk=params["id"])
    if params.get("bill_number"):
        queryset = queryset.filter(bill_number__icontains=params["bill_number"].strip())
    if params.get("status"):
        queryset = queryset.filter(status__icontains=params["status"].strip())
    if params.get("sponsor"):
        sponsor = params["sponsor"].strip()
        queryset = queryset.filter(
            sponsor_id=int(sponsor) if sponsor.isdigit() else None
        ) if sponsor.isdigit() else queryset.filter(sponsor__name__icontains=sponsor)
    if params.get("topic_id") is not None:
        queryset = queryset.filter(bill_topics__topic_id=params["topic_id"]).distinct()
    elif params.get("topic"):
        topic = params["topic"].strip()
        queryset = queryset.filter(
            Q(bill_topics__topic__name__icontains=topic)
            | Q(bill_topics__topic__slug__icontains=topic)
        ).distinct()
    return queryset
