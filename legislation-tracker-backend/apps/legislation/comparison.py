"""Bounded, identity-aware comparisons for persisted bill versions."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from .extraction.federal_structure import parse_federal_structure
from .extraction.types import ExpectedExtractionRejection

Operation = Literal["added", "removed", "changed"]

MIN_DIFF_CORRESPONDENCE_RATIO = 0.72


@dataclass(frozen=True)
class ContractChange:
    path: str
    operation: Operation
    before: object | None
    after: object | None


@dataclass(frozen=True)
class ContractDiff:
    changes: tuple[ContractChange, ...]
    total_change_count: int
    returned_change_count: int
    truncated: bool


@dataclass(frozen=True)
class SemanticItem:
    category: str
    structural_path: tuple[str, ...]
    anchor: tuple[str, ...]
    mutable_fields: dict[str, object]
    source_order: int


@dataclass(frozen=True)
class DocumentSectionChange:
    section_key: str
    operation: Literal["added", "removed", "modified"]
    before_hash: str | None
    after_hash: str | None


@dataclass(frozen=True)
class DocumentSectionDiff:
    sections: tuple[DocumentSectionChange, ...]
    total_change_count: int
    returned_change_count: int
    truncated: bool
    fallback: bool
    truncation_reasons: tuple[str, ...]


@dataclass(frozen=True)
class DocumentLineDiff:
    section_key: str
    operations: tuple[dict, ...]
    truncated: bool
    truncation_reasons: tuple[str, ...]


def _normalize_identity(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _bounded(value: object, *, max_chars: int = 10_000):
    rendered = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    if len(rendered) <= max_chars:
        return value
    return {"truncated": True, "preview": rendered[:max_chars]}


def _normalized_value(value: object) -> object:
    if isinstance(value, str):
        return _normalize_identity(value)
    if isinstance(value, list):
        return tuple(_normalized_value(item) for item in value)
    if isinstance(value, dict):
        return tuple(
            (str(key), _normalized_value(item)) for key, item in sorted(value.items())
        )
    return value


def _structural_path(item: dict[str, object]) -> tuple[str, ...]:
    raw_path = item.get("section_path")
    if isinstance(raw_path, list):
        path = tuple(
            _normalize_identity(part.get("label"))
            for part in raw_path
            if isinstance(part, dict) and part.get("label")
        )
        if path:
            return path
    label = _normalize_identity(item.get("section_label"))
    return (label,) if label else ()


_SEMANTIC_CATEGORIES = {
    "requirements": "requirements",
    "funding_items": "financial_items",
    "financial_items": "financial_items",
    "timeline_items": "timeline_items",
    "definitions": "definitions",
    "applicability": "applicability",
    "amendment_operations": "amendment_operations",
}

_SEMANTIC_FIELDS = {
    "requirements": (
        "modality",
        "actor",
        "action",
        "object",
        "conditions",
    ),
    "financial_items": (
        "financial_action",
        "direction",
        "amount",
        "amount_type",
        "currency",
        "fiscal_years",
        "purpose",
        "source_account",
        "destination_account",
    ),
    "timeline_items": (
        "timeline_type",
        "date",
        "relative_value",
        "relative_unit",
        "trigger",
    ),
    "definitions": ("term", "definition", "definition_type"),
    "applicability": ("subject", "scope", "applicability_type"),
    "amendment_operations": (
        "target",
        "operation",
        "removed_text",
        "inserted_text",
    ),
}


def _anchor(category: str, fields: dict[str, object]) -> tuple[str, ...]:
    anchor_fields = {
        "requirements": ("modality", "actor"),
        "financial_items": ("purpose", "source_account", "destination_account"),
        "timeline_items": ("timeline_type", "trigger"),
        "definitions": ("term",),
        "applicability": ("subject", "applicability_type"),
        "amendment_operations": ("target", "operation"),
    }[category]
    return tuple(_normalize_identity(fields.get(field)) for field in anchor_fields)


def semantic_contract_items(
    contract_json: dict[str, object],
) -> dict[str, tuple[SemanticItem, ...]]:
    """Project a contract into statutory claims with no source-local identity.

    Offset-derived IDs, evidence paths, extraction metadata, line-item reader
    projections, and generated display text are deliberately absent.
    """
    projected: dict[str, list[SemanticItem]] = defaultdict(list)
    source_order = 0
    for raw_category, category in _SEMANTIC_CATEGORIES.items():
        raw_items = contract_json.get(raw_category, [])
        if not isinstance(raw_items, list):
            continue
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            fields = {
                field: _normalized_value(raw_item[field])
                for field in _SEMANTIC_FIELDS[category]
                if field in raw_item
            }
            if not fields:
                continue
            projected[category].append(
                SemanticItem(
                    category=category,
                    structural_path=_structural_path(raw_item),
                    anchor=_anchor(category, raw_item),
                    mutable_fields=fields,
                    source_order=source_order,
                )
            )
            source_order += 1
    return {category: tuple(items) for category, items in sorted(projected.items())}


def _common_fields_equal(before: SemanticItem, after: SemanticItem) -> bool:
    common = set(before.mutable_fields) & set(after.mutable_fields)
    return all(
        before.mutable_fields[key] == after.mutable_fields[key] for key in common
    )


def _correspondence_text(item: SemanticItem, *, common_fields: set[str]) -> str:
    payload = {key: item.mutable_fields[key] for key in sorted(common_fields)}
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)


def _changed_field_text(
    before: SemanticItem, after: SemanticItem, *, common_fields: set[str]
) -> tuple[str, str]:
    changed = {
        key
        for key in common_fields
        if before.mutable_fields[key] != after.mutable_fields[key]
    }
    return (
        _correspondence_text(before, common_fields=changed),
        _correspondence_text(after, common_fields=changed),
    )


def _item_payload(item: SemanticItem) -> dict[str, object]:
    return {
        "category": item.category,
        "structural_path": item.structural_path,
        **item.mutable_fields,
    }


def _semantic_changes(
    before_json: dict[str, object], after_json: dict[str, object]
) -> list[ContractChange]:
    before_items = semantic_contract_items(before_json)
    after_items = semantic_contract_items(after_json)
    changes: list[ContractChange] = []
    for category in sorted(set(before_items) | set(after_items)):
        buckets: dict[
            tuple[tuple[str, ...], tuple[str, ...]],
            tuple[list[SemanticItem], list[SemanticItem]],
        ] = {}
        for item in before_items.get(category, ()):
            buckets.setdefault((item.structural_path, item.anchor), ([], []))[0].append(
                item
            )
        for item in after_items.get(category, ()):
            buckets.setdefault((item.structural_path, item.anchor), ([], []))[1].append(
                item
            )
        ordinal = 0
        for bucket in sorted(buckets):
            old_group, new_group = buckets[bucket]
            unmatched_old = list(old_group)
            unmatched_new = list(new_group)
            for old_item in list(unmatched_old):
                exact_index = next(
                    (
                        index
                        for index, new_item in enumerate(unmatched_new)
                        if _common_fields_equal(old_item, new_item)
                    ),
                    None,
                )
                if exact_index is not None:
                    unmatched_old.remove(old_item)
                    unmatched_new.pop(exact_index)

            candidates = []
            for old_index, old_item in enumerate(unmatched_old):
                for new_index, new_item in enumerate(unmatched_new):
                    common = set(old_item.mutable_fields) & set(new_item.mutable_fields)
                    old_text, new_text = _changed_field_text(
                        old_item, new_item, common_fields=common
                    )
                    ratio = SequenceMatcher(
                        None,
                        old_text,
                        new_text,
                        autojunk=False,
                    ).ratio()
                    if ratio >= MIN_DIFF_CORRESPONDENCE_RATIO:
                        candidates.append(
                            (
                                -ratio,
                                old_item.source_order,
                                new_item.source_order,
                                old_index,
                                new_index,
                            )
                        )
            paired_old = set()
            paired_new = set()
            for _score, _old_order, _new_order, old_index, new_index in sorted(
                candidates
            ):
                if old_index in paired_old or new_index in paired_new:
                    continue
                paired_old.add(old_index)
                paired_new.add(new_index)
                old_item = unmatched_old[old_index]
                new_item = unmatched_new[new_index]
                ordinal += 1
                common = sorted(
                    set(old_item.mutable_fields) & set(new_item.mutable_fields)
                )
                old_payload = {key: old_item.mutable_fields[key] for key in common}
                new_payload = {key: new_item.mutable_fields[key] for key in common}
                if old_payload != new_payload:
                    changes.append(
                        ContractChange(
                            f"{category}[{ordinal}]",
                            "changed",
                            _bounded(old_payload),
                            _bounded(new_payload),
                        )
                    )
            for index, item in enumerate(unmatched_old):
                if index not in paired_old:
                    ordinal += 1
                    changes.append(
                        ContractChange(
                            f"{category}[{ordinal}]",
                            "removed",
                            _bounded(_item_payload(item)),
                            None,
                        )
                    )
            for index, item in enumerate(unmatched_new):
                if index not in paired_new:
                    ordinal += 1
                    changes.append(
                        ContractChange(
                            f"{category}[{ordinal}]",
                            "added",
                            None,
                            _bounded(_item_payload(item)),
                        )
                    )
    return changes


def _legacy_plain_summary_changes(
    before_json: dict[str, object], after_json: dict[str, object]
) -> list[ContractChange]:
    """Preserve the existing pre-semantic plain-summary comparison only."""
    if "plain_summary" not in before_json and "plain_summary" not in after_json:
        return []
    before = before_json.get("plain_summary")
    after = after_json.get("plain_summary")
    if before == after:
        return []
    if "plain_summary" not in before_json:
        return [ContractChange("plain_summary", "added", None, _bounded(after))]
    if "plain_summary" not in after_json:
        return [ContractChange("plain_summary", "removed", _bounded(before), None)]
    return [
        ContractChange(
            "plain_summary",
            "changed",
            _bounded(before),
            _bounded(after),
        )
    ]


def compare_contracts(*, before, after, limit: int = 200) -> ContractDiff:
    if before.bill_id != after.bill_id:
        raise ValueError("Contracts must belong to the same bill.")
    if limit < 1:
        raise ValueError("limit must be positive")
    before_json = before.contract_json or {}
    after_json = after.contract_json or {}
    if semantic_contract_items(before_json) or semantic_contract_items(after_json):
        changes = _semantic_changes(before_json, after_json)
    else:
        changes = _legacy_plain_summary_changes(before_json, after_json)
    return ContractDiff(
        changes=tuple(changes[:limit]),
        total_change_count=len(changes),
        returned_change_count=min(len(changes), limit),
        truncated=len(changes) > limit,
    )


def _section_map(document):
    complete_source = document.extracted_text or document.raw_text or ""
    source_truncated = len(complete_source) > 50_000
    source = complete_source[:50_000]
    if not source:
        raise ValueError("Document text is unavailable.")
    try:
        sections = parse_federal_structure(source)
        fallback = False
    except ExpectedExtractionRejection:
        sections = ()
        fallback = True
    result = {}
    if sections:
        occurrences: dict[str, int] = {}
        ancestry: list[tuple[int, str]] = []
        for section in sections:
            while ancestry and ancestry[-1][0] <= section.span.start_char:
                ancestry.pop()
            label = _normalize_identity(section.label)
            base = "/".join([*(key for _end, key in ancestry), label])
            occurrences[base] = occurrences.get(base, 0) + 1
            key = f"{base}#{occurrences[base]}"
            result[key] = section.span.text
            ancestry.append((section.span.end_char, key))
    else:
        for index, paragraph in enumerate(re.split(r"\n\s*\n+", source), start=1):
            if paragraph.strip():
                result[f"paragraph-{index}"] = paragraph.strip()
    return result, fallback, source_truncated


def _content_hash(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").rstrip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compare_document_sections(
    *, before, after, limit: int = 500
) -> DocumentSectionDiff:
    if before.bill_id != after.bill_id:
        raise ValueError("Documents must belong to the same bill.")
    before_sections, before_fallback, before_source_truncated = _section_map(before)
    after_sections, after_fallback, after_source_truncated = _section_map(after)
    changes = []
    for key in sorted(set(before_sections) | set(after_sections)):
        old = before_sections.get(key)
        new = after_sections.get(key)
        if old is None:
            changes.append(
                DocumentSectionChange(key, "added", None, _content_hash(new))
            )
        elif new is None:
            changes.append(
                DocumentSectionChange(key, "removed", _content_hash(old), None)
            )
        elif _content_hash(old) != _content_hash(new):
            changes.append(
                DocumentSectionChange(
                    key, "modified", _content_hash(old), _content_hash(new)
                )
            )
    return DocumentSectionDiff(
        sections=tuple(changes[:limit]),
        total_change_count=len(changes),
        returned_change_count=min(len(changes), limit),
        truncated=(
            len(changes) > limit or before_source_truncated or after_source_truncated
        ),
        fallback=before_fallback or after_fallback,
        truncation_reasons=tuple(
            reason
            for reason, applies in (
                (
                    "source_text_limit",
                    before_source_truncated or after_source_truncated,
                ),
                ("section_change_limit", len(changes) > limit),
            )
            if applies
        ),
    )


def compare_document_section(*, before, after, section_key: str) -> DocumentLineDiff:
    before_sections, _, before_source_truncated = _section_map(before)
    after_sections, _, after_source_truncated = _section_map(after)
    left = before_sections.get(section_key, "")[:50_000].splitlines()
    right = after_sections.get(section_key, "")[:50_000].splitlines()
    matcher = SequenceMatcher(a=left[:2_000], b=right[:2_000], autojunk=False)
    changed_opcodes = [
        opcode for opcode in matcher.get_opcodes() if opcode[0] != "equal"
    ]
    operations = [
        {
            "operation": tag,
            "before": left[left_start:left_end],
            "after": right[right_start:right_end],
        }
        for tag, left_start, left_end, right_start, right_end in changed_opcodes[:500]
    ]
    operation_limit_reached = len(changed_opcodes) > 500
    line_limit_reached = len(left) > 2_000 or len(right) > 2_000
    return DocumentLineDiff(
        section_key=section_key,
        operations=tuple(operations),
        truncated=(
            operation_limit_reached
            or line_limit_reached
            or before_source_truncated
            or after_source_truncated
        ),
        truncation_reasons=tuple(
            reason
            for reason, applies in (
                (
                    "source_text_limit",
                    before_source_truncated or after_source_truncated,
                ),
                ("line_limit", line_limit_reached),
                ("operation_limit", operation_limit_reached),
            )
            if applies
        ),
    )
