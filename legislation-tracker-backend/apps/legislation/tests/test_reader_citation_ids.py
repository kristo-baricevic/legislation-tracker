import copy
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError
from jsonschema import Draft202012Validator

from apps.legislation.enhancements.reader_citations import READER_ID_SCHEMA, citation_passages, resolve_reader_citations
from apps.legislation.tests.test_enhancement_reader_targets import packet
from apps.legislation.tests.test_enhancement_service import source_bill, enhancement_owner, enhancement_settings


def test_s4387_real_response_cannot_publish_or_reuse_period_only_text():
    from apps.legislation.enhancements.reader_citations import recover_reader_items
    fixture = json.loads((Path(__file__).parent / 'fixtures/s4387_period_only_response.json').read_text())
    target, source, output = fixture['target'], fixture['source'], fixture['output']
    with pytest.raises(ValidationError):
        resolve_reader_citations(output, [target], [source])
    recovered = recover_reader_items(output, [target], [source])
    item = recovered['explanations'][target['target_id']]
    assert item['status'] == 'unresolved'
    assert item['text'] is None
    assert item['source_quotes'] == []


def test_summary_rejects_internal_citation_ids_in_reader_prose():
    _, source, output = packet()
    output['explanations'] = []
    output['summary'] = [{'text': 'Employers must adopt a policy. (src_0001, p0001)',
                          'source_quotes': [{'source_ref': 'src_0001', 'quote_id': 'p0001'}]}]
    with pytest.raises(ValidationError):
        resolve_reader_citations(output, [], [source])


def test_server_resolves_exact_quote_without_model_transcription():
    target, source, output = packet()
    output["explanations"][0]["source_quotes"] = [{"source_ref": "src_0001", "quote_id": "p0001"}]
    original = copy.deepcopy(output)
    result = resolve_reader_citations(output, [target], [source])
    assert result["explanations"][0]["source_quotes"] == [{
        "source_ref": "src_0001",
        "quote": "Employers with at least 15 employees must adopt a policy within one year.",
    }]
    assert output == original


@pytest.mark.parametrize("mutation", ["unknown_id", "wrong_source", "wrong_target", "invented_quote", "outside_evidence"])
def test_ids_cannot_bypass_source_or_target_validation(mutation):
    target, source, output = packet()
    quote = {"source_ref": "src_0001", "quote_id": "p0001"}
    output["explanations"][0]["source_quotes"] = [quote]
    if mutation == "unknown_id":
        quote["quote_id"] = "p9999"
    elif mutation == "wrong_source":
        quote["source_ref"] = "src_9999"
    elif mutation == "wrong_target":
        source["reader_targets"] = [{**target, "target_id": "other"}]
    elif mutation == "invented_quote":
        quote["quote"] = "No employer has obligations."
    else:
        target["evidence_ranges"] = [[1000, 1100]]
    with pytest.raises(ValidationError):
        resolve_reader_citations(output, [target], [source])


def test_passages_retain_all_whitespace_and_stay_within_quote_limit():
    text = ("The Secretary shall publish a report.\n\n" * 31) + "The amount is $10,000."
    passages = citation_passages({"quoted_text": text})
    assert "".join(p["text"] for p in passages) == text
    assert all(len(p["text"]) <= 800 for p in passages)
    assert any(p["quote_id"] is None for p in passages)  # Repeated text is not guessed.


def test_wire_schema_requires_every_target_and_rejects_wrong_source_pairs():
    from apps.legislation.enhancements.reader_citations import bounded_reader_schema
    from jsonschema import Draft202012Validator
    target, source, output = packet()
    item = output["explanations"][0]
    item["source_quotes"] = [{"source_ref": "src_0001", "quote_id": "p0001"}]
    output["explanations"] = {target["target_id"]: item}
    schema = bounded_reader_schema([source], [target], {"src_0001": citation_passages(source)})
    Draft202012Validator(schema).validate(output)
    assert resolve_reader_citations(output, [target], [source])["explanations"][0]["target_id"] == target["target_id"]
    item["source_quotes"][0]["source_ref"] = "src_9999"
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(output)
    output["explanations"] = {}
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(output)
    with pytest.raises(ValidationError):
        resolve_reader_citations(output, [target], [source])


def test_summary_uses_the_same_id_resolution():
    _, source, output = packet()
    output["explanations"] = []
    output["summary"] = [{"text": "Covered employers must adopt a policy.",
                          "source_quotes": [{"source_ref": "src_0001", "quote_id": "p0001"}]}]
    result = resolve_reader_citations(output, [], [source])
    assert result["summary"][0]["source_quotes"][0]["quote"] == source["quoted_text"]


@pytest.mark.parametrize("mutation", ["explained_with_reason", "unresolved_with_text", "unresolved_with_quotes", "unresolved_without_reason"])
def test_provider_schema_prevents_contradictory_outcomes(mutation):
    _, _, output = packet()
    item = output["explanations"][0]
    item["source_quotes"] = [{"source_ref": "src_0001", "quote_id": "p0001"}]
    if mutation == "explained_with_reason":
        item["unresolved_reason"] = "External context needed."
    else:
        item.update(status="unresolved", text=None, unresolved_reason="External context needed.", source_quotes=[])
        if mutation == "unresolved_with_text":
            item["text"] = "A partial explanation."
        elif mutation == "unresolved_with_quotes":
            item["source_quotes"] = [{"source_ref": "src_0001", "quote_id": "p0001"}]
        else:
            item["unresolved_reason"] = None
    with pytest.raises(ValidationError):
        Draft202012Validator(READER_ID_SCHEMA).validate(output)


def test_valid_unresolved_outcome_preserves_original_fallback():
    target, source, output = packet()
    output["explanations"][0].update(status="unresolved", text=None,
        unresolved_reason="Requires external law.", source_quotes=[])
    assert resolve_reader_citations(output, [target], [source]) == output


@pytest.mark.django_db
def test_bill_460_neighboring_evidence_keeps_original_and_preserves_valid_sibling(source_bill, enhancement_owner, enhancement_settings):
    import hashlib
    from dataclasses import replace
    from datetime import timedelta
    from django.utils import timezone
    from apps.legislation.enhancements.reader_citations import bounded_reader_schema
    from apps.legislation.enhancements.reader_steps import DurableReaderProvider
    from apps.legislation.enhancements.providers.base import ProviderResult, ProviderUsage
    from apps.legislation.enhancements.source_packet import build_enhancement_preflight
    from apps.legislation.tests.test_enhancement_tasks import _pending_attempt
    from apps.legislation.tests.test_reader_enhancement_pipeline import install_reader
    # Bill 460: waiver and fee provisions share a source section, not evidence.
    waiver = "With respect to any benefit under this title, and in addition to the waivers under subsection (c)(2), "
    fee = "The Secretary may, subject to an exemption under section 303(c), require an alien applying under this section "
    text = waiver.ljust(800) + fee
    targets = [dict(target_id=k, kind="line_item", evidence_ranges=[span]) for k, span in
               [("waiver", [0, len(waiver)]), ("fee", [800, len(text)])]]
    source = dict(source_ref="src_0029", quoted_text=text, start_char=0, end_char=len(text),
                  text_sha256=hashlib.sha256(text.encode()).hexdigest(), reader_targets=targets)
    claims = {k: dict(target_id=k, status="explained", text=v, unresolved_reason=None,
                      source_quotes=[dict(source_ref="src_0029", quote_id="p0002")])
              for k, v in [("waiver", "Unsupported waiver explanation."), ("fee", "The fee rule includes an exemption.")]}
    output = dict(schema_version="1.4", summary=[], explanations=claims)
    schema = bounded_reader_schema([source], targets, {"src_0029": citation_passages(source)})
    assert not Draft202012Validator(schema).is_valid(output)
    install_reader(source_bill)
    class Provider:
        def enhance_bill(self, **kwargs):
            # A split provision-only call on the live rerun also returned an unwanted summary.
            return ProviderResult({**output, "summary": [{"text": "Unrequested summary.", "source_quotes": []}]},
                                  ProviderUsage(10, 5, 15), "response", "offline")
    with enhancement_settings:
        request = replace(build_enhancement_preflight(source_bill), source_snapshot=[source])
        attempt = _pending_attempt(enhancement_owner, source_bill)
        attempt.status, attempt.run_token = "running", "test"
        attempt.lease_expires_at = timezone.now() + timedelta(minutes=2)
        attempt.save()
        wrapper = DurableReaderProvider(Provider(), attempt, "test", 1)
        safe = wrapper.enhance_bill(api_key="offline", request=request, timeout_seconds=1).output
        assert safe["summary"] == []
        assert attempt.steps.get().result_json == safe
        reused = wrapper.enhance_bill(api_key="offline", request=request, timeout_seconds=1)
        assert reused.output == safe and reused.usage.total_tokens == 0
        assert wrapper.paid_calls == 1
    valid = resolve_reader_citations(safe, targets, [source])["explanations"]
    assert valid[0]["status"] == "unresolved" and valid[0]["text"] is None and not valid[0]["source_quotes"]
    assert valid[1]["text"] == claims["fee"]["text"]
    assert valid[1]["source_quotes"] == [{"source_ref": "src_0029", "quote": fee}]
