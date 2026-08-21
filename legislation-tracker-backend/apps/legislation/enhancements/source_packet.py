from __future__ import annotations

import hashlib
import json
import math
from collections import OrderedDict, deque
from typing import Any

from django.conf import settings

from apps.legislation.models import BillDocument

from .prompts import DEVELOPER_INSTRUCTIONS, PROMPT_VERSION, SOURCE_PACKET_VERSION
from .schema import OUTPUT_SCHEMA, OUTPUT_SCHEMA_VERSION
from .types import EnhancementPreflight

MAX_SOURCE_TEXT_LENGTH = 4_000


class PreflightUnavailable(ValueError):
    def __init__(self, message: str, *, reason: str = "source_unavailable"):
        super().__init__(message)
        self.reason = reason


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def estimate_input_tokens(request_bytes: bytes) -> int:
    return math.ceil(len(request_bytes) / 2)


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _field_category(field_path: str) -> str:
    return field_path.split("[", 1)[0].split(".", 1)[0]


def _contract_value(contract_json: dict[str, Any], field_path: str) -> Any:
    current: Any = contract_json
    for raw_segment in field_path.split("."):
        if "[" in raw_segment and raw_segment.endswith("]"):
            key, raw_index = raw_segment[:-1].split("[", 1)
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
            if not isinstance(current, list):
                return None
            try:
                current = current[int(raw_index)]
            except (IndexError, ValueError):
                return None
        else:
            if not isinstance(current, dict) or raw_segment not in current:
                return None
            current = current[raw_segment]
    return current


def _evidence_candidates(
    bill, *, active_document: BillDocument | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    contract = bill.latest_contract
    if contract is None or (
        active_document is not None and contract.document_id != active_document.id
    ):
        return [], {}
    spans = list(
        contract.evidence_spans.select_related("document").order_by(
            "start_char",
            "end_char",
            "id",
        )
    )
    unique: list[Any] = []
    seen: set[tuple[int, int, str]] = set()
    for span in spans:
        quote = span.quoted_text or ""
        identity = (span.start_char, span.end_char, quote)
        document_text = ""
        if span.document_id:
            document_text = span.document.extracted_text or span.document.raw_text or ""
        exact_source_match = (
            span.end_char > span.start_char
            and span.end_char <= len(document_text)
            and document_text[span.start_char : span.end_char] == quote
        )
        if (
            not quote.strip()
            or len(quote) > MAX_SOURCE_TEXT_LENGTH
            or identity in seen
            or not exact_source_match
        ):
            continue
        seen.add(identity)
        unique.append(span)

    groups: OrderedDict[str, deque[Any]] = OrderedDict()
    for span in unique:
        groups.setdefault(_field_category(span.field_path), deque()).append(span)

    balanced: list[Any] = []
    while groups:
        empty = []
        for category, spans_for_category in groups.items():
            balanced.append(spans_for_category.popleft())
            if not spans_for_category:
                empty.append(category)
        for category in empty:
            groups.pop(category)

    candidates = []
    contract_json = (
        contract.contract_json if isinstance(contract.contract_json, dict) else {}
    )
    for span in balanced:
        candidates.append(
            {
                "kind": "contract_evidence",
                "field_path": span.field_path,
                "section_label": (
                    span.document.version_label if span.document_id else None
                ),
                "quoted_text": span.quoted_text,
                "start_char": span.start_char,
                "end_char": span.end_char,
                "text_sha256": _text_hash(span.quoted_text),
                "contract_value": _contract_value(contract_json, span.field_path),
            }
        )
    return candidates, {
        "contract_id": contract.id,
        "contract_hash": contract.contract_hash,
        "contract_schema_version": contract.schema_version,
        "document_id": contract.document_id,
    }


def _marked_active_document(bill) -> BillDocument | None:
    return (
        bill.documents.filter(is_active_version=True)
        .order_by("-created_at", "-id")
        .first()
    )


def _stored_document(bill) -> BillDocument | None:
    return (
        bill.documents.exclude(extracted_text__isnull=True)
        .exclude(extracted_text="")
        .order_by("-created_at", "-id")
        .first()
        or bill.documents.exclude(raw_text__isnull=True)
        .exclude(raw_text="")
        .order_by("-created_at", "-id")
        .first()
    )


def _document_candidates(
    bill, *, active_document: BillDocument | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    document = active_document or _stored_document(bill)
    if document is None:
        return [], {}
    text = document.extracted_text or document.raw_text or ""
    if not text.strip():
        return [], {}
    candidates = []
    start = 0
    while start < len(text):
        hard_end = min(start + MAX_SOURCE_TEXT_LENGTH, len(text))
        end = hard_end
        if hard_end < len(text):
            boundary = max(
                text.rfind("\n", start, hard_end), text.rfind(". ", start, hard_end)
            )
            if boundary > start + (MAX_SOURCE_TEXT_LENGTH // 2):
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            actual_start = text.find(chunk, start, end)
            candidates.append(
                {
                    "kind": "document_chunk",
                    "field_path": None,
                    "section_label": document.version_label,
                    "quoted_text": chunk,
                    "start_char": actual_start,
                    "end_char": actual_start + len(chunk),
                    "text_sha256": _text_hash(chunk),
                    "contract_value": None,
                }
            )
        start = max(end, start + 1)
    return candidates, {
        "document_id": document.id,
        "document_content_hash": document.content_hash,
        "document_version_label": document.version_label,
    }


def _numbered_sources(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"source_ref": f"src_{index:04d}", **candidate}
        for index, candidate in enumerate(candidates, start=1)
    ]


def _snapshot(source: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in source.items() if key != "contract_value"}


def _request_envelope(
    bill, sources: list[dict[str, Any]], *, truncated: bool
) -> dict[str, Any]:
    return {
        "provider": settings.LLM_ENHANCEMENT_PROVIDER,
        "requested_model": settings.LLM_ENHANCEMENT_MODEL,
        "reasoning_effort": settings.LLM_ENHANCEMENT_REASONING_EFFORT,
        "prompt_version": PROMPT_VERSION,
        "output_schema_version": OUTPUT_SCHEMA_VERSION,
        "source_packet_version": SOURCE_PACKET_VERSION,
        "max_output_tokens": settings.LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS,
        "instructions": DEVELOPER_INSTRUCTIONS,
        "bill": {
            "id": bill.id,
            "jurisdiction": bill.jurisdiction,
            "session": bill.session,
            "bill_number": bill.bill_number,
            "title": bill.title,
            "status": bill.status,
            "introduced_at": (
                bill.introduced_at.isoformat() if bill.introduced_at else None
            ),
        },
        "source_packet": {
            "truncated": truncated,
            "sources": sources,
        },
        "output_schema": OUTPUT_SCHEMA,
    }


def _within_limits(request_bytes: bytes) -> bool:
    return (
        len(request_bytes) <= settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES
        and estimate_input_tokens(request_bytes)
        <= settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS
    )


def build_enhancement_preflight(bill) -> EnhancementPreflight:
    if str(bill.jurisdiction or "").strip().lower() != "federal":
        raise PreflightUnavailable(
            "LLM enhancements are currently available only for federal bills",
            reason="unsupported_jurisdiction",
        )

    active_document = _marked_active_document(bill)
    candidates, source_identity = _evidence_candidates(
        bill,
        active_document=active_document,
    )
    source_kind = "contract_evidence"
    if not candidates:
        candidates, source_identity = _document_candidates(
            bill,
            active_document=active_document,
        )
        source_kind = "document_chunk"
    if not candidates:
        raise PreflightUnavailable("No stored source text is available for this bill")

    fixed_envelope = _request_envelope(bill, [], truncated=True)
    if not _within_limits(canonical_json_bytes(fixed_envelope)):
        raise PreflightUnavailable(
            "The fixed request overhead exceeds configured limits",
            reason="request_too_large",
        )

    numbered = None
    request_envelope = None
    request_bytes = None
    selected_count = 0
    low = 1
    high = len(candidates)
    while low <= high:
        candidate_count = (low + high) // 2
        candidate_sources = _numbered_sources(candidates[:candidate_count])
        candidate_truncated = candidate_count < len(candidates)
        candidate_envelope = _request_envelope(
            bill,
            candidate_sources,
            truncated=candidate_truncated,
        )
        candidate_bytes = canonical_json_bytes(candidate_envelope)
        if _within_limits(candidate_bytes):
            numbered = candidate_sources
            request_envelope = candidate_envelope
            request_bytes = candidate_bytes
            selected_count = candidate_count
            low = candidate_count + 1
        else:
            high = candidate_count - 1

    if numbered is None or request_envelope is None or request_bytes is None:
        raise PreflightUnavailable(
            "No source packet can fit the configured request limits",
            reason="request_too_large",
        )
    truncated = selected_count < len(candidates)

    source_snapshot = [_snapshot(source) for source in numbered]
    source_fingerprint = hashlib.sha256(
        canonical_json_bytes(
            {
                "source_packet_version": SOURCE_PACKET_VERSION,
                "source_identity": source_identity,
                "sources": source_snapshot,
            }
        )
    ).hexdigest()
    request_fingerprint = hashlib.sha256(request_bytes).hexdigest()
    manifest = {
        **source_identity,
        "source_kind": source_kind,
        "total_candidates": len(candidates),
        "selected_count": selected_count,
        "truncated": truncated,
    }
    return EnhancementPreflight(
        provider=settings.LLM_ENHANCEMENT_PROVIDER,
        requested_model=settings.LLM_ENHANCEMENT_MODEL,
        reasoning_effort=settings.LLM_ENHANCEMENT_REASONING_EFFORT,
        prompt_version=PROMPT_VERSION,
        output_schema_version=OUTPUT_SCHEMA_VERSION,
        source_packet_version=SOURCE_PACKET_VERSION,
        source_fingerprint=source_fingerprint,
        request_fingerprint=request_fingerprint,
        source_manifest=manifest,
        source_snapshot=source_snapshot,
        request_envelope=request_envelope,
        request_bytes=request_bytes,
        estimated_input_tokens=estimate_input_tokens(request_bytes),
        truncated=truncated,
    )
