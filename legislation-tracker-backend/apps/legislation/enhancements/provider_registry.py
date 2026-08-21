from __future__ import annotations

from .providers.openai import OpenAIEnhancementProvider

_PROVIDERS = {"openai": OpenAIEnhancementProvider}


def provider_is_registered(name: str) -> bool:
    return (name or "").strip().lower() in _PROVIDERS


def get_provider(name: str):
    provider_class = _PROVIDERS.get((name or "").strip().lower())
    if provider_class is None:
        raise ValueError("Configured LLM enhancement provider is unavailable")
    return provider_class()
