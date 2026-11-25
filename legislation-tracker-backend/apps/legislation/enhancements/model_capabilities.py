"""Model limits used by planning, with their origin kept explicit."""

import json
from dataclasses import asdict, dataclass
from hashlib import sha256

from django.conf import settings


@dataclass(frozen=True)
class ModelCapabilities:
    provider: str
    model: str
    context_tokens: int
    output_tokens: int
    visible_fraction: float
    provenance: str
    tokenizer: str | None
    fetched_at: str | None
    parameters: tuple[str, ...]
    pricing: dict | None

    @property
    def fingerprint(self):
        values = asdict(self)
        values.pop("fetched_at")
        return sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def resolve_capabilities(provider, model):
    entry = settings.LLM_READER_MODEL_CAPACITIES.get(f"{provider}/{model}", {})
    if provider == "openrouter" and model != "openrouter/free":
        from .openrouter_catalog import entries

        entry = {**entry, **entries().get(model, {})}
    output = min(
        settings.LLM_READER_MAX_OUTPUT_TOKENS,
        int(entry.get("output_tokens", settings.LLM_READER_MAX_OUTPUT_TOKENS)),
    )
    context = int(
        entry.get(
            "context_tokens",
            settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS + output + 1024,
        )
    )
    return ModelCapabilities(
        provider,
        model,
        context,
        output,
        min(0.9, max(0.1, float(entry.get("visible_fraction", 0.5)))),
        entry.get("provenance", "configured" if entry else "application estimate"),
        entry.get("tokenizer"),
        entry.get("fetched_at"),
        tuple(sorted(entry.get("parameters", ()))),
        entry.get("pricing"),
    )
