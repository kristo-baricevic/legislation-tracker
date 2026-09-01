"""Deterministic, bounded projection of public bill material for search."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from .models import Bill, BillDocument, BillSearchChunk

SearchKind = Literal["metadata", "contract", "document"]
MAX_SEARCH_CHUNK_CHARS = 20_000


@dataclass(frozen=True)
class SearchSource:
    kind: SearchKind
    source_key: str
    text: str
    weight: str
    source_hash: str
    document_id: int | None = None
    contract_id: int | None = None


@dataclass(frozen=True)
class SearchIndexResult:
    bill_id: int
    changed: bool
    chunk_count: int
    source_updated_at: object


def _normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def project_reader_contract_text(contract_json: dict[str, object]) -> str:
    """Return only reader-facing statutory text from a persisted contract."""
    lines: list[str] = []
    seen: set[str] = set()

    def add(value: object) -> None:
        normalized = _normalize_text(value)
        identity = normalized.casefold()
        if normalized and identity not in seen:
            seen.add(identity)
            lines.append(normalized)

    orientation = contract_json.get("orientation")
    if isinstance(orientation, dict):
        add(orientation.get("purpose_clause"))

    for category in (
        "line_items",
        "requirements",
        "applicability",
        "amendment_operations",
    ):
        items = contract_json.get(category, [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    add(item.get("display_text") or item.get("text"))

    financial_items = contract_json.get("financial_items")
    if not isinstance(financial_items, list):
        financial_items = contract_json.get("funding_items", [])
    if isinstance(financial_items, list):
        for item in financial_items:
            if not isinstance(item, dict):
                continue
            display_text = item.get("display_text") or item.get("text")
            if display_text:
                add(display_text)
                continue
            fiscal_years = item.get("fiscal_years")
            fiscal_phrase = ""
            if isinstance(fiscal_years, list) and fiscal_years:
                fiscal_phrase = " fiscal years " + ", ".join(map(str, fiscal_years))
            add(
                " ".join(
                    str(value)
                    for value in (
                        item.get("financial_action"),
                        item.get("amount"),
                        item.get("purpose"),
                        fiscal_phrase,
                    )
                    if value
                )
            )

    for category in ("timeline_items", "definitions"):
        items = contract_json.get(category, [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    add(item.get("display_text") or item.get("text"))

    # The legacy deterministic contract uses reader text under these names.
    summary = contract_json.get("summary")
    if isinstance(summary, dict):
        add(summary.get("text"))
    for category in ("key_points", "funding_mentions", "effective_dates"):
        items = contract_json.get(category, [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    add(item.get("text"))
    if not lines:
        add(contract_json.get("plain_summary"))
    return "\n".join(lines)


def chunk_search_text(
    text: str, *, max_chars: int = MAX_SEARCH_CHUNK_CHARS
) -> list[str]:
    """Split text by paragraphs first, then safely split oversized paragraphs."""
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    chunks: list[str] = []
    current = ""
    for paragraph in re.split(r"\n\s*\n+", normalized):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        pieces = (
            [
                paragraph[index : index + max_chars]
                for index in range(0, len(paragraph), max_chars)
            ]
            if len(paragraph) > max_chars
            else [paragraph]
        )
        for piece in pieces:
            candidate = piece if not current else f"{current}\n\n{piece}"
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = piece
    if current:
        chunks.append(current)
    return chunks


def project_bill_search_sources(bill: Bill) -> list[SearchSource]:
    """Project only current public corpus data; never private user content."""
    bill = (
        Bill.objects.select_related("sponsor", "latest_contract")
        .prefetch_related("bill_topics__topic")
        .get(pk=bill.pk)
    )
    metadata_parts = [
        f"Bill number: {bill.bill_number}",
        f"Title: {bill.title}",
        f"Summary: {bill.summary or ''}",
        f"Status: {bill.status}",
    ]
    if bill.sponsor_id:
        metadata_parts.extend(
            [
                f"Sponsor: {bill.sponsor.name}",
                f"Sponsor Bioguide ID: {bill.sponsor.bioguide_id}",
            ]
        )
    topic_names = sorted(topic.topic.name for topic in bill.bill_topics.all())
    if topic_names:
        metadata_parts.append(f"Topics: {', '.join(topic_names)}")
    metadata_text = "\n".join(part for part in metadata_parts if _normalize_text(part))
    sources = [
        SearchSource(
            kind="metadata",
            source_key="metadata",
            text=metadata_text,
            weight="A",
            source_hash=_hash(metadata_text),
        )
    ]

    contract = bill.latest_contract
    if contract is not None:
        contract_text = project_reader_contract_text(contract.contract_json or {})
        if contract_text:
            sources.append(
                SearchSource(
                    kind="contract",
                    source_key=f"contract:{contract.id}:{contract.contract_hash}",
                    text=contract_text,
                    weight="B",
                    source_hash=_hash(contract_text),
                    contract_id=contract.id,
                    document_id=contract.document_id,
                )
            )

    active_document = (
        BillDocument.objects.filter(bill=bill, is_active_version=True)
        .order_by("-created_at", "-id")
        .first()
    )
    if active_document:
        document_text = active_document.extracted_text or active_document.raw_text or ""
        if document_text.strip():
            sources.append(
                SearchSource(
                    kind="document",
                    source_key=(
                        f"document:{active_document.id}:"
                        f"{active_document.content_hash or _hash(document_text)}"
                    ),
                    text=document_text,
                    weight="C",
                    source_hash=_hash(document_text),
                    document_id=active_document.id,
                )
            )
    return sources


def _desired_rows(bill: Bill) -> list[BillSearchChunk]:
    rows: list[BillSearchChunk] = []
    for source in project_bill_search_sources(bill):
        for ordinal, chunk in enumerate(chunk_search_text(source.text)):
            rows.append(
                BillSearchChunk(
                    bill_id=bill.id,
                    document_id=source.document_id,
                    contract_id=source.contract_id,
                    kind=source.kind,
                    source_key=source.source_key,
                    ordinal=ordinal,
                    text=chunk,
                    source_hash=_hash(f"{source.source_hash}:{ordinal}:{chunk}"),
                )
            )
    return sorted(rows, key=lambda row: (row.kind, row.source_key, row.ordinal))


def _same_projection(
    current: list[BillSearchChunk], desired: list[BillSearchChunk]
) -> bool:
    current_signature = [
        (
            row.kind,
            row.source_key,
            row.ordinal,
            row.source_hash,
            row.document_id,
            row.contract_id,
        )
        for row in current
    ]
    desired_signature = [
        (
            row.kind,
            row.source_key,
            row.ordinal,
            row.source_hash,
            row.document_id,
            row.contract_id,
        )
        for row in desired
    ]
    return current_signature == desired_signature


def latest_search_index_at(*, bill_id: int):
    """Return the freshest committed projection timestamp, if any."""
    return (
        BillSearchChunk.objects.filter(bill_id=bill_id)
        .order_by("-updated_at")
        .values_list("updated_at", flat=True)
        .first()
    )


def rebuild_bill_search_index(*, bill_id: int) -> SearchIndexResult:
    """Atomically replace a bill's search rows only when source hashes changed."""
    with transaction.atomic():
        bill = Bill.objects.select_for_update().get(pk=bill_id)
        desired = _desired_rows(bill)
        current = list(
            BillSearchChunk.objects.select_for_update()
            .filter(bill=bill)
            .order_by("kind", "source_key", "ordinal")
        )
        if _same_projection(current, desired):
            return SearchIndexResult(
                bill_id=bill.id,
                changed=False,
                chunk_count=len(current),
                source_updated_at=bill.updated_at,
            )
        BillSearchChunk.objects.filter(bill=bill).delete()
        BillSearchChunk.objects.bulk_create(desired)
        if connection.vendor == "postgresql" and desired:
            from django.contrib.postgres.search import SearchVector

            for kind, weight in (
                ("metadata", "A"),
                ("contract", "B"),
                ("document", "C"),
            ):
                BillSearchChunk.objects.filter(bill=bill, kind=kind).update(
                    search_vector=SearchVector(
                        F("text"), config="english", weight=weight
                    )
                )
        return SearchIndexResult(
            bill_id=bill.id,
            changed=True,
            chunk_count=len(desired),
            source_updated_at=timezone.now(),
        )
