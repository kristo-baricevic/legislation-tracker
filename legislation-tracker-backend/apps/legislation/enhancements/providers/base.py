from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from apps.legislation.enhancements.types import EnhancementPreflight


@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class ProviderResult:
    output: dict[str, Any]
    usage: ProviderUsage
    response_id: str
    resolved_model: str


@dataclass(frozen=True)
class CredentialCheck:
    valid: bool
    category: str | None = None


class ProviderError(RuntimeError):
    def __init__(
        self,
        category: str,
        *,
        outcome_unknown: bool = False,
        retry_allowed: bool = False,
        usage: ProviderUsage | None = None,
    ):
        super().__init__(f"Provider request failed: {category}")
        self.category = category
        self.outcome_unknown = outcome_unknown
        self.retry_allowed = retry_allowed
        self.usage = usage or ProviderUsage()


class EnhancementProvider(Protocol):
    provider_name: str

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
