from __future__ import annotations

from dataclasses import dataclass
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
