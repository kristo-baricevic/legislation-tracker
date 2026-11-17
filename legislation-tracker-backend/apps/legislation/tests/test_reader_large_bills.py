import pytest
from django.test import override_settings

from apps.legislation.enhancements.reader_discovery import discovery_sources
from apps.legislation.enhancements.source_packet import build_enhancement_preflight
from apps.legislation.tests.test_enhancement_service import source_bill, enhancement_settings
from apps.legislation.tests.test_reader_enhancement_pipeline import install_reader


def test_large_section_context_is_bounded_and_every_source_byte_is_reviewed():
    text = 'SEC. 1. Grants\n' + ''.join(
        f'Program {i}: The Secretary shall provide grants to eligible schools.\n' for i in range(3000))
    sources = discovery_sources(text, 1)
    assert ''.join(s['quoted_text'] for s in sources) == text
    assert all(len(s.get('section_context', '').encode()) < 32000 for s in sources)
    assert all(s.get('section_context_complete') is False for s in sources)


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
                quotes = [{'source_ref': source['source_ref'], 'quote_id': p['quote_id']}
                          for p in citation_passages(source) if p['quote_id']]
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
