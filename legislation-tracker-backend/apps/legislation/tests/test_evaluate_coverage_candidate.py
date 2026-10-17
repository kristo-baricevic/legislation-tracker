from io import StringIO

import pytest
from django.core.management import CommandError, call_command


def test_dry_run_uses_pinned_source_without_key_or_provider(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Dry run must not call provider")

    monkeypatch.setattr(
        "apps.legislation.management.commands.evaluate_coverage_candidate.get_provider",
        forbidden,
    )
    output = StringIO()
    call_command(
        "evaluate_coverage_candidate", "--case", "BILLS-119hr1589ih", stdout=output
    )
    assert '"execute": false' in output.getvalue()
    assert '"maximum_calls": 2' in output.getvalue()


def test_existing_artifact_prevents_repeat_spend(tmp_path, monkeypatch):
    path = tmp_path / "run.json"
    path.write_text("existing")
    with pytest.raises(CommandError, match="refusing overwrite"):
        call_command(
            "evaluate_coverage_candidate",
            "--case",
            "BILLS-119hr1589ih",
            "--execute",
            "--output",
            str(path),
        )
    assert path.read_text() == "existing"


def test_failed_dispatch_is_not_left_marked_running(tmp_path, monkeypatch, settings):
    import json
    from types import SimpleNamespace

    from apps.legislation.enhancements.providers.base import (
        ProviderError,
        ProviderUsage,
    )

    settings.LLM_ENHANCEMENT_EVALUATION_API_KEY = "test"

    def fail(**kwargs):
        raise ProviderError(
            "invalid_output",
            validation_code="provider_output_incomplete",
            usage=ProviderUsage(10, 8000, 8010),
        )

    monkeypatch.setattr(
        "apps.legislation.management.commands.evaluate_coverage_candidate.get_provider",
        lambda provider: SimpleNamespace(enhance_bill=fail),
    )
    path = tmp_path / "failed.json"
    with pytest.raises(CommandError, match="Not release-approved"):
        call_command(
            "evaluate_coverage_candidate",
            "--case",
            "BILLS-119hr1589ih",
            "--provision-first",
            "--execute",
            "--output",
            str(path),
        )
    artifact = json.loads(path.read_text())
    assert artifact["dispatches"][0]["status"] == "failed"
    assert artifact["dispatches"][0]["validation_code"] == "provider_output_incomplete"
    assert artifact["evaluation"]["attempts"][0]["usage"]["output_tokens"] == 8000
