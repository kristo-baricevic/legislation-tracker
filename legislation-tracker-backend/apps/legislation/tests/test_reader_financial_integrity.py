"""Source-derived checks must not trust the model's own coverage checklist."""
import copy

import pytest
from jsonschema import ValidationError

from apps.legislation.enhancements.reader_discovery import discovery_sources, resolve_discovery, validate_source_review


def review(amount='$10,000'):
    sources = discovery_sources('SEC. 1. School grants\nThe Secretary shall provide $10,000 for school grants.', 1)
    output = {'financial_items': [{'label': 'School grants', 'amount_display': amount,
        'text': f'Provides {amount} for school grants.', 'fiscal_years': [],
        'source_quotes': [{'source_ref': 'src_0001', 'quote_id': 'p0001'}]}],
        'additional_changes': [], 'money_checks': {'src_0001:p0001': 'financial'}}
    return sources, output


@pytest.mark.parametrize('amount', ['$1 billion', '$100', '20%'])
def test_invented_money_is_rejected_even_with_real_citation(amount):
    sources, output = review(amount)
    with pytest.raises(ValidationError):
        resolve_discovery(output, sources)


def test_explicit_grant_cannot_be_self_classified_away():
    sources, output = review()
    output['financial_items'] = []
    output['money_checks']['src_0001:p0001'] = 'not_financial'
    with pytest.raises(ValidationError):
        resolve_discovery(output, sources)


def test_citing_grant_without_reporting_its_amount_is_incomplete():
    sources, output = review()
    output['financial_items'][0].update(amount_display='No amount specified', text='Provides school grants.')
    with pytest.raises(ValidationError):
        resolve_discovery(output, sources)


def test_equivalent_dollar_notation_is_allowed():
    sources, output = review('$10 thousand')
    assert resolve_discovery(output, sources)['financial_items'][0]['amount_display'] == '$10 thousand'


def test_percentage_allocation_cannot_be_classified_away():
    sources = discovery_sources('SEC. 1. Schools\n20 percent of grant funds must go to school equipment.', 1)
    with pytest.raises(ValidationError):
        resolve_discovery({'financial_items': [], 'additional_changes': [],
            'money_checks': {'src_0001:p0001': 'not_financial'}}, sources)


def test_percentage_allocation_must_retain_its_percentage():
    sources = discovery_sources('SEC. 1. Schools\n20 percent of grant funds must go to school equipment.', 1)
    _, output = review()
    output['financial_items'][0].update(amount_display='Unspecified', text='Reserves grant funds for school equipment.')
    with pytest.raises(ValidationError):
        resolve_discovery(output, sources)


def test_financial_heading_cannot_invent_an_amount():
    sources, output = review()
    output['financial_items'][0]['label'] = '$1 billion school grant'
    with pytest.raises(ValidationError):
        resolve_discovery(output, sources)


def test_saved_nonpolicy_review_is_revalidated_not_just_citations():
    sources, output = review()
    saved = {'reviewed_sources': ['src_0001'], **resolve_discovery(output, sources)}
    forged = copy.deepcopy(saved)
    forged['financial_items'][0]['amount_display'] = '$1 billion'
    with pytest.raises(ValidationError):
        validate_source_review(forged, sources)


def test_summary_cannot_cite_a_passage_not_sent_to_provider():
    import hashlib
    from apps.legislation.enhancements.reader_citations import resolve_reader_citations
    source = {'source_ref': 'src_0001', 'quoted_text': 'Schools must report results.',
              'text_sha256': hashlib.sha256(b'Schools must report results.').hexdigest(),
              'allowed_quote_ids': []}
    output = {'schema_version': '1.4', 'explanations': [], 'summary': [{
        'text': 'Schools must report results.', 'source_quotes': [{'source_ref': 'src_0001', 'quote_id': 'p0001'}]}]}
    with pytest.raises(ValidationError):
        resolve_reader_citations(output, [], [source])
