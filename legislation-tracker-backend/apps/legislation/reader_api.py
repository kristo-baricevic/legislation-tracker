"""Bounded public projections for immutable 2.1 reader contracts."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from rest_framework import serializers

from .models import Bill, BillContract

READER_SCHEMA_VERSION = "2.1-legal-nlp"
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
SUMMARY_PREVIEW_LIMIT = 1_200


class ReaderContractUnavailable(Exception):
    """The stored contract cannot serve the bounded reader projection."""


def _contract_json(contract: BillContract) -> dict[str, Any]:
    payload = contract.contract_json
    if (
        contract.schema_version != READER_SCHEMA_VERSION
        or not isinstance(contract.contract_hash, str)
        or not contract.contract_hash.strip()
        or not isinstance(payload, dict)
        or payload.get("schema_version") != READER_SCHEMA_VERSION
    ):
        raise ReaderContractUnavailable
    return payload


def _array(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise serializers.ValidationError({key: ["Stored reader data is invalid."]})
    return value


def _validated_page(
    values: Sequence[dict[str, Any]],
    *,
    page: int,
    page_size: int,
    serializer_class,
) -> dict[str, Any]:
    if page < 1:
        raise serializers.ValidationError(
            {"page": ["Ensure this value is at least 1."]}
        )
    if page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise serializers.ValidationError(
            {"page_size": [f"Ensure this value is at most {MAX_PAGE_SIZE}."]}
        )
    count = len(values)
    start = (page - 1) * page_size
    projected = list(values[start : start + page_size])
    serializer = serializer_class(data=projected, many=True)
    serializer.is_valid(raise_exception=True)
    return {
        "count": count,
        "next": page + 1 if start + page_size < count else None,
        "previous": page - 1 if page > 1 else None,
        "results": serializer.data,
    }


def _item_by_id(
    items: Sequence[dict[str, Any]], item_id: str, *, query_field: str
) -> dict[str, Any]:
    item = next(
        (candidate for candidate in items if candidate.get("id") == item_id), None
    )
    if item is None:
        raise serializers.ValidationError(
            {query_field: ["Unknown contract-local item ID."]}
        )
    return item


def _valid_section(payload: dict[str, Any], section_id: str) -> None:
    groups = _array(payload, "section_groups")
    if not any(group.get("source_id") == section_id for group in groups):
        raise serializers.ValidationError(
            {"section_id": ["Unknown contract-local section ID."]}
        )


def _financial_preview(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item.get(key)
        for key in (
            "id",
            "display_text",
            "financial_action",
            "direction",
            "amount",
            "amount_type",
            "currency",
            "fiscal_years",
        )
    }


def _timeline_preview(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item.get(key)
        for key in (
            "id",
            "display_text",
            "timeline_type",
            "date",
            "relative_value",
            "relative_unit",
            "trigger",
        )
    }


def _public_financial(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **_financial_preview(item),
        **{
            key: item.get(key)
            for key in (
                "source_id",
                "section_id",
                "section_label",
                "section_path",
                "purpose",
                "source_account",
                "destination_account",
            )
        },
    }


def _public_timeline(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **_timeline_preview(item),
        **{
            key: item.get(key)
            for key in ("source_id", "section_id", "section_label", "section_path")
        },
    }


def _public_definition(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item.get(key)
        for key in (
            "id",
            "source_id",
            "section_id",
            "section_label",
            "section_path",
            "display_text",
            "term",
            "definition",
            "definition_type",
        )
    }


def reader_items_page(
    contract: BillContract, *, page: int, page_size: int
) -> dict[str, Any]:
    from .serializers import ReaderLineItemPublicSerializer

    if page < 1:
        raise serializers.ValidationError(
            {"page": ["Ensure this value is at least 1."]}
        )
    if page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise serializers.ValidationError(
            {"page_size": [f"Ensure this value is at most {MAX_PAGE_SIZE}."]}
        )
    payload = _contract_json(contract)
    lines = _array(payload, "line_items")
    financial_items = _array(payload, "financial_items")
    timeline_items = _array(payload, "timeline_items")
    definitions = _array(payload, "definitions")
    financial_by_id = {item.get("id"): item for item in financial_items}
    timeline_by_id = {item.get("id"): item for item in timeline_items}
    definition_ids = {item.get("id") for item in definitions}
    start = (page - 1) * page_size
    page_lines = lines[start : start + page_size]
    projected = []
    for line in page_lines:
        financial_refs = set(line.get("exact_financial_refs") or [])
        timeline_refs = set(line.get("timeline_refs") or [])
        definition_refs = set(line.get("definition_refs") or [])
        ordered_financial = [
            item for item in financial_items if item.get("id") in financial_refs
        ]
        ordered_timeline = [
            item for item in timeline_items if item.get("id") in timeline_refs
        ]
        projected.append(
            {
                key: line.get(key)
                for key in (
                    "id",
                    "source_id",
                    "section_id",
                    "section_path",
                    "kind",
                    "display_text",
                    "actor",
                    "action",
                    "effect",
                )
            }
            | {
                "exact_financial_count": sum(
                    item_id in financial_by_id for item_id in financial_refs
                ),
                "exact_financial_preview": [
                    _financial_preview(item) for item in ordered_financial[:3]
                ],
                "timeline_count": sum(
                    item_id in timeline_by_id for item_id in timeline_refs
                ),
                "timeline_preview": [
                    _timeline_preview(item) for item in ordered_timeline[:3]
                ],
                "definition_count": sum(
                    item_id in definition_ids for item_id in definition_refs
                ),
            }
        )
    result = _validated_page(
        projected,
        page=1,
        page_size=page_size,
        serializer_class=ReaderLineItemPublicSerializer,
    )
    result["count"] = len(lines)
    result["next"] = page + 1 if start + page_size < len(lines) else None
    result["previous"] = page - 1 if page > 1 else None

    group_by_section = {
        group.get("source_id"): group for group in _array(payload, "section_groups")
    }
    supplements = []
    seen_sections = set()
    for line in page_lines:
        section_id = line.get("section_id")
        if section_id in seen_sections:
            continue
        seen_sections.add(section_id)
        group = group_by_section.get(section_id, {})
        supplements.append(
            {
                "section_id": section_id,
                "section_path": group.get("section_path") or line.get("section_path"),
                "section_financial_count": len(
                    {
                        item_id
                        for item_id in group.get("section_financial_refs") or []
                        if item_id in financial_by_id
                    }
                ),
                "section_timeline_count": len(
                    {
                        item_id
                        for item_id in group.get("section_timeline_refs") or []
                        if item_id in timeline_by_id
                    }
                ),
            }
        )
    result["section_supplements"] = supplements
    return result


def financial_items_page(
    contract: BillContract,
    *,
    page: int,
    page_size: int,
    financial_action: str | None = None,
    fiscal_year: int | None = None,
    line_item_id: str | None = None,
    section_id: str | None = None,
) -> dict[str, Any]:
    from .serializers import FinancialItemPublicSerializer

    payload = _contract_json(contract)
    items = _array(payload, "financial_items")
    if line_item_id is not None:
        line = _item_by_id(
            _array(payload, "line_items"), line_item_id, query_field="line_item_id"
        )
        references = set(line.get("exact_financial_refs") or [])
        items = [item for item in items if item.get("id") in references]
    elif section_id is not None:
        _valid_section(payload, section_id)
        group = next(
            group
            for group in _array(payload, "section_groups")
            if group.get("source_id") == section_id
        )
        references = set(group.get("section_financial_refs") or [])
        items = [item for item in items if item.get("id") in references]
    if financial_action is not None:
        items = [
            item for item in items if item.get("financial_action") == financial_action
        ]
    if fiscal_year is not None:
        items = [
            item for item in items if fiscal_year in (item.get("fiscal_years") or [])
        ]
    return _validated_page(
        [_public_financial(item) for item in items],
        page=page,
        page_size=page_size,
        serializer_class=FinancialItemPublicSerializer,
    )


def timeline_items_page(
    contract: BillContract,
    *,
    page: int,
    page_size: int,
    line_item_id: str | None = None,
    section_id: str | None = None,
) -> dict[str, Any]:
    from .serializers import TimelineItemPublicSerializer

    payload = _contract_json(contract)
    items = _array(payload, "timeline_items")
    if line_item_id is not None:
        line = _item_by_id(
            _array(payload, "line_items"), line_item_id, query_field="line_item_id"
        )
        references = set(line.get("timeline_refs") or [])
        items = [item for item in items if item.get("id") in references]
    elif section_id is not None:
        _valid_section(payload, section_id)
        group = next(
            group
            for group in _array(payload, "section_groups")
            if group.get("source_id") == section_id
        )
        references = set(group.get("section_timeline_refs") or [])
        items = [item for item in items if item.get("id") in references]
    return _validated_page(
        [_public_timeline(item) for item in items],
        page=page,
        page_size=page_size,
        serializer_class=TimelineItemPublicSerializer,
    )


def definition_items_page(
    contract: BillContract,
    *,
    page: int,
    page_size: int,
    line_item_id: str | None = None,
    unlinked: bool | None = None,
) -> dict[str, Any]:
    from .serializers import DefinitionItemPublicSerializer

    payload = _contract_json(contract)
    items = _array(payload, "definitions")
    lines = _array(payload, "line_items")
    linked_ids = {
        item_id for line in lines for item_id in (line.get("definition_refs") or [])
    }
    if line_item_id is not None:
        line = _item_by_id(lines, line_item_id, query_field="line_item_id")
        references = set(line.get("definition_refs") or [])
        items = [item for item in items if item.get("id") in references]
    elif unlinked is not None:
        items = [
            item for item in items if (item.get("id") not in linked_ids) is unlinked
        ]
    return _validated_page(
        [_public_definition(item) for item in items],
        page=page,
        page_size=page_size,
        serializer_class=DefinitionItemPublicSerializer,
    )


def contract_evidence_page(
    contract: BillContract,
    *,
    line_item_id: str | None = None,
    financial_item_id: str | None = None,
    definition_item_id: str | None = None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    from .serializers import EvidenceSpanPublicSerializer

    payload = _contract_json(contract)
    requested = [
        ("line_item_id", "line_items", line_item_id),
        ("financial_item_id", "financial_items", financial_item_id),
        ("definition_item_id", "definitions", definition_item_id),
    ]
    selected = [entry for entry in requested if entry[2] is not None]
    if len(selected) != 1:
        raise serializers.ValidationError(
            {"non_field_errors": ["Provide exactly one supported item ID."]}
        )
    query_field, category, item_id = selected[0]
    item = _item_by_id(_array(payload, category), item_id, query_field=query_field)
    paths = item.get("evidence_paths")
    if (
        not isinstance(paths, list)
        or not paths
        or any(not isinstance(path, str) or not path for path in paths)
    ):
        raise serializers.ValidationError(
            {query_field: ["Stored evidence references are invalid."]}
        )
    rows = contract.evidence_spans.filter(field_path__in=paths).order_by(
        "start_char", "end_char", "id"
    )
    deduplicated = []
    seen = set()
    for row in rows:
        identity = (row.start_char, row.end_char, row.quoted_text)
        if identity in seen:
            continue
        seen.add(identity)
        deduplicated.append(
            {
                "start_char": row.start_char,
                "end_char": row.end_char,
                "quoted_text": row.quoted_text,
                "page_number": row.page_number,
            }
        )
    return _validated_page(
        deduplicated,
        page=page,
        page_size=page_size,
        serializer_class=EvidenceSpanPublicSerializer,
    )


def _summary_paragraphs(summary: str) -> list[str]:
    return [
        " ".join(part.split()) for part in re.split(r"\n+", summary) if part.split()
    ]


def _summary_preview(bill: Bill) -> tuple[str | None, bool]:
    summary = bill.summary or ""
    paragraphs = _summary_paragraphs(summary)
    normalized_title = " ".join((bill.title or "").split()).casefold()
    while paragraphs and paragraphs[0].casefold() == normalized_title:
        paragraphs.pop(0)
    if not paragraphs:
        return None, bool(summary.strip())
    paragraph = paragraphs[0]
    if len(paragraph) <= SUMMARY_PREVIEW_LIMIT:
        preview = paragraph
    else:
        boundary = paragraph.rfind(" ", 0, SUMMARY_PREVIEW_LIMIT + 1)
        preview = paragraph[
            : boundary if boundary > 0 else SUMMARY_PREVIEW_LIMIT
        ].rstrip()
    complete_normalized = "\n".join(_summary_paragraphs(summary))
    return preview, preview != complete_normalized


def official_summary_projection(bill: Bill, *, full: bool) -> dict[str, Any]:
    provenance = {
        "summary_source": bill.summary_source,
        "summary_action_date": bill.summary_action_date,
        "summary_version_code": bill.summary_version_code,
        "summary_last_updated_at": bill.summary_last_updated_at,
    }
    if full:
        return {"summary": bill.summary, **provenance}
    preview, has_more = _summary_preview(bill)
    return {
        "summary_preview": preview,
        "summary_has_more": has_more,
        **provenance,
    }
