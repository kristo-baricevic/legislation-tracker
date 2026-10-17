from __future__ import annotations

import hashlib
import json
from typing import Any

from django.conf import settings

from apps.legislation.models import BillDocument

from .citations import compact_source_text
from .prompts import DEVELOPER_INSTRUCTIONS, PROMPT_VERSION, SOURCE_PACKET_VERSION
from .schema import OUTPUT_SCHEMA_VERSION, PROVIDER_OUTPUT_SCHEMA
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
    # A BPE token cannot contain less than one byte of the UTF-8 request. This
    # deliberately conservative upper bound remains safe for punctuation,
    # non-BMP text, and model tokenizer changes.
    return len(request_bytes)


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


def _numbered_sources(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"source_ref": f"src_{index:04d}", **candidate}
        for index, candidate in enumerate(candidates, start=1)
    ]


def _snapshot(source: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in source.items() if key != "contract_value"}


def _request_envelope(
    bill, sources: list[dict[str, Any]], *, truncated: bool, coverage=None
) -> dict[str, Any]:
    return {
        "provider": settings.LLM_ENHANCEMENT_PROVIDER,
        "requested_model": settings.LLM_ENHANCEMENT_MODEL,
        "reasoning_effort": settings.LLM_ENHANCEMENT_REASONING_EFFORT,
        "prompt_version": PROMPT_VERSION,
        "output_schema_version": OUTPUT_SCHEMA_VERSION,
        "source_packet_version": SOURCE_PACKET_VERSION,
        "max_output_tokens": settings.LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS,
        "citation_resolution": {"version": 2, "max_repair_calls": 1},
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
            # Snapshots remain verbatim; only provider input is compacted.
            "quote_layout": "whitespace_compacted_offsets_refer_to_original",
            "sources": [
                {**source, "quoted_text": compact_source_text(source["quoted_text"])}
                for source in sources
            ],
            **({"coverage": coverage} if coverage is not None else {}),
        },
        "output_schema": PROVIDER_OUTPUT_SCHEMA,
    }


def _within_limits(request_bytes: bytes) -> bool:
    return (
        len(request_bytes) <= settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES
        and estimate_input_tokens(request_bytes)
        <= settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS
    )


def select_document_sources(bill, text: str, version_label: str):
    """Select complete sections, never a prefix of an operative condition group."""
    from .source_sections import document_groups, section_coverage

    if not text.strip():
        raise PreflightUnavailable("No stored source text is available for this bill")
    if not _within_limits(
        canonical_json_bytes(_request_envelope(bill, [], truncated=True))
    ):
        raise PreflightUnavailable(
            "The fixed request overhead exceeds configured limits",
            reason="request_too_large",
        )
    groups = document_groups(text, version_label)

    def envelope_for(indices):
        selected = set(indices)
        sources = _numbered_sources(
            [
                source
                for index, group in enumerate(groups)
                if index in selected
                for source in group["sources"]
            ]
        )
        coverage = section_coverage(groups, selected, sources)
        envelope = _request_envelope(
            bill, sources, truncated=len(selected) != len(groups), coverage=coverage
        )
        return sources, envelope, canonical_json_bytes(envelope)

    full = envelope_for(range(len(groups)))
    if _within_limits(full[2]):
        return full
    selected = []
    current = envelope_for(selected)
    for index, group in enumerate(groups):
        # Raw bytes are a lower bound; avoid serializing obviously oversized groups.
        raw_size = sum(
            len(compact_source_text(s["quoted_text"]).encode("utf-8"))
            for s in group["sources"]
        )
        limit = min(
            settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES,
            settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS,
        )
        if len(current[2]) + raw_size > limit:
            continue
        candidate = envelope_for([*selected, index])
        if _within_limits(candidate[2]):
            selected.append(index)
            current = candidate
    if not selected:
        raise PreflightUnavailable(
            "No complete source section can fit the configured request limits",
            reason="request_too_large",
        )
    return current


def build_enhancement_preflight(bill, *, reuse_result=None) -> EnhancementPreflight:
    if str(bill.jurisdiction or "").strip().lower() != "federal":
        raise PreflightUnavailable(
            "LLM enhancements are currently available only for federal bills",
            reason="unsupported_jurisdiction",
        )

    active_document = _marked_active_document(bill)
    document = active_document or _stored_document(bill)
    if document is None:
        raise PreflightUnavailable("No stored source text is available for this bill")
    text = document.extracted_text or document.raw_text or ""
    if getattr(settings, "LLM_SOURCE_FIRST_ENABLED", False):
        from .source_first_preflight import build_source_first_preflight
        return build_source_first_preflight(document, text, reuse_result=reuse_result)
    numbered, request_envelope, request_bytes = select_document_sources(
        bill, text, document.version_label
    )
    source_identity = {
        "document_id": document.id,
        "document_content_hash": _text_hash(text),
        "document_version_label": document.version_label,
    }
    coverage = request_envelope["source_packet"]["coverage"]
    truncated = request_envelope["source_packet"]["truncated"]

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
        "source_kind": "document_chunk",
        "total_candidates": coverage["total_chunks"],
        "selected_count": len(numbered),
        "coverage": coverage,
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
