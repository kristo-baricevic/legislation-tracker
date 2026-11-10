from dataclasses import replace
from types import SimpleNamespace

from apps.legislation.enhancements.reader_targets import snapshot_targets


def test_small_items_have_smaller_output_estimates_than_complex_items():
    from apps.legislation.enhancements.reader_sizing import target_output_bytes
    small = {'kind': 'line_item', 'original_text': 'Publish a report.', 'facts': {}, 'evidence_ranges': [[0, 17]]}
    large = {**small, 'kind': 'financial_item', 'original_text': 'Conditions and amounts. ' * 90, 'evidence_ranges': [[0, 2000]]}
    assert target_output_bytes(large) > target_output_bytes(small) * 2


def test_size_split_keeps_entire_source_context_and_all_targets_once():
    from apps.legislation.enhancements.reader_sizing import split_reader_request
    from apps.legislation.enhancements.types import EnhancementPreflight
    targets = [{'target_id': str(i), 'kind': 'line_item', 'original_text': 'word ' * length, 'facts': {}, 'evidence_ranges': [[0, 20]]} for i, length in enumerate([200, 10, 10, 10])]
    sources = [{'source_ref': 'src_0001', 'quoted_text': 'The Secretary shall publish a report.', 'start_char': 0, 'end_char': 36, 'reader_targets': targets}]
    p = EnhancementPreflight('openai', 'test', 'none', 'test', '1.4', 'test', 'hash', 'hash', {}, sources,
        {'source_packet': {'sources': [], 'target_citations': []}, 'max_output_tokens': 8000}, b'', 0, False)
    halves = split_reader_request(p)
    assert len(halves) == 2
    assert [len(snapshot_targets(h.source_snapshot)) for h in halves] == [1, 3]
    assert [t['target_id'] for h in halves for t in snapshot_targets(h.source_snapshot)] == ['0', '1', '2', '3']
    assert all(h.source_snapshot[0]['quoted_text'] == sources[0]['quoted_text'] for h in halves)


def test_source_review_split_assigns_each_passage_once_without_losing_context():
    from apps.legislation.enhancements.reader_sizing import split_reader_request
    from apps.legislation.enhancements.reader_discovery import money_candidates
    from apps.legislation.enhancements.reader_citations import citation_passages
    from apps.legislation.enhancements.types import EnhancementPreflight
    text = ''.join(f'Section {i}: $100 is authorized for program {i}. ' * 8 + '\n' for i in range(8))
    source = {'source_ref': 'src_0001', 'quoted_text': text, 'start_char': 0,
              'end_char': len(text), 'discovery_source': True}
    p = EnhancementPreflight('openai', 'test', 'none', 'test', '1.4', 'test', 'hash', 'hash', {}, [source],
        {'source_review': True, 'instructions': 'Review sources.', 'source_packet': {'sources': []},
         'max_output_tokens': 8000}, b'', 0, False)
    halves = split_reader_request(p)
    assert len(halves) == 2
    assigned = [q for h in halves for q in h.source_snapshot[0]['review_quote_ids']]
    assert assigned == [q['quote_id'] for q in citation_passages(source) if q['quote_id']]
    assert len(assigned) == len(set(assigned))
    assert all(h.source_snapshot[0]['quoted_text'] == text for h in halves)
    assert set(money_candidates([source])) == set(q for h in halves for q in money_candidates(h.source_snapshot))
    grandchildren = split_reader_request(halves[0])
    assert [q for h in grandchildren for q in h.source_snapshot[0]['review_quote_ids']] == halves[0].source_snapshot[0]['review_quote_ids']
