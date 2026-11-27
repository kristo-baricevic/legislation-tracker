from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import cached_property
from typing import Any


@dataclass(frozen=True)
class Passage:
    id: str
    start: int
    end: int
    text: str
    text_sha256: str
    role: str
    structural_path: tuple[str, ...]


@dataclass(frozen=True)
class SourceUnit:
    id: str
    own_passage_ids: tuple[str, ...]
    context_passage_ids: tuple[str, ...] = ()
    parent_id: str | None = None
    condition_group_id: str | None = None
    inventory_kinds: tuple[str, ...] = ()
    unresolved_dependencies: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceGraph:
    document_fingerprint: str
    passages: dict[str, Passage]
    units: tuple[SourceUnit, ...]
    coverage: dict[str, Any]
    source_text: str
    document_id: str
    version: str
    xml_sections: tuple = ()


@dataclass(frozen=True)
class EnhancementPreflight:
    provider: str
    requested_model: str
    reasoning_effort: str
    prompt_version: str
    output_schema_version: str
    source_packet_version: str
    source_fingerprint: str
    request_fingerprint: str
    source_manifest: dict[str, Any]
    source_snapshot: list[dict[str, Any]]
    request_envelope: dict[str, Any]
    request_bytes: bytes
    estimated_input_tokens: int
    truncated: bool
    analysis_plan: Any = None
    glossary_batches: tuple = ()
    reader_batches: tuple = ()
    reader_reuse: Any = None
    worker_guard: str | None = None
    prior_reader_items: dict[str, dict[str, Any]] | None = None
    legacy_dependency_request: Callable[[], EnhancementPreflight] | None = None
    historical_page_sources: Callable[[str], Iterable[list[dict[str, Any]]]] | None = (
        None
    )

    @cached_property
    def historical_reader_sources(self):
        from .reader_legacy_context import HistoricalReaderSources

        return HistoricalReaderSources(self)
