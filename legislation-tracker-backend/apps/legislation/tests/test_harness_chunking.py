from types import SimpleNamespace

import pytest
from django.test import override_settings

from apps.legislation.enhancements.reader_chunking import planned_sources
from apps.legislation.enhancements.model_capabilities import resolve_capabilities
from apps.legislation.enhancements.token_budget import plan_request


@pytest.mark.parametrize("target", [1000, 2000, 4000])
def test_giant_unicode_sentence_is_owned_exactly_once(target):
    source = "SEC. 1. Rule\n" + "🚇" * 4100 + "\nThe fee is $1.25."
    doc = SimpleNamespace(pk=1, version_label="IH")
    parts = planned_sources(doc, source, 1, target, ())
    assert len(parts) > 1
    assert "".join(p["quoted_text"] for p in parts) == source
    cursor = 0
    for part in parts:
        assert part["start_char"] == cursor
        cursor = part["end_char"]
        assert part["quoted_text"] == source[part["start_char"]:cursor]
        assert len(part["quoted_text"].encode()) <= target


def test_pinned_chunk_target_survives_flag_changes(settings):
    from apps.legislation.enhancements.model_selection import owned_token_target, planning_for
    settings.LLM_READER_OWNED_TOKEN_TARGET = 4000
    with planning_for(("openrouter", "concrete"), owned_target=1000):
        assert owned_token_target() == 1000
    assert owned_token_target() == 4000


def test_metadata_refresh_preserves_budget_identity():
    from dataclasses import replace
    cap = resolve_capabilities("openrouter", "example")
    changed = replace(cap, fetched_at="later")
    assert plan_request({"instructions": "Read", "max_output_tokens": 2000}, cap) == plan_request(
        {"instructions": "Read", "max_output_tokens": 2000}, changed)
    assert cap.fingerprint != replace(cap, output_tokens=cap.output_tokens + 1).fingerprint
