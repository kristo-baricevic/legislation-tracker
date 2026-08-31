"""Bounded, identity-aware comparisons for persisted bill versions."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from .extraction.federal_structure import parse_federal_structure
from .extraction.types import ExpectedExtractionRejection

Operation = Literal["added", "removed", "changed"]

CONTRACT_ITEM_IDENTITIES = {
    "key_provisions": ("section_label", "kind", "heading"),
    "requirements": ("section_label", "modality", "actor", "action", "object"),
    "funding_items": ("section_label", "amount_type", "currency", "purpose"),
    "timeline_items": ("section_label", "timeline_type", "trigger"),
    "definitions": ("section_label", "term"),
    "applicability": ("section_label", "subject", "applicability_type"),
    "amendment_operations": ("section_label", "target", "operation"),
}


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


def _identity(item: dict, fields: tuple[str, ...]) -> str:
    return "|".join(_normalize_identity(item.get(field)) for field in fields)


def _bounded(value: object, *, max_chars: int = 10_000):
    rendered = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    if len(rendered) <= max_chars:
        return value
    return {"truncated": True, "preview": rendered[:max_chars]}


def _compare_values(before: object, after: object, path: str, changes: list[ContractChange]):
    if before == after:
        return
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            child_path = f"{path}.{key}" if path else key
            if key not in before:
                changes.append(ContractChange(child_path, "added", None, _bounded(after[key])))
            elif key not in after:
                changes.append(ContractChange(child_path, "removed", _bounded(before[key]), None))
            else:
                _compare_values(before[key], after[key], child_path, changes)
        return
    if isinstance(before, list) and isinstance(after, list):
        root = path.split(".", 1)[0]
        identity_fields = CONTRACT_ITEM_IDENTITIES.get(root)
        if identity_fields and all(isinstance(item, dict) for item in before + after):
            before_items: dict[str, list[dict]] = {}
            after_items: dict[str, list[dict]] = {}
            for item in before:
                before_items.setdefault(_identity(item, identity_fields), []).append(item)
            for item in after:
                after_items.setdefault(_identity(item, identity_fields), []).append(item)
            for identity in sorted(set(before_items) | set(after_items)):
                old_group = list(before_items.get(identity, ()))
                new_group = list(after_items.get(identity, ()))
                duplicate_identity = max(len(old_group), len(new_group)) > 1

                def item_path(
                    index: int,
                    *,
                    is_duplicate: bool = duplicate_identity,
                    item_identity: str = identity,
                ) -> str:
                    suffix = f"#{index}" if is_duplicate else ""
                    return f"{path}[{item_identity}{suffix}]"

                # Consume exact matches first so a duplicate removal cannot be
                # misreported as a mutation of the surviving row.
                unmatched_new = list(new_group)
                unmatched_old = []
                for old_item in old_group:
                    try:
                        match_index = unmatched_new.index(old_item)
                    except ValueError:
                        unmatched_old.append(old_item)
                    else:
                        unmatched_new.pop(match_index)
                paired = min(len(unmatched_old), len(unmatched_new))
                for index in range(paired):
                    _compare_values(
                        unmatched_old[index],
                        unmatched_new[index],
                        item_path(index + 1),
                        changes,
                    )
                for index, item in enumerate(unmatched_old[paired:], start=paired + 1):
                    changes.append(
                        ContractChange(
                            item_path(index),
                            "removed",
                            _bounded(item),
                            None,
                        )
                    )
                for index, item in enumerate(unmatched_new[paired:], start=paired + 1):
                    changes.append(
                        ContractChange(
                            item_path(index),
                            "added",
                            None,
                            _bounded(item),
                        )
                    )
            return
        if sorted(map(repr, before)) == sorted(map(repr, after)):
            return
    changes.append(ContractChange(path, "changed", _bounded(before), _bounded(after)))


def compare_contracts(*, before, after, limit: int = 200) -> ContractDiff:
    if before.bill_id != after.bill_id:
        raise ValueError("Contracts must belong to the same bill.")
    if limit < 1:
        raise ValueError("limit must be positive")
    changes: list[ContractChange] = []
    _compare_values(before.contract_json or {}, after.contract_json or {}, "", changes)
    changes.sort(key=lambda item: (item.path, item.operation))
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
        for section in sections:
            base = _normalize_identity(section.label)
            occurrences[base] = occurrences.get(base, 0) + 1
            key = f"{base}#{occurrences[base]}"
            result[key] = section.span.text
    else:
        for index, paragraph in enumerate(re.split(r"\n\s*\n+", source), start=1):
            if paragraph.strip():
                result[f"paragraph-{index}"] = paragraph.strip()
    return result, fallback, source_truncated


def _content_hash(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").rstrip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compare_document_sections(*, before, after, limit: int = 500) -> DocumentSectionDiff:
    if before.bill_id != after.bill_id:
        raise ValueError("Documents must belong to the same bill.")
    before_sections, before_fallback, before_source_truncated = _section_map(before)
    after_sections, after_fallback, after_source_truncated = _section_map(after)
    changes = []
    for key in sorted(set(before_sections) | set(after_sections)):
        old = before_sections.get(key)
        new = after_sections.get(key)
        if old is None:
            changes.append(DocumentSectionChange(key, "added", None, _content_hash(new)))
        elif new is None:
            changes.append(DocumentSectionChange(key, "removed", _content_hash(old), None))
        elif _content_hash(old) != _content_hash(new):
            changes.append(DocumentSectionChange(key, "modified", _content_hash(old), _content_hash(new)))
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
                ("source_text_limit", before_source_truncated or after_source_truncated),
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
                ("source_text_limit", before_source_truncated or after_source_truncated),
                ("line_limit", line_limit_reached),
                ("operation_limit", operation_limit_reached),
            )
            if applies
        ),
    )
