# ruff: noqa: F401, F811
import pytest

from apps.legislation.models import BillContract, EvidenceSpan
from apps.legislation.enhancements.source_packet import build_enhancement_preflight, PreflightUnavailable
from apps.legislation.enhancements.reader_targets import snapshot_targets
from apps.legislation.enhancements.providers.base import ProviderResult, ProviderUsage
from apps.legislation.enhancements.serializers import enhancement_payload
from apps.legislation.tests.test_enhancement_tasks import _pending_attempt
from apps.legislation.tests.test_enhancement_service import enhancement_owner, enhancement_settings, source_bill
from apps.legislation.tasks import run_bill_enhancement_attempt


def install_reader(bill, count=10):
    document = bill.documents.get()
    text = document.extracted_text
    lines = [{"id": f"line-{i}", "display_text": "Publish a report within 90 days.",
              "evidence_paths": [f"line_items[{i}].display_text"]} for i in range(count)]
    c = BillContract.objects.create(bill=bill, document=document, contract_hash="reader-hash",
        schema_version="2.1-legal-nlp", contract_json={"schema_version": "2.1-legal-nlp",
            "line_items": lines, "financial_items": [], "definitions": [], "timeline_items": []})
    for i in range(count):
        EvidenceSpan.objects.create(bill=bill, document=document, contract=c,
            field_path=f"line_items[{i}].display_text", start_char=0, end_char=len(text), quoted_text=text)
    bill.latest_contract = c
    bill.save()
    return c


@pytest.mark.django_db(transaction=True)
def test_discovery_publishes_new_money_with_citations_when_nlp_found_none(
    source_bill, enhancement_owner, enhancement_settings, monkeypatch
):
    c = install_reader(source_bill)
    document = source_bill.documents.get()
    document.extracted_text = 'SEC. 1. Housing\nThe first housing grant shall be $100,000,000.'
    document.save()
    c.contract_json.update(line_items=[], financial_items=[])
    c.save()

    class Provider:
        def enhance_bill(self, *, request, **kwargs):
            source = request.source_snapshot[0]
            quote = {'source_ref': source['source_ref'], 'quote_id': 'p0001'}
            if request.request_envelope.get('source_review'):
                output = {'financial_items': [{'label': 'Housing grants', 'amount_display': '$100 million',
                    'text': 'Provides a $100 million first housing grant.', 'fiscal_years': [], 'source_quotes': [quote]}],
                    'additional_changes': [], 'money_checks': {source['source_ref'] + ':p0001': 'financial'}}
            else:
                output = {'schema_version': '1.4', 'summary': [{'text': 'Provides housing grants.', 'source_quotes': [quote]}], 'explanations': []}
            return ProviderResult(output, ProviderUsage(10, 5, 15), 'review', 'test')

    monkeypatch.setattr('apps.legislation.tasks.get_provider', lambda _: Provider())
    with enhancement_settings:
        attempt = _pending_attempt(enhancement_owner, source_bill)
        outcome = run_bill_enhancement_attempt(attempt.pk, attempt.dispatch_token)
    assert outcome['status'] == 'succeeded'
    attempt.enhancement.refresh_from_db()
    result = enhancement_payload(attempt.enhancement, detail=True)['result']
    assert result['explanations'] == []
    money = result['source_review']['financial_items']
    assert money[0]['amount_display'] == '$100 million'
    assert '$100,000,000' in money[0]['cited_sources'][0]['quoted_text']
    assert money[0]['cited_sources'][0]['start_char'] == 0


@pytest.mark.django_db
def test_reader_preflight_pins_contract_and_exposes_all_targets(source_bill, enhancement_settings):
    from django.test import override_settings
    c = install_reader(source_bill)
    with enhancement_settings:
        p = build_enhancement_preflight(source_bill)
        assert p.output_schema_version == "1.4"
        assert p.source_manifest["reader"]["selected_count"] == 10
        assert p.source_manifest["reader"]["unavailable_count"] == 0
        assert len(p.reader_batches) == 2
        assert p.reader_batches[-1].request_envelope['source_review']
        # Shared enclosing text appears once per request, not once per target.
        assert len(p.reader_batches[0].source_snapshot) == 1
        assert len(snapshot_targets(p.reader_batches[0].source_snapshot)) == 10
        rules = p.reader_batches[0].request_envelope["source_packet"]["target_citations"]
        assert {r["target_id"] for r in rules} == {t["target_id"] for t in snapshot_targets(p.reader_batches[0].source_snapshot)}
        assert all(r["allowed_source_refs"] == [p.reader_batches[0].source_snapshot[0]["source_ref"]] for r in rules)
        assert all(r["own_evidence"] for r in rules)
        assert p.source_manifest["budget"]["planned_calls"] == 3
        assert p.source_manifest["budget"]["maximum_calls"] == 11
        assert p.reader_batches[0].request_envelope['max_output_tokens'] >= 8000
        assert p.source_manifest['budget']['maximum_output'] == sum(
            r.request_envelope['max_output_tokens'] for r in (p, *p.reader_batches)) + 8 * 24000
        wire_source = p.request_envelope["source_packet"]["sources"][0]
        assert "citation_passages" in wire_source
        assert "quoted_text" not in wire_source  # Do not send the text twice.
        assert wire_source["citation_passages"][0]["quote_id"] == "p0001"
        c.contract_hash = "new-contract"
        c.save()
        assert build_enhancement_preflight(source_bill).source_fingerprint != p.source_fingerprint
        with override_settings(LLM_READER_MAX_CALLS=1), pytest.raises(PreflightUnavailable):
            build_enhancement_preflight(source_bill)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("mode", ["success", "split", "missing", "revoked", "changed"])
def test_reader_pipeline_publishes_only_complete_current_targets(
    source_bill, enhancement_owner, enhancement_settings, monkeypatch, mode
):
    from apps.accounts.models import LLMCredential
    c = install_reader(source_bill)
    requests = []
    class Provider:
        def enhance_bill(self, *, request, **kwargs):
            requests.append(request)
            if request.request_envelope.get('source_review'):
                return ProviderResult({'financial_items': [], 'additional_changes': [], 'money_checks': {}},
                    ProviderUsage(10, 5, 15), 'review-response', 'test')
            targets = snapshot_targets(request.source_snapshot)
            if mode == 'split' and len(targets) == 10:
                from apps.legislation.enhancements.providers.base import ProviderError
                raise ProviderError('invalid_output', validation_code='provider_output_limit', usage=ProviderUsage(10, 5, 15))
            output = {"schema_version": "1.4", "summary": [], "explanations": []}
            if not targets:
                s = request.source_snapshot[0]
                output["summary"] = [{"text": "Requires a report within 90 days.",
                    "source_quotes": [{"source_ref": s["source_ref"], "quote_id": "p0001"}]}]
            for s in request.source_snapshot:
                for t in s.get("reader_targets", []):
                    output["explanations"].append({"target_id": t["target_id"],
                        "status": "explained", "text": "Publish a report within 90 days.",
                        "unresolved_reason": None,
                        "source_quotes": [{"source_ref": s["source_ref"], "quote_id": "p0001"}]})
            if targets and mode == "missing":
                output["explanations"].pop()
            if targets and mode == "revoked":
                LLMCredential.objects.filter(user=enhancement_owner).update(enabled=False)
            if targets and mode == "changed":
                c.contract_hash = "changed"
                c.save()
            return ProviderResult(output, ProviderUsage(10, 5, 15), "reader-response", "test")
    monkeypatch.setattr("apps.legislation.tasks.get_provider", lambda _: Provider())
    with enhancement_settings:
        a = _pending_attempt(enhancement_owner, source_bill)
        a.dispatch_token = "reader-test"
        a.save()
        outcome = run_bill_enhancement_attempt(a.pk, a.dispatch_token)
    a.refresh_from_db()
    a.enhancement.refresh_from_db()
    if mode in {"success", "split"}:
        assert outcome["status"] == "succeeded"
        assert len(requests) == (3 if mode == 'success' else 5)
        assert a.total_tokens == (45 if mode == 'success' else 75)
        assert a.steps.filter(status='validated').count() == (3 if mode == 'success' else 4)
        assert a.enhancement.result_json['source_review']['reviewed_sources']
        payload = enhancement_payload(a.enhancement, detail=True)
        assert len(payload["result"]["explanations"]) == 10
        assert payload["result"]["explanations"][0]["contract_id"] == c.pk
        assert payload["result"]["explanations"][0]["cited_sources"]
    else:
        assert outcome["status"] != "succeeded"
        assert a.enhancement.result_json is None
        assert len(requests) == 2


@pytest.mark.django_db
def test_source_compatibility_does_not_depend_on_execution_format(source_bill):
    from apps.legislation.enhancements.views import _source_compatible
    from types import SimpleNamespace
    import hashlib
    c = install_reader(source_bill)
    d = source_bill.documents.get()
    saved = SimpleNamespace(source_manifest_json={
        "document_id": d.pk, "document_content_hash": hashlib.sha256(d.extracted_text.encode()).hexdigest(),
        "contract_id": c.pk, "contract_hash": c.contract_hash},
        request_fingerprint="old-format", output_schema_version="1.4")
    assert _source_compatible(saved, source_bill)
    saved.source_manifest_json["contract_hash"] = "other"
    assert not _source_compatible(saved, source_bill)


@pytest.mark.django_db
def test_output_allowance_splits_batches_without_losing_targets(source_bill, enhancement_settings):
    from django.test import override_settings
    install_reader(source_bill, count=30)
    with enhancement_settings, override_settings(LLM_READER_MAX_OUTPUT_TOKENS=8000):
        small = build_enhancement_preflight(source_bill)
    with enhancement_settings, override_settings(LLM_READER_MAX_OUTPUT_TOKENS=24000):
        large = build_enhancement_preflight(source_bill)
    assert len(small.reader_batches) > len(large.reader_batches)
    small_ids = [t['target_id'] for b in small.reader_batches for t in snapshot_targets(b.source_snapshot)]
    large_ids = [t['target_id'] for b in large.reader_batches for t in snapshot_targets(b.source_snapshot)]
    assert small_ids == large_ids
    assert len(set(small_ids)) == 30
    assert [t['facts']['item']['member_ids'] for b in small.reader_batches for t in snapshot_targets(b.source_snapshot)] == [[f'line-{i}'] for i in range(30)]
    assert small.source_manifest['reader']['unavailable_count'] == 0
    assert small.request_fingerprint != large.request_fingerprint
    assert small.source_manifest['budget']['maximum_output'] == sum(
        r.request_envelope['max_output_tokens'] for r in (small, *small.reader_batches)) + 8 * 8000


@pytest.mark.django_db
def test_impossible_output_budget_rejected_before_paid_calls(source_bill, enhancement_settings):
    from django.test import override_settings
    install_reader(source_bill)
    with enhancement_settings, override_settings(LLM_READER_MAX_OUTPUT_TOKENS=100):
        with pytest.raises(PreflightUnavailable):
            build_enhancement_preflight(source_bill)


@pytest.mark.django_db
def test_status_freshness_does_not_build_request_plan(source_bill, enhancement_settings, monkeypatch):
    from types import SimpleNamespace
    from django.test import override_settings
    from apps.legislation.enhancements.views import _is_stale
    install_reader(source_bill)
    with enhancement_settings:
        p = build_enhancement_preflight(source_bill)
        saved = SimpleNamespace(source_manifest_json=p.source_manifest, output_schema_version=p.output_schema_version,
            request_fingerprint=p.request_fingerprint, prompt_version=p.prompt_version, provider=p.provider,
            requested_model=p.requested_model, reasoning_effort=p.reasoning_effort)
        def forbidden(*args, **kwargs):
            pytest.fail('Reading saved status must not rebuild the paid request plan')
        monkeypatch.setattr('apps.legislation.enhancements.views.build_enhancement_preflight', forbidden)
        assert not _is_stale(saved, source_bill)
        with override_settings(LLM_READER_MAX_OUTPUT_TOKENS=12000):
            assert _is_stale(saved, source_bill)
        source_bill.latest_contract.contract_hash = 'changed'
        assert _is_stale(saved, source_bill)
