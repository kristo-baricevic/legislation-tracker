from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from apps.legislation.enhancements.types import EnhancementPreflight


@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None
    visible_output_tokens: int | None = None


@dataclass(frozen=True)
class ProviderResult:
    output: dict[str, Any]
    usage: ProviderUsage
    response_id: str
    resolved_model: str
    citation_resolution: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CredentialCheck:
    valid: bool
    category: str | None = None


@dataclass(frozen=True)
class ProviderCapabilities:
    wire_api: str
    schema_profile: str
    reasoning_mapping: dict[str, Any] = field(default_factory=dict)
    privacy_flags: dict[str, Any] = field(default_factory=dict)
    validation_profile: str = ""
    usage_shape: str = ""
    refusal_completion_profile: str = ""
    error_profile: str = ""
    unsupported_schema_keywords: frozenset[str] = field(default_factory=frozenset)


class ProviderError(RuntimeError):
    def __init__(
        self,
        category: str,
        *,
        outcome_unknown: bool = False,
        retry_allowed: bool = False,
        usage: ProviderUsage | None = None,
        response_id: str = "",
        resolved_model: str = "",
        validation_code: str = "",
        validation_detail: dict | None = None,
    ):
        super().__init__(f"Provider request failed: {category}")
        self.category = category
        self.outcome_unknown = outcome_unknown
        self.retry_allowed = retry_allowed
        self.usage = usage or ProviderUsage()
        self.response_id = response_id
        self.resolved_model = resolved_model
        self.validation_code = validation_code
        self.validation_detail = validation_detail or {}
        self.citation_resolution = {}


class EnhancementProvider(Protocol):
    provider_name: str
    capabilities: ProviderCapabilities

    def generate_provisions(
        self, *, api_key: str, request, timeout_seconds: int
    ) -> ProviderResult: ...

    def repair_provisions(
        self, *, api_key: str, request, timeout_seconds: int
    ) -> ProviderResult: ...

    def generate_synopsis(
        self, *, api_key: str, request, timeout_seconds: int
    ) -> ProviderResult: ...

    def validate_credential(
        self,
        *,
        api_key: str,
        requested_model: str,
        timeout_seconds: int,
    ) -> CredentialCheck: ...

    def enhance_bill(
        self,
        *,
        api_key: str,
        request: EnhancementPreflight,
        timeout_seconds: int,
    ) -> ProviderResult: ...
