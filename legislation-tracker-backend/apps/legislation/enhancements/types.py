from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
