import json
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.legislation.enhancements.providers.base import ProviderResult, ProviderUsage

CORPUS_PATH = (
    Path(__file__).parent / "fixtures" / "llm_enhancement" / "evaluation_cases.json"
)


def test_evaluation_corpus_has_25_versioned_representative_federal_cases():
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))

    assert corpus["corpus_version"] == "1.0"
    assert len(corpus["cases"]) >= 25
    assert all(case["jurisdiction"] == "federal" for case in corpus["cases"])
    assert len({case["category"] for case in corpus["cases"]}) >= 7
    assert any(case["truncated"] for case in corpus["cases"])
    assert any("instruction" in case["source_text"].lower() for case in corpus["cases"])


@pytest.mark.django_db
def test_evaluation_requires_explicit_execute_and_hard_budgets():
    with pytest.raises(CommandError, match="--execute"):
        call_command(
            "evaluate_bill_enhancements",
            case_limit=1,
            max_input_tokens=1000,
            max_output_tokens=200,
        )

    with pytest.raises(CommandError, match="case-limit"):
        call_command(
            "evaluate_bill_enhancements",
            execute=True,
            case_limit=0,
            max_input_tokens=1000,
            max_output_tokens=200,
        )


@pytest.mark.django_db
def test_evaluation_uses_dedicated_key_prints_budget_before_calls_and_writes_only_explicit_artifact(
    monkeypatch,
    tmp_path,
    capsys,
):
    events = []

    class Provider:
        def enhance_bill(self, **kwargs):
            events.append(("call", capsys.readouterr().out, kwargs))
            source_ref = kwargs["request"].source_snapshot[0]["source_ref"]
            return ProviderResult(
                output={
                    "schema_version": "1.1",
                    "overview": [
                        {
                            "text": "The cited provision creates a duty.",
                            "source_refs": [source_ref],
                        }
                    ],
                    "key_impacts": [],
                    "obligations": [],
                    "funding_and_timing": [],
                    "uncertain_language": [],
                },
                usage=ProviderUsage(
                    input_tokens=100, output_tokens=20, total_tokens=120
                ),
                response_id="private-evaluation-response",
                resolved_model="evaluation-model",
            )

    monkeypatch.setattr(
        "apps.legislation.management.commands.evaluate_bill_enhancements.get_provider",
        lambda name: Provider(),
    )
    output_path = tmp_path / "evaluation-results.json"
    with override_settings(
        LLM_ENHANCEMENT_EVALUATION_API_KEY="sk-evaluation-dedicated",
        LLM_ENHANCEMENT_PROVIDER="openai",
        LLM_ENHANCEMENT_MODEL="gpt-5.6-luna",
        LLM_ENHANCEMENT_REASONING_EFFORT="none",
        LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS=90,
        LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS=4000,
    ):
        call_command(
            "evaluate_bill_enhancements",
            execute=True,
            case_limit=1,
            max_input_tokens=5000,
            max_output_tokens=200,
            output=str(output_path),
        )

    assert len(events) == 1
    _, output_before_call, kwargs = events[0]
    assert "cases=1" in output_before_call
    assert "max_input_tokens=5000" in output_before_call
    assert "max_output_tokens=200" in output_before_call
    assert kwargs["api_key"] == "sk-evaluation-dedicated"
    artifact = json.loads(output_path.read_text(encoding="utf-8"))
    assert artifact["corpus_version"] == "1.0"
    assert artifact["results"][0]["output"]["schema_version"] == "1.1"
    combined = output_before_call + capsys.readouterr().out
    assert "sk-evaluation-dedicated" not in combined
    assert "private-evaluation-response" not in combined


def test_evaluation_sanitizes_schema_invalid_provider_output(
    monkeypatch,
    tmp_path,
    capsys,
):
    secret_output = "provider-output-must-not-appear"

    class Provider:
        def enhance_bill(self, **kwargs):
            return ProviderResult(
                output={"schema_version": "1.1", "overview": secret_output},
                usage=ProviderUsage(),
                response_id="private-response-id",
                resolved_model="evaluation-model",
            )

    monkeypatch.setattr(
        "apps.legislation.management.commands.evaluate_bill_enhancements.get_provider",
        lambda name: Provider(),
    )
    output_path = tmp_path / "invalid-evaluation-results.json"
    with override_settings(
        LLM_ENHANCEMENT_EVALUATION_API_KEY="sk-evaluation-dedicated",
        LLM_ENHANCEMENT_PROVIDER="openai",
        LLM_ENHANCEMENT_MODEL="gpt-5.6-luna",
        LLM_ENHANCEMENT_REASONING_EFFORT="none",
        LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS=90,
        LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS=4000,
    ):
        call_command(
            "evaluate_bill_enhancements",
            execute=True,
            case_limit=1,
            max_input_tokens=5000,
            max_output_tokens=200,
            output=str(output_path),
        )

    artifact = json.loads(output_path.read_text(encoding="utf-8"))
    assert artifact["results"] == [
        {
            "case_id": "federal-obligation-01",
            "category": "obligation",
            "status": "failed",
            "failure_category": "invalid_output",
        }
    ]
    combined = capsys.readouterr().out + output_path.read_text(encoding="utf-8")
    assert secret_output not in combined
    assert "private-response-id" not in combined
