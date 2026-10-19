from types import SimpleNamespace

import pytest

from apps.legislation.enhancements.citations import citation_spans
from apps.legislation.enhancements.serializers import _expanded_result


@pytest.mark.parametrize('source,quote', [
    ('Funds\n   shall\tbe provided.', 'Funds shall be provided.'),
    ('An evidence-\n  based practice.', 'An evidence-based practice.'),
    ('A non-\r\n delegable duty.', 'A non-delegable duty.'),
])
def test_layout_normalization_preserves_original_span(source, quote):
    wrapped = 'Before. ' + source + ' After.'
    assert citation_spans(wrapped, quote) == [(8, 8 + len(source))]
    result = _expanded_result(SimpleNamespace(
        result_json={'overview': [{'source_refs': ['src_0001'], 'source_quotes': [
            {'source_ref': 'src_0001', 'quote': quote}]}]},
        source_snapshot_json=[{'source_ref': 'src_0001', 'quoted_text': wrapped, 'start_char': 100}],
    ))
    citation = result['overview'][0]['cited_sources'][0]
    assert citation['quoted_text'] == source
    assert citation['start_char'] == 108
    assert citation['end_char'] == 108 + len(source)


@pytest.mark.parametrize('source,quote', [
    ('shall provide $100', 'may provide $100'),
    ('shall provide $100', 'shall provide $1000'),
    ('evidence-based', 'evidencebased'),
    ('non- delegable', 'non-delegable'),
    ('10-\n5', '10-5'),
    ('Funds provided', 'funds provided'),
    ('first sentence. second sentence.', 'first sentence second sentence'),
    ('anything', '  '),
])
def test_meaning_and_punctuation_are_not_normalized(source, quote):
    assert citation_spans(source, quote) == []


def test_repeated_normalized_and_overlapping_matches_are_ambiguous():
    assert len(citation_spans('Funds provided. Funds\nprovided.', 'Funds provided.')) == 2
    assert len(citation_spans('aaaa', 'aaa')) == 2
