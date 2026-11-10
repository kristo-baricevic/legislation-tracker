from pathlib import Path

import pytest
from jsonschema import ValidationError


TEXT = (Path(__file__).parent / 'fixtures/reader_evals/hr10906_119_ih.txt').read_text()


def test_policy_expectations_are_pinned_to_the_bill_not_generated_output():
    import json
    from apps.legislation.evaluation.financial_review import evaluate_policy_review
    expectations = json.loads((Path(__file__).parent / 'fixtures/financial_review/hr10906_policy_expectations.json').read_text())
    assert all(e['source_text'] in TEXT for e in expectations)
    report = evaluate_policy_review({'policy_changes': []}, expectations)
    assert not report['passed'] and len(report['failures']) == len(expectations)
    item = {'title': 'Fund housing', 'text': 'States get grants to help build homes.',
            'source_quotes': [{'quote': 'Grants for State housing finance agencies.'}]}
    case = [{'id': 'housing', 'source_text': 'State housing finance agencies', 'patterns': ['grants', 'homes']}]
    assert evaluate_policy_review({'policy_changes': [item]}, case)['passed']
    item['source_quotes'] = [{'quote': 'Unrelated source.'}]
    assert not evaluate_policy_review({'policy_changes': [item]}, case)['passed']


def test_policy_review_requires_a_complete_cited_policy_explanation():
    from apps.legislation.enhancements.reader_discovery import discovery_sources, resolve_discovery
    sources = discovery_sources('SEC. 1. Grants\nThe Secretary shall provide grants of $100 to eligible schools.', 1)
    sources[0]['policy_review'] = True
    output = {'financial_items': [{'label': 'Grants', 'amount_display': '$100',
        'text': 'Provides $100 grants to eligible schools.', 'fiscal_years': [],
        'source_quotes': [{'source_ref': 'src_0001', 'quote_id': 'p0001'}]}],
        'additional_changes': [], 'money_checks': {'src_0001:p0001': 'financial'}}
    with pytest.raises(ValidationError):
        resolve_discovery(output, sources)
    output.update(policy_changes=[{'title': 'Help schools pay for services',
        'text': 'The government must give eligible schools $100 grants.',
        'source_quotes': [{'source_ref': 'src_0001', 'quote_id': 'p0001'}]}],
        policy_checks={'src_0001:p0001': 'explained'})
    resolved = resolve_discovery(output, sources)
    assert '$100' in resolved['policy_changes'][0]['source_quotes'][0]['quote']
    output['policy_checks']['src_0001:p0001'] = 'context'
    with pytest.raises(ValidationError):
        resolve_discovery(output, sources)


@pytest.mark.parametrize('text', ['The government must give', 'Cite p0001 for the grants.',
    'Section 4 is amended by striking a comma and inserting a semicolon.'])
def test_policy_prose_rejects_clipped_sentences_citation_instructions_and_amendment_mechanics(text):
    from apps.legislation.enhancements.reader_discovery import discovery_sources, resolve_discovery
    sources = discovery_sources('SEC. 1. Grants\nSchools receive grants.', 1)
    sources[0]['policy_review'] = True
    output = {'financial_items': [], 'additional_changes': [], 'money_checks': {},
        'policy_changes': [{'title': 'Help schools', 'text': text,
            'source_quotes': [{'source_ref': 'src_0001', 'quote_id': 'p0001'}]}],
        'policy_checks': {'src_0001:p0001': 'explained'}}
    with pytest.raises(ValidationError):
        resolve_discovery(output, sources)


def test_hr10906_answer_key_is_source_pinned_and_catches_empty_money_inventory():
    import json
    from apps.legislation.evaluation.financial_review import evaluate_financial_review
    expectations = json.loads((Path(__file__).parent / 'fixtures/financial_review/hr10906_financial_expectations.json').read_text())
    assert len(expectations) == 12
    assert all(e['source_text'] in TEXT for e in expectations)
    report = evaluate_financial_review({'financial_items': []}, expectations)
    assert not report['passed']
    assert len(report['failures']) == 12


def test_financial_eval_rejects_wrong_amount_and_unrelated_citation():
    from apps.legislation.evaluation.financial_review import evaluate_financial_review
    key = [{'id': 'cap', 'source_text': 'may not exceed 35 percent', 'patterns': ['35%', 'capital cost']}]
    item = {'amount_display': '35%', 'text': 'Up to 35% of capital costs.',
            'source_quotes': [{'quote': 'Funding may not exceed 35 percent of capital costs.'}]}
    assert evaluate_financial_review({'financial_items': [item]}, key)['passed']
    item['amount_display'] = '50%'
    item['text'] = 'Up to 50% of capital costs.'
    assert not evaluate_financial_review({'financial_items': [item]}, key)['passed']
    item['text'] = 'Up to 35% of capital costs.'
    item['source_quotes'] = [{'quote': 'An unrelated grant.'}]
    assert not evaluate_financial_review({'financial_items': [item]}, key)['passed']


def test_hr10906_scan_covers_whole_source_independently_of_nlp_inventory():
    from apps.legislation.enhancements.reader_discovery import discovery_sources
    sources = discovery_sources(TEXT, 500)
    assert ''.join(s['quoted_text'] for s in sources) == TEXT
    assert len({s['source_ref'] for s in sources}) == len(sources)
    for literal in ('$85', '30 percent', '$100,000,000', '$200,000,000',
                    '$20,000,000', '$50,000,000', '35 percent', '5 percent'):
        assert any(literal in s['quoted_text'] for s in sources)


def test_discovery_cannot_silently_skip_a_money_passage():
    from apps.legislation.enhancements.reader_discovery import discovery_sources, resolve_discovery
    sources = discovery_sources('SEC. 1. Grants\nThe first grant shall be $100,000,000.', 1)
    with pytest.raises(ValidationError):
        resolve_discovery({'financial_items': [], 'additional_changes': [], 'money_checks': {}}, sources)


def test_quoted_amendment_stays_with_its_enclosing_section_and_conditions():
    from apps.legislation.enhancements.reader_discovery import discovery_sources
    sources = discovery_sources(TEXT, 1)
    timber = next(s for s in sources if 'SEC. 102.' in s['quoted_text'])
    assert 'SEC. 45BB.' in timber['quoted_text']
    assert 'multiplied by 5' in timber['quoted_text']
    assert 'prevailing wage' in timber['quoted_text'].lower()
    disaster = next(s for s in sources if 'SEC. 112.' in s['quoted_text'])
    assert 'SEC. 194B.' in disaster['quoted_text']
    assert '$1,000,000' in disaster['quoted_text']


def test_oversized_section_keeps_governing_context_without_truncation():
    from apps.legislation.enhancements.reader_discovery import discovery_sources
    text = 'SEC. 1. Grants\n' + ('A condition applies to the grant.\n' * 450)
    sources = discovery_sources(text, 1)
    assert len(sources) > 1
    assert ''.join(s['quoted_text'] for s in sources) == text
    assert all(s['section_context'] == text for s in sources)


def test_new_financial_provision_needs_no_nlp_target_and_keeps_amount_and_source():
    from apps.legislation.enhancements.reader_discovery import discovery_sources, resolve_discovery
    sources = discovery_sources('SEC. 1. Grants\nThe first grant shall be $100,000,000.', 1)
    output = {'financial_items': [{'label': 'Housing grants', 'amount_display': '$100 million',
        'text': 'Provides a $100 million first grant.', 'fiscal_years': [],
        'source_quotes': [{'source_ref': 'src_0001', 'quote_id': 'p0001'}]}],
        'additional_changes': [], 'money_checks': {'src_0001:p0001': 'financial'}}
    result = resolve_discovery(output, sources)
    assert result['financial_items'][0]['amount_display'] == '$100 million'
    assert result['financial_items'][0]['source_quotes'][0]['quote'].endswith('$100,000,000.')
    output['financial_items'][0]['source_quotes'][0]['quote_id'] = 'p9999'
    with pytest.raises(ValidationError):
        resolve_discovery(output, sources)


def test_review_cannot_omit_an_entire_source_or_a_preexisting_financial_item():
    from apps.legislation.enhancements.reader_discovery import discovery_sources, validate_source_review
    sources = discovery_sources('SEC. 1. Grants\nThe first grant shall be $100,000,000.', 1)
    review = {'financial_items': [], 'additional_changes': [], 'money_checks': {'src_0001:p0001': 'not_financial'}, 'reviewed_sources': []}
    with pytest.raises(ValidationError):
        validate_source_review(review, sources)
    review['reviewed_sources'] = ['src_0001']
    sources.append({'source_ref': 'src_0002', 'reader_targets': [{'kind': 'financial_item', 'evidence_ranges': [[0, 50]]}]})
    with pytest.raises(ValidationError):
        validate_source_review(review, sources)


def test_money_marked_financial_requires_a_returned_cited_item():
    from apps.legislation.enhancements.reader_discovery import discovery_sources, resolve_discovery
    sources = discovery_sources('SEC. 1. Grants\nThe first grant shall be $100,000,000.', 1)
    with pytest.raises(ValidationError):
        resolve_discovery({'financial_items': [], 'additional_changes': [],
                           'money_checks': {'src_0001:p0001': 'financial'}}, sources)
