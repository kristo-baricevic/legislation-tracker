"""Public, cached model metadata. Fetching the catalog makes no generation request."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import requests
from django.core.cache import cache

CATALOG_KEY = "enhancement:openrouter:catalog:v1"
CATALOG_URL = "https://openrouter.ai/api/v1/models"


def zero_price(prices):
    try:
        return isinstance(prices, dict) and {"prompt", "completion"}.issubset(prices) and all(Decimal(str(v)) == 0 for v in prices.values())
    except (InvalidOperation, TypeError):
        return False


def refresh_catalog():
    response = requests.get(CATALOG_URL, timeout=10)
    response.raise_for_status()
    now = datetime.now(timezone.utc).isoformat()
    entries = {}
    for row in response.json()["data"]:
        model = row["id"]
        free = zero_price(row.get("pricing") or {})
        parameters = row.get("supported_parameters") or []
        limits = row.get("top_provider") or {}
        if (
            model.endswith(":free") and free and {"structured_outputs", "max_tokens", "reasoning"}.issubset(parameters)
            and all(type(limits.get(k)) is int and limits[k] > 0 for k in ("max_completion_tokens", "context_length"))
        ):
            entries[model] = {"provider": "openrouter", "model": model, "free": free,
                              "pricing": row.get("pricing"), "fetched_at": now, "provenance": CATALOG_URL,
                              "context_tokens": limits.get("context_length"),
                              "output_tokens": limits.get("max_completion_tokens"),
                              "parameters": parameters, "tokenizer": (row.get("architecture") or {}).get("tokenizer")}
    cache.set(CATALOG_KEY, entries, 24 * 60 * 60)
    return entries


_scope = ContextVar("openrouter_catalog_scope", default=None)


@contextmanager
def catalog_scope():
    token = _scope.set({})
    try:
        yield
    finally:
        _scope.reset(token)


def entries():
    scope = _scope.get()
    if scope is None:
        return cache.get(CATALOG_KEY) or {}
    if "entries" not in scope:
        scope["entries"] = cache.get(CATALOG_KEY) or {}
    return scope["entries"]
