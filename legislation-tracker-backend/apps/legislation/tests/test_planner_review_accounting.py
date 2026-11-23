from types import SimpleNamespace

import pytest
from django.core.management.base import CommandError


def test_xml_audit_counts_owned_passages_not_repeated_context():
    from apps.legislation.management.commands.benchmark_source_planner import verify_review_ownership
    from apps.legislation.enhancements.reader_citations import citation_passages
    text = ' '.join(f'Program {i} must report its results to Congress.' for i in range(80))
    source = {'source_ref': 'src_0001', 'quoted_text': text,
              'start_char': 0, 'end_char': len(text), 'discovery_source': True}
    ids = [p['quote_id'] for p in citation_passages(source) if p['quote_id']]
    assert len(ids) >= 2
    reviews = [SimpleNamespace(source_snapshot=[{**source, 'review_quote_ids': [qid]}]) for qid in ids]
    verify_review_ownership([source], reviews)
    verify_review_ownership([source], reviews[1:], {'policy_checks': {f'src_0001:{ids[0]}': 'explained'}})
    with pytest.raises(CommandError):
        verify_review_ownership([source], reviews[:-1])
    with pytest.raises(CommandError):
        verify_review_ownership([source], reviews + reviews[:1])
