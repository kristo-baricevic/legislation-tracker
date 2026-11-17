"""Historical audit probes for base commit 1636fa2, NOT release regressions.

These reproduce the pre-fix defects and intentionally fail on the repaired code.
Current regression coverage lives in apps/legislation/tests/test_reader_*.
"""
import copy
import json
from types import SimpleNamespace
import pytest
from django.test import override_settings
from apps.legislation.enhancements.reader_discovery import discovery_sources, resolve_discovery, validate_source_review, policy_passages, money_candidates
from apps.legislation.enhancements.reader_citations import citation_passages
from apps.legislation.enhancements.reader_sizing import split_reader_request
from apps.legislation.enhancements.source_packet import build_enhancement_preflight, PreflightUnavailable, canonical_json_bytes
from apps.legislation.tests.test_enhancement_service import source_bill, enhancement_settings
from apps.legislation.tests.test_reader_enhancement_pipeline import install_reader


def test_oversized_section_repeated_in_every_chunk():
    text = 'SEC. 1. Grants\n' + ('The Secretary shall provide grants to eligible schools.\n' * 3000)
    sources = discovery_sources(text, 1)
    contexts = sum(len(s.get('section_context', '').encode()) for s in sources)
    print('OVERSIZED_CONTEXT', json.dumps({'text_bytes': len(text.encode()), 'chunks': len(sources), 'context_bytes_across_calls': contexts, 'max_context_bytes': max(len(s.get('section_context', '').encode()) for s in sources)}))
    assert max(len(s.get('section_context', '').encode()) for s in sources) > 120000


def one_source():
    source = discovery_sources('SEC. 1. School grants\nThe Secretary shall provide $10,000 for school grants.', 1)[0]
    source['policy_review'] = True
    return source


def test_wrong_amount_with_real_citation_is_accepted():
    source = one_source()
    quote = {'source_ref': source['source_ref'], 'quote_id': next(p['quote_id'] for p in citation_passages(source) if p['quote_id'])}
    output = {'financial_items': [{'label': 'School grants', 'amount_display': '$1 billion',
        'text': 'Provides $1 billion for school grants.', 'fiscal_years': [], 'source_quotes': [quote]}],
        'additional_changes': [], 'money_checks': {k: 'financial' for k in money_candidates([source])},
        'policy_changes': [{'title': 'Fund schools', 'text': 'The government must provide $1 billion for school grants.', 'source_quotes': [quote]}],
        'policy_checks': {k: 'explained' for k in policy_passages([source])}}
    valid = resolve_discovery(output, [source])
    review = {'reviewed_sources': [source['source_ref']], **valid}
    validate_source_review(review, [source])
    from apps.legislation.enhancements.schema import validate_enhancement_output
    validate_enhancement_output({'schema_version': '1.4', 'summary': [{'text': 'Provides school grants.',
        'source_quotes': valid['financial_items'][0]['source_quotes']}], 'explanations': [],
        'source_review': review}, [source], expected_version='1.4')
    assert valid['financial_items'][0]['amount_display'] == '$1 billion'
    print('WRONG_AMOUNT_ACCEPTED', 'Source $10,000, explanation $1 billion; both discovery and stored-review validators accepted')


def test_money_omission_self_classification_is_accepted():
    source = one_source()
    output = {'financial_items': [], 'additional_changes': [], 'policy_changes': [],
        'money_checks': {k: 'not_financial' for k in money_candidates([source])},
        'policy_checks': {k: 'context' for k in policy_passages([source])}}
    valid = resolve_discovery(output, [source])
    validate_source_review({'reviewed_sources': [source['source_ref']], **valid}, [source])
    print('MISSING_MONEY_ACCEPTED', 'Explicit $10,000 grant omitted when NLP inventory is empty')


@pytest.mark.django_db
def test_long_bill_rejected_before_any_call(source_bill, enhancement_settings):
    install_reader(source_bill, count=0)
    doc = source_bill.documents.get()
    doc.extracted_text = ''.join(f'SEC. {i}. Program {i}\n' + ('The Secretary shall provide school grants to eligible students.\n' * 95) for i in range(1, 71))
    doc.save()
    with enhancement_settings, override_settings(LLM_READER_MAX_CALLS=64):
        with pytest.raises(PreflightUnavailable) as failure:
            build_enhancement_preflight(source_bill)
    print('LARGE_BILL_PREFLIGHT', len(doc.extracted_text), failure.value.reason, str(failure.value))
    assert 'call budget' in str(failure.value)


@pytest.mark.django_db
def test_summary_sees_only_subset_before_full_source_review(source_bill, enhancement_settings):
    install_reader(source_bill, count=0)
    doc = source_bill.documents.get()
    doc.extracted_text = ''.join(f'SEC. {i}. Program {i}\n' + ('The Secretary shall provide school grants to eligible students.\n' * 95) for i in range(1, 31))
    doc.save()
    with enhancement_settings:
        p = build_enhancement_preflight(source_bill)
    main_sources = p.request_envelope['source_packet']['sources']
    refs = {s['source_ref'] for s in main_sources}
    main_bytes = sum(len(s['quoted_text'].encode()) for s in p.source_snapshot if s['source_ref'] in refs)
    print('SUMMARY_COVERAGE', json.dumps({'document_chars': len(doc.extracted_text), 'summary_source_bytes': main_bytes,
        'summary_truncated': p.truncated, 'calls': p.source_manifest['budget']['planned_calls']}))
    assert p.truncated and main_bytes < len(doc.extracted_text)


@pytest.mark.django_db
def test_real_hr10906_plan_cost_shape(source_bill, enhancement_settings):
    from pathlib import Path
    import time
    from apps.legislation.extraction.service import extract_contract
    from apps.legislation.models import EvidenceSpan, BillContract
    from apps.legislation.contract_json import contract_hash_from_dict
    doc = source_bill.documents.get()
    doc.extracted_text = Path('apps/legislation/tests/fixtures/reader_evals/hr10906_119_ih.txt').read_text()
    doc.save()
    with override_settings(LEGAL_NLP_V21_WRITE_ENABLED=True):
        result = extract_contract(document=doc, bill=source_bill)
    c = BillContract.objects.create(bill=source_bill, document=doc, schema_version=result.schema_version,
        contract_hash=contract_hash_from_dict(result.contract_json), contract_json=result.contract_json)
    EvidenceSpan.objects.bulk_create([EvidenceSpan(bill=source_bill, document=doc, contract=c,
        field_path=e.field_path, start_char=e.start_char, end_char=e.end_char, quoted_text=e.quoted_text) for e in result.evidence])
    source_bill.latest_contract = c
    source_bill.save()
    with enhancement_settings, override_settings(LLM_READER_MAX_CALLS=64):
        start = time.monotonic()
        p = build_enhancement_preflight(source_bill)
        seconds = time.monotonic() - start
    print('HR10906_PLAN', json.dumps({'source_bytes': len(doc.extracted_text.encode()), 'preflight_seconds': round(seconds,3),
        'planned_calls': p.source_manifest['budget']['planned_calls'], 'maximum_calls': p.source_manifest['budget']['maximum_calls'],
        'request_bytes_before_retry_reserve': len(canonical_json_bytes(p.request_envelope)) + sum(len(r.request_bytes) for r in p.reader_batches),
        'maximum_output_tokens': p.source_manifest['budget']['maximum_output']}))
