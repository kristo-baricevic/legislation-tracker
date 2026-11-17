from copy import deepcopy
from types import SimpleNamespace
import pytest
from jsonschema import ValidationError


def test_publication_rejects_changed_meaning_and_saved_reader_uses_original_drafts():
    from apps.legislation.enhancements.reader_discovery import discovery_sources, resolve_discovery, validate_source_review
    from apps.legislation.enhancements.serializers import _expanded_result
    sources = discovery_sources('SEC. 1. Schools\nThe Secretary may provide services to eligible schools. Schools must report annually.', 1)
    sources[0]['policy_review'] = True
    review = resolve_discovery({'financial_items': [], 'additional_changes': [], 'money_checks': {},
        'policy_checks': {'src_0001:p0001':'explained'}, 'policy_changes': [{'title':'School services',
        'text':'The Secretary may provide services to eligible schools. Schools must report annually.',
        'source_quotes':[{'source_ref':'src_0001','quote_id':'p0001'}]}]}, sources)
    review['reviewed_sources'] = ['src_0001']
    review['policy_drafts'] = deepcopy(review['policy_changes'])
    review['policy_changes'][0]['text'] = 'The Secretary must provide services to every school.'
    with pytest.raises(ValidationError):
        validate_source_review(review, sources)
    saved = SimpleNamespace(result_json={'schema_version':'1.4', 'explanations':[], 'source_review':review},
        source_snapshot_json=sources, source_manifest_json=dict(document_id=1,document_content_hash='a',contract_id=1,contract_hash='b'))
    expanded = _expanded_result(saved)
    assert expanded['source_review']['policy_changes'][0]['text'] == 'The Secretary may provide services to eligible schools. Schools must report annually.'
    assert saved.result_json['source_review']['policy_changes'][0]['text'] == 'The Secretary must provide services to every school.'
    assert 'policy_drafts' not in expanded['source_review']


def test_grouping_preserves_permission_eligibility_and_reporting_exactly():
    from apps.legislation.enhancements.policy_compilation import group_policy_drafts
    text = 'SEC. 1. Schools\nThe Secretary may provide services to eligible schools.\nSchools must submit an annual report.'
    sources = [{'source_ref': 'src_0001', 'discovery_source': True, 'start_char': 0, 'quoted_text': text}]
    drafts = [
        {'title': 'Help schools', 'text': 'The Secretary may provide services to eligible schools.',
         'source_quotes': [{'source_ref': 'src_0001', 'quote': 'The Secretary may provide services to eligible schools.'}]},
        {'title': 'Help schools', 'text': 'Schools must submit an annual report.',
         'source_quotes': [{'source_ref': 'src_0001', 'quote': 'Schools must submit an annual report.'}]},
    ]
    original = deepcopy(drafts)
    result = group_policy_drafts(SimpleNamespace(source_snapshot=sources), drafts)
    assert result == [{'title': 'Help schools',
        'text': 'The Secretary may provide services to eligible schools. Schools must submit an annual report.',
        'source_quotes': [*drafts[0]['source_quotes'], *drafts[1]['source_quotes']]}]
    assert drafts == original
    # A title can supply the actor or scope missing from its short body.
    drafts[1]['title'] = 'Private schools only'
    assert group_policy_drafts(SimpleNamespace(source_snapshot=sources), drafts) == drafts


def test_long_group_keeps_every_draft_instead_of_truncating_conditions():
    from apps.legislation.enhancements.policy_compilation import group_policy_drafts
    source = {'source_ref': 'src_0001', 'discovery_source': True, 'start_char': 0,
              'quoted_text': 'SEC. 1. Schools\nSchools may apply. Schools must report.'}
    drafts = [{'title': title, 'text': ('Eligible schools may apply for assistance. ' * 8).strip(),
               'source_quotes': [{'source_ref':'src_0001', 'quote': quote}]} for title, quote in
              [('Eligibility', 'Schools may apply.'), ('Reporting', 'Schools must report.')]]
    result = group_policy_drafts(SimpleNamespace(source_snapshot=[source]), drafts)
    assert result == drafts


def test_different_sections_do_not_merge_and_empty_review_is_safe():
    from apps.legislation.enhancements.policy_compilation import group_policy_drafts
    source = {'source_ref': 'src_0001', 'discovery_source': True, 'start_char': 0,
              'quoted_text': 'SEC. 1. Schools\nSchools may apply.\nSEC. 2. Reporting\nSchools must report.'}
    drafts = [{'title': title, 'text': quote, 'source_quotes': [{'source_ref':'src_0001', 'quote': quote}]}
              for title, quote in [('Eligibility', 'Schools may apply.'), ('Reporting', 'Schools must report.')]]
    request = SimpleNamespace(source_snapshot=[source])
    assert group_policy_drafts(request, drafts) == drafts
    assert group_policy_drafts(request, []) == []
