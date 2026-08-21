from __future__ import annotations

from django.conf import settings

from .providers.openai import OpenAIEnhancementProvider

_PROVIDERS = {"openai": OpenAIEnhancementProvider}


def _provider_class(name: str):
    normalized = (name or "").strip().lower()
    if normalized == "e2e" and getattr(
        settings,
        "LLM_ENHANCEMENT_E2E_FAKE_PROVIDER_ENABLED",
        False,
    ):
        from .providers.e2e import E2EEnhancementProvider

        return E2EEnhancementProvider
    return _PROVIDERS.get(normalized)


def provider_is_registered(name: str) -> bool:
    return _provider_class(name) is not None


def get_provider(name: str):
    provider_class = _provider_class(name)
    if provider_class is None:
        raise ValueError("Configured LLM enhancement provider is unavailable")
    return provider_class()
