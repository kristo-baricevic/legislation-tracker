import pytest
from django.test import override_settings

from apps.legislation.enhancements.reader_discovery import discovery_sources
from apps.legislation.enhancements.source_packet import build_enhancement_preflight
from apps.legislation.tests.test_enhancement_service import source_bill, enhancement_settings
from apps.legislation.tests.test_reader_enhancement_pipeline import install_reader


@pytest.mark.django_db
@pytest.mark.parametrize('source_first', [False, True])
def test_large_html_without_nlp_contract_never_falls_back_to_selective_legacy_summary(source_bill, enhancement_settings, source_first):
    doc = source_bill.documents.get()
    doc.content_type = 'text/html'
    doc.object_storage_key = 'public-law.html'
    doc.extracted_text = ''.join(f'SEC. {i}. Reports\n' + ''.join(
        f'The agency shall publish report {i}-{j} for the public.\n' for j in range(100)) for i in range(12))
    doc.save()
    with enhancement_settings, override_settings(LLM_SOURCE_FIRST_ENABLED=source_first,
            LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS=50000, LLM_READER_MAX_CALLS=0):
        plan = build_enhancement_preflight(source_bill)
    assert plan.output_schema_version == '1.4'
    scans = [s for s in plan.source_snapshot if s.get('discovery_source')]
    assert ''.join(s['quoted_text'] for s in scans) == doc.extracted_text
    assert plan.source_manifest['coverage']['complete_document'] is True


@pytest.mark.django_db
def test_large_xml_without_contract_routes_to_complete_review(source_bill, enhancement_settings, monkeypatch):
    from apps.legislation.enhancements.source_packet import PreflightUnavailable
    doc = source_bill.documents.get()
    # Bytes exceed the input cap even though the character count fits.
    section = "学校は出席を報告する。\n" * 270
    doc.extracted_text = section * 16
    doc.save()
    rows = [(str(i), i * len(section), (i + 1) * len(section), f"Sec. {i+1}", "")
            for i in range(16)]
    monkeypatch.setattr("apps.legislation.enhancements.xml_sections.stored_xml_sections",
                        lambda document, text: rows)
    with enhancement_settings, override_settings(LLM_SOURCE_FIRST_ENABLED=True, LLM_READER_MAX_CALLS=0):
        plan = build_enhancement_preflight(source_bill)
        assert plan.source_manifest["source_kind"] == "xml_full_review"
        assert plan.source_manifest["coverage"]["sections_planned"] == 16
        assert plan.source_manifest["coverage"]["source_chars_planned"] == len(doc.extracted_text)
        with override_settings(LLM_READER_MAX_CALLS=1), pytest.raises(PreflightUnavailable):
            build_enhancement_preflight(source_bill)


def test_xml_review_reuse_only_stops_when_reader_contract_becomes_available():
    from types import SimpleNamespace
    from apps.legislation.enhancements.shared import source_compatible
    contract = SimpleNamespace(document_id=1, schema_version="2.0-legal-nlp", contract_json={})
    bill = SimpleNamespace(latest_contract=contract)
    document = SimpleNamespace(pk=1, reader_text_hash="abc", bill=bill)
    saved = SimpleNamespace(output_schema_version="1.4", source_manifest_json={
        "document_id": 1, "document_content_hash": "abc", "source_kind": "xml_full_review"})
    assert source_compatible(saved, bill, identity=(document, contract))
    contract.schema_version = contract.contract_json["schema_version"] = "2.1-legal-nlp"
    assert not source_compatible(saved, bill, identity=(document, contract))


def test_large_section_context_is_bounded_and_every_source_byte_is_reviewed():
    text = 'SEC. 1. Grants\n' + ''.join(
        f'Program {i}: The Secretary shall provide grants to eligible schools.\n' for i in range(3000))
    sources = discovery_sources(text, 1)
    assert ''.join(s['quoted_text'] for s in sources) == text
    assert all(len(s.get('section_context', '').encode()) < 32000 for s in sources)
    assert all(s.get('section_context_complete') is False for s in sources)


@pytest.mark.django_db
def test_summary_includes_financial_and_additional_changes_alongside_policies(source_bill, enhancement_settings):
    from apps.legislation.enhancements.reader_summary import summarize_review
    from apps.legislation.enhancements.reader_citations import citation_passages
    from apps.legislation.enhancements.providers.base import ProviderResult, ProviderUsage
    install_reader(source_bill, count=0)
    with enhancement_settings:
        preflight = build_enhancement_preflight(source_bill)
        source = next(s for s in preflight.source_snapshot if s.get('discovery_source'))
        quote = {'source_ref': source['source_ref'], 'quote': citation_passages(source)[0]['text']}
        texts = ['Creates a school program.', 'Funds the program with $10,000.', 'Requires a public annual report.']
        review = {key: [{'text': text, 'source_quotes': [quote]}] for key, text in zip(
            ['policy_changes', 'financial_items', 'additional_changes'], texts)}
        class Provider:
            def enhance_bill(self, *, request, **kwargs):
                assert [item['text'] for item in request.request_envelope['source_packet']['validated_changes']] == texts
                wire = request.request_envelope['source_packet']['sources'][0]
                return ProviderResult({'schema_version': '1.4', 'explanations': [], 'summary': [{
                    'text': 'Creates and funds a school program that must report annually.',
                    'source_quotes': [{'source_ref': wire['source_ref'], 'quote_id': wire['citation_passages'][0]['quote_id']}]}]},
                    ProviderUsage(10, 5, 15), 'test', 'test')
        result, calls = summarize_review(preflight, review, Provider(), 'offline', lambda: None, 4)
    assert calls == 1
    assert result.output['summary']


@pytest.mark.django_db
def test_hr3045_missing_final_citation_keeps_verified_sanctions_finding(source_bill, enhancement_settings):
    import hashlib
    from dataclasses import replace
    from apps.legislation.enhancements.reader_summary import summarize_review
    from apps.legislation.enhancements.providers.base import ProviderResult, ProviderUsage, ProviderError
    install_reader(source_bill, count=0)
    with enhancement_settings:
        plan = build_enhancement_preflight(source_bill)
        source = dict(plan.source_snapshot[0], source_ref="src_0022")
        # H.R. 3045, section 3(a)(1)(B)(i), introduced text.
        quote = "An act of violence or threat of violence targeting civilians."
        source.update(quoted_text=quote, start_char=0, end_char=len(quote), text_sha256=hashlib.sha256(quote.encode()).hexdigest())
        plan = replace(plan, source_snapshot=[source])
        finding = {"text": "Violence against civilians is one of the listed grounds for sanctions.",
                   "source_quotes": [{"source_ref": "src_0022", "quote": quote}]}
        class Provider:
            def enhance_bill(self, *, request, **kwargs):
                citations = request.request_envelope["source_packet"]["validated_changes"][0]["source_quotes"]
                assert citations == [{"source_ref": "src_0022", "quote_id": "p0001"}]
                assert request.request_envelope["output_schema"]["properties"]["summary"]["items"]["properties"]["source_quotes"]["minItems"] == 1
                if request.request_envelope.get('summary_repair'):
                    return ProviderResult({'schema_version': '1.4', 'explanations': [], 'summary': [
                        {'text': 'The bill lists violence against civilians as grounds for sanctions.',
                         'source_quotes': citations}]}, ProviderUsage(10, 5, 15), 'test', 'test')
                if durable in ('wrong_number', 'punctuation'):
                    text = 'Violence against civilians triggers a $900 fee.' if durable == 'wrong_number' else '.'
                    return ProviderResult({'schema_version': '1.4', 'explanations': [], 'summary': [
                        {'text': text, 'source_quotes': citations}]}, ProviderUsage(10, 5, 15), 'test', 'test')
                if durable:
                    raise ProviderError("invalid_output", validation_code=durable, usage=ProviderUsage(10, 5, 15))
                return ProviderResult({"schema_version": "1.4", "explanations": [], "summary": [
                    {"text": "An unsupported claim.", "source_quotes": []}]}, ProviderUsage(10, 5, 15), "test", "test")
        for durable in (False, "citation_quote_not_found", "reader_amount_conflict", "wrong_number", "punctuation"):
            result, calls = summarize_review(plan, {"policy_changes": [finding]}, Provider(), "offline", lambda: None, 2)
            assert calls == 2
            assert result.output["summary"][0]["text"] == 'The bill lists violence against civilians as grounds for sanctions.'
            assert result.output["summary"][0]["source_quotes"] == finding["source_quotes"]
            assert result.usage.total_tokens == 30
            with pytest.raises((ProviderError, __import__('jsonschema').ValidationError)):
                summarize_review(plan, {"policy_changes": [finding]}, Provider(), "offline", lambda: None, 1)


@pytest.mark.django_db
@pytest.mark.parametrize("omit_last_citation", [False, True], ids=["valid-summary", "partially-uncited-summary"])
def test_summary_keeps_each_finding_with_its_own_source(source_bill, enhancement_settings, omit_last_citation):
    import hashlib
    import json
    from dataclasses import replace

    from apps.legislation.enhancements.providers.base import ProviderResult, ProviderUsage
    from apps.legislation.enhancements.reader_summary import summarize_review

    install_reader(source_bill, count=0)
    with enhancement_settings:
        plan = build_enhancement_preflight(source_bill)
        # Both documents' passages are called p0001. Only the pair identifies the evidence.
        facts = [("src_0022", "Schools shall publish an annual report.", "Schools must report every year."),
                 ("src_0011", "Libraries may award grants.", "Libraries can give grants.")]
        sources = [dict(plan.source_snapshot[0], source_ref=ref, quoted_text=quote, start_char=0,
                        end_char=len(quote), text_sha256=hashlib.sha256(quote.encode()).hexdigest())
                   for ref, quote, _ in facts]
        findings = [{"text": text, "source_quotes": [{"source_ref": ref, "quote": quote}]}
                    for ref, quote, text in facts]

        class OfflineProvider:
            def enhance_bill(self, *, request, **kwargs):
                packet = json.loads(request.request_bytes)["source_packet"]
                assert packet["validated_changes"] == [
                    {"text": text, "source_quotes": [{"source_ref": ref, "quote_id": "p0001"}]}
                    for ref, _, text in facts]
                paragraphs = [{"text": "Libraries could provide grants.", "source_quotes": [
                    {"source_ref": "src_0011", "quote_id": "p0001"}]},
                    {"text": "Schools would publish yearly reports.", "source_quotes": [] if omit_last_citation
                     else [{"source_ref": "src_0022", "quote_id": "p0001"}]}]
                return ProviderResult({"schema_version": "1.4", "explanations": [], "summary": paragraphs},
                                      ProviderUsage(10, 5, 15), "test", "test")

        if omit_last_citation:
            from jsonschema import ValidationError
            with pytest.raises(ValidationError):
                summarize_review(replace(plan, source_snapshot=sources), {"policy_changes": findings},
                                 OfflineProvider(), "offline", lambda: None, 1)
            return
        result, calls = summarize_review(replace(plan, source_snapshot=sources), {"policy_changes": findings},
                                         OfflineProvider(), "offline", lambda: None, 1)
    assert calls == 1
    assert result.output["summary"] == (findings if omit_last_citation else [
        {"text": "Libraries could provide grants.", "source_quotes": findings[1]["source_quotes"]},
        {"text": "Schools would publish yearly reports.", "source_quotes": findings[0]["source_quotes"]}])


@pytest.mark.django_db
def test_missing_fee_rule_is_recovered_from_its_own_source_not_generated_text():
    from apps.legislation.enhancements.reader_discovery import retain_missing_financial_rules
    raw = 'Applicants must pay the first fee instead of the second fee.'
    target = {'kind': 'financial_item', 'target_id': 'fee', 'original_text': 'Both fees are due.',
              'evidence_ranges': [(0, len(raw))], 'facts': {'item': {'financial_action': 'fee'}}}
    source = {'source_ref': 'src_0001', 'start_char': 0, 'end_char': len(raw),
              'quoted_text': raw, 'discovery_source': True}
    sources = [source, {'reader_targets': [target]}]
    review = {'financial_items': []}
    retain_missing_financial_rules(review, sources)
    retain_missing_financial_rules(review, sources)
    assert len(review['financial_items']) == 1
    assert review['financial_items'][0]['text'] == raw
    assert review['financial_items'][0]['source_quotes'] == [{'source_ref': 'src_0001', 'quote': raw}]


@pytest.mark.django_db
def test_large_bill_uses_source_sized_confirmed_budget_not_fixed_call_count(source_bill, enhancement_settings):
    install_reader(source_bill, count=0)
    doc = source_bill.documents.get()
    doc.extracted_text = ''.join(f'SEC. {i}. Program {i}\n' + ''.join(
        f'School {j} shall report its program results for district {i}.\n' for j in range(110)) for i in range(1, 91))
    doc.save()
    with enhancement_settings, override_settings(LLM_READER_MAX_CALLS=0):
        p = build_enhancement_preflight(source_bill)
    assert p.source_manifest['budget']['planned_calls'] > 64
    assert p.source_manifest['budget']['maximum_calls'] >= p.source_manifest['budget']['planned_calls']
    assert not p.truncated
    assert p.source_manifest['coverage']['complete_document'] is True
    scans = [s for s in p.source_snapshot if s.get('discovery_source')]
    assert ''.join(s['quoted_text'] for s in scans) == doc.extracted_text
    assert all(len(r.request_bytes) <= 100000 for r in p.reader_batches)
    from apps.legislation.enhancements.reader_batches import execute_reader_batches
    from apps.legislation.enhancements.reader_citations import citation_passages
    from apps.legislation.enhancements.providers.base import ProviderResult, ProviderUsage
    calls = []
    class Provider:
        def enhance_bill(self, *, request, **kwargs):
            calls.append(request)
            if request.request_envelope.get('source_review'):
                source = request.source_snapshot[0]
                # Bill 460: a correction still missed coverage in the last chunk.
                if source['source_ref'] == scans[-1]['source_ref'] and 'review_quote_ids' not in source:
                    from apps.legislation.enhancements.providers.base import ProviderError
                    raise ProviderError('invalid_output', validation_code='reader_coverage_incomplete')
                quotes = [{'source_ref': source['source_ref'], 'quote_id': p['quote_id']}
                          for p in citation_passages(source) if p['quote_id'] and
                          ('review_quote_ids' not in source or p['quote_id'] in source['review_quote_ids'])]
                output = {'financial_items': [], 'additional_changes': [], 'money_checks': {},
                    'policy_changes': [{'title': 'Report school results', 'text': 'Schools must report their program results.', 'source_quotes': quotes}],
                    'policy_checks': {q['source_ref'] + ':' + q['quote_id']: 'explained' for q in quotes}}
            else:
                wire = request.request_envelope['source_packet']['sources'][0]
                output = {'schema_version': '1.4', 'explanations': [], 'summary': [{
                    'text': 'Schools must report how their programs perform.',
                    'source_quotes': [{'source_ref': wire['source_ref'], 'quote_id': wire['citation_passages'][0]['quote_id']}]}]}
            return ProviderResult(output, ProviderUsage(10, 5, 15), 'test', 'test')
    with enhancement_settings:
        result = execute_reader_batches(p, Provider(), 'offline', lambda *args: None)
    assert len(result.output['source_review']['reviewed_sources']) == 90
    assert result.output['summary']
    assert all(len(request.request_bytes) <= 100000 for request in calls)
    assert len(calls) <= p.source_manifest['budget']['maximum_calls']


@pytest.mark.django_db
@pytest.mark.parametrize('budget,error_code', [(4, 'provider_output_limit'), (3, 'provider_output_limit'), (4, 'provider_timeout')])
def test_summary_output_limit_splits_work_within_confirmed_budget(source_bill, enhancement_settings, budget, error_code):
    from apps.legislation.enhancements.reader_summary import summarize_review
    from apps.legislation.enhancements.reader_citations import citation_passages
    from apps.legislation.enhancements.providers.base import ProviderError, ProviderResult, ProviderUsage
    install_reader(source_bill, count=0)
    doc = source_bill.documents.get()
    doc.extracted_text = 'SEC. 1. Schools\nSchools must report attendance.\nSEC. 2. Libraries\nLibraries must report visits.'
    doc.save()
    with enhancement_settings:
        preflight = build_enhancement_preflight(source_bill)
        sources = [s for s in preflight.source_snapshot if s.get('discovery_source')]
        review = {'policy_changes': [{'text': text, 'source_quotes': [{'source_ref': source['source_ref'],
            'quote': citation_passages(source)[0]['text']}]} for source, text in zip([sources[0], sources[-1]],
                ['Schools must report attendance at their institutions.', 'Libraries must report visits to their institutions.'])]}
        class Provider:
            calls = 0
            def enhance_bill(self, *, request, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise ProviderError('invalid_output', validation_code=error_code, usage=ProviderUsage(10, 5, 15))
                wire = request.request_envelope['source_packet']['sources'][0]
                return ProviderResult({'schema_version': '1.4', 'explanations': [], 'summary': [{
                    'text': 'Institutions must report activity.',
                    'source_quotes': [{'source_ref': wire['source_ref'], 'quote_id': wire['citation_passages'][0]['quote_id']}]}]},
                    ProviderUsage(10, 5, 15), 'test', 'test')
        provider = Provider()
        if budget < 4 or error_code != 'provider_output_limit':
            with pytest.raises(ProviderError):
                summarize_review(preflight, review, provider, 'offline', lambda: None, budget)
            assert provider.calls == 1
            return
        result, calls = summarize_review(preflight, review, provider, 'offline', lambda: None, budget)
    assert calls == provider.calls == 4
    assert result.usage.total_tokens == 60
    assert result.output['summary']
