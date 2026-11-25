from unittest.mock import Mock

from django.core.cache import cache

from apps.legislation.enhancements.model_selection import catalog, selectable
from apps.legislation.enhancements.openrouter_catalog import (
    CATALOG_KEY,
    refresh_catalog,
)


def test_free_choices_require_current_capabilities_and_honor_operator_exclusions(
    settings, monkeypatch
):
    settings.LLM_ENHANCEMENT_PROVIDER = "openrouter"
    settings.LLM_ENHANCEMENT_MODEL = "no-schema:free"
    settings.LLM_OPENROUTER_EXCLUDED_MODELS = ["blocked:free"]
    base = {
        "pricing": {"prompt": "0", "completion": "0"},
        "supported_parameters": ["reasoning", "max_tokens", "structured_outputs"],
        "top_provider": {"context_length": 100000, "max_completion_tokens": 24000},
    }
    rows = [
        {**base, "id": name, **overrides}
        for name, overrides in [
            ("eligible:free", {}),
            ("blocked:free", {}),
            ("openrouter/free", {}),
            ("no-schema:free", {"supported_parameters": ["max_tokens", "reasoning"]}),
            ("unknown-limit:free", {"top_provider": {}}),
            ("unknown-price:free", {"pricing": {}}),
            ("paid:free", {"pricing": {"prompt": "0.01", "completion": "0"}}),
        ]
    ]
    response = Mock()
    response.json.return_value = {"data": rows}
    monkeypatch.setattr(
        "apps.legislation.enhancements.openrouter_catalog.requests.get",
        lambda *a, **k: response,
    )
    try:
        refresh_catalog()
        assert [m["model"] for m in catalog() if m["provider"] == "openrouter"] == [
            "eligible:free"
        ]
        assert not selectable(("openrouter", "no-schema:free"))
        assert not selectable(("openrouter", "blocked:free"))
        cache.delete(CATALOG_KEY)
        assert not selectable(("openrouter", "eligible:free"))
    finally:
        cache.delete(CATALOG_KEY)
