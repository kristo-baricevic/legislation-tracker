from types import SimpleNamespace

import pytest
from django.test import override_settings

from apps.legislation.enhancements.model_capabilities import resolve_capabilities
from apps.legislation.enhancements.reader_chunking import planned_sources
from apps.legislation.enhancements.token_budget import plan_request

from .test_enhancement_service import (
    _valid_credential,
    enhancement_owner,
    enhancement_settings,
    source_bill,
)


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
        assert part["quoted_text"] == source[part["start_char"] : cursor]
        assert len(part["quoted_text"].encode()) <= target


def test_pinned_chunk_target_survives_flag_changes(settings):
    from apps.legislation.enhancements.model_selection import (
        owned_token_target,
        planning_for,
    )

    settings.LLM_READER_OWNED_TOKEN_TARGET = 4000
    with planning_for(("openrouter", "concrete"), owned_target=1000):
        assert owned_token_target() == 1000
    assert owned_token_target() == 4000


@pytest.mark.django_db
def test_variant_command_uses_explicit_limits(source_bill, tmp_path, settings):
    import hashlib
    import json
    from io import StringIO

    from django.core.management import call_command

    settings.STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": tmp_path},
        }
    }
    doc = source_bill.documents.get()
    doc.object_storage_key = "source.txt"
    doc.save()
    raw = doc.extracted_text.encode()
    (tmp_path / doc.object_storage_key).write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    manifest = tmp_path / "case.json"
    manifest.write_text(
        json.dumps(
            dict(
                document=doc.pk,
                bill=source_bill.pk,
                xml_sha256=digest,
                text_sha256=digest,
            )
        )
    )
    output = StringIO()
    call_command(
        "estimate_reader_variants",
        str(manifest),
        "--provider",
        "openai",
        "--model",
        "offline",
        "--context-tokens",
        "100000",
        "--output-tokens",
        "10000",
        stdout=output,
    )
    rows = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [row["target"] for row in rows] == [1000, 2000, 4000]
    assert all(0 < row["budget"]["maximum_request_output"] <= 10000 for row in rows)
    output = StringIO()
    call_command(
        "estimate_reader_variants",
        str(manifest),
        "--provider",
        "openai",
        "--model",
        "offline",
        "--context-tokens",
        "3000",
        "--output-tokens",
        "1024",
        stdout=output,
    )
    assert [
        json.loads(line)["rejected"] for line in output.getvalue().splitlines()
    ] == ["request_too_large"] * 3


@pytest.mark.django_db
def test_legacy_catalog_limits_reach_estimate_and_transport(
    source_bill, enhancement_owner, enhancement_settings, monkeypatch
):
    from rest_framework.test import APIClient

    from apps.legislation.enhancements import openrouter_catalog
    from apps.legislation.enhancements.model_selection import planning_for
    from apps.legislation.enhancements.source_packet import build_enhancement_preflight

    from .test_enhancement_openai_compatible_provider import (
        FakeClientFactory,
        FakeCompletions,
        OpenAICompatibleEnhancementProvider,
        _completed_response,
    )

    model = "fixture/small:free"
    metadata = {
        "provider": "openrouter",
        "model": model,
        "context_tokens": 50000,
        "output_tokens": 2048,
    }
    monkeypatch.setattr(openrouter_catalog, "entries", lambda: {model: metadata})
    with (
        enhancement_settings,
        override_settings(
            LLM_SOURCE_FIRST_ENABLED=False, LLM_READER_OWNED_TOKEN_TARGET=0
        ),
    ):
        credential = _valid_credential(enhancement_owner)
        credential.provider = credential.validated_provider = "openrouter"
        credential.selected_model = credential.validated_model = model
        credential.save()
        client = APIClient()
        client.force_authenticate(enhancement_owner)
        url = f"/api/bills/{source_bill.pk}/enhancements/estimate/"
        estimate = client.get(url).data
        assert (
            estimate["can_enhance"] and estimate["max_output_tokens"] == 2048
        ), estimate
        with planning_for(("openrouter", model)):
            plan = build_enhancement_preflight(source_bill)
        response = _completed_response()
        response.model = model
        completions = FakeCompletions(result=response)
        provider = OpenAICompatibleEnhancementProvider(
            client_factory=FakeClientFactory(completions)
        )
        provider.enhance_bill(api_key="offline", request=plan, timeout_seconds=1)
        assert completions.calls[0]["max_tokens"] == 2048
        from apps.legislation.enhancements.glossary import build_glossary_batches
        from apps.legislation.enhancements.providers.base import ProviderError

        definition = {"start_char": 0, "end_char": 4, "definition_id": "test"}
        with planning_for(("openrouter", model)):
            (batch,) = build_glossary_batches(source_bill, "Test", "IH", [definition])
            assert batch["envelope"]["max_output_tokens"] == 2048
        provider.repair_citations(
            api_key="offline", request=plan, payload={}, timeout_seconds=1
        )
        assert completions.calls[-1]["max_tokens"] == 2048
        with pytest.raises(ProviderError, match="request_too_large"):
            provider.repair_citations(
                api_key="offline",
                request=plan,
                payload={"text": "x" * 50000},
                timeout_seconds=1,
            )
        assert len(completions.calls) == 2
        metadata["context_tokens"] = 3000
        assert client.get(url).data["unavailable_reason"] == "request_too_large"


def test_metadata_refresh_preserves_budget_identity():
    from dataclasses import replace

    cap = resolve_capabilities("openrouter", "example")
    changed = replace(cap, fetched_at="later")
    assert plan_request(
        {"instructions": "Read", "max_output_tokens": 2000}, cap
    ) == plan_request({"instructions": "Read", "max_output_tokens": 2000}, changed)
    assert (
        cap.fingerprint != replace(cap, output_tokens=cap.output_tokens + 1).fingerprint
    )
