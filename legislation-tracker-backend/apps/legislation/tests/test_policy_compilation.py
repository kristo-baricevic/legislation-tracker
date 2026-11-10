import pytest
from jsonschema import ValidationError


def test_grouping_keeps_every_underlying_policy_and_its_sources_exactly_once():
    from apps.legislation.enhancements.policy_compilation import resolve_policy_groups
    items = [{'title': 'Loans', 'text': 'States offer repayable housing loans.', 'source_quotes': [{'source_ref': 'src_0001', 'quote': 'Loans must be repaid.'}]},
             {'title': 'Eligibility', 'text': 'Borrowers must meet income limits.', 'source_quotes': [{'source_ref': 'src_0001', 'quote': 'Income limits apply.'}]}]
    output = {'groups': {'0': {'title': 'Loans',
        'text': 'States can offer repayable home loans to people who meet income limits.'}}}
    groups = resolve_policy_groups(output, items, [[0, 1]])
    assert len(groups) == 1
    assert [q['quote'] for q in groups[0]['source_quotes']] == ['Loans must be repaid.', 'Income limits apply.']
    with pytest.raises(ValidationError):
        resolve_policy_groups(output, items, [[0]])
    with pytest.raises(ValidationError):
        resolve_policy_groups(output, items, [[0, 0, 1]])


def test_grouping_rejects_a_dangling_conjunction_even_with_final_punctuation():
    from apps.legislation.enhancements.policy_compilation import resolve_policy_groups
    with pytest.raises(ValidationError):
        resolve_policy_groups({'groups': {'0': {'title': 'Housing', 'text': 'States offer housing loans, and.'}}},
            [{'title': 'Housing', 'source_quotes': [{'source_ref': 'src_0001', 'quote': 'Loans.'}]}], [[0]])


def test_same_program_conditions_are_grouped_before_generation_not_left_to_model():
    from types import SimpleNamespace
    from apps.legislation.enhancements.policy_compilation import section_assignments
    text = 'SEC. 1. Housing\nLoans must be repaid.\nIncome limits apply.\nSEC. 2. Tax\nA tax credit applies.'
    source = {'source_ref': 'src_0001', 'start_char': 0, 'quoted_text': text, 'discovery_source': True}
    items = [{'source_quotes': [{'source_ref': 'src_0001', 'quote': q}]} for q in ['Loans must be repaid.', 'Income limits apply.', 'A tax credit applies.']]
    assert section_assignments(SimpleNamespace(source_snapshot=[source]), items) == [[0, 1], [2]]


def test_publication_enforces_the_word_limit():
    from apps.legislation.enhancements.policy_compilation import resolve_policy_groups
    def output(words):
        return {'groups': {'0': {'title': 'Housing', 'text': ' '.join(['Help'] * words) + '.'}}}
    items = [{'title': 'Housing', 'source_quotes': []}]
    resolve_policy_groups(output(55), items, [[0]])
    with pytest.raises(ValidationError):
        resolve_policy_groups(output(56), items, [[0]])


def test_quoted_amendment_sections_do_not_split_the_enclosing_program():
    from types import SimpleNamespace
    from apps.legislation.enhancements.policy_compilation import section_assignments
    text = 'SEC. 1. Housing\nLoans are available.\n[[QUOTED_BLOCK_START]]\nSEC. 99. Income limits apply.\n[[QUOTED_BLOCK_END]]\nSEC. 2. Tax\nA credit applies.'
    split = text.index('SEC. 2.')
    sources = [{'source_ref': 'src_0001', 'start_char': 0, 'quoted_text': text[:split], 'discovery_source': True},
               {'source_ref': 'src_0002', 'start_char': split, 'quoted_text': text[split:], 'discovery_source': True}]
    items = [{'source_quotes': [{'source_ref': ref, 'quote': q}]} for ref, q in
             [('src_0001', 'Loans are available.'), ('src_0001', 'Income limits apply.'), ('src_0002', 'A credit applies.')]]
    assert section_assignments(SimpleNamespace(source_snapshot=sources), items) == [[0, 1], [2]]


def test_group_identity_cannot_shift_to_a_different_policy():
    from apps.legislation.enhancements.policy_compilation import resolve_policy_groups
    items = [{'title': 'Review air pollution standards', 'source_quotes': []}]
    with pytest.raises(ValidationError):
        resolve_policy_groups({'groups': {'0': {'title': 'Adjust tax limits', 'text': 'Tax limits change.'}}}, items, [[0]])


@pytest.mark.parametrize('text', ['The program ends after 7‑.', 'The report is due within 5年.'])
def test_grouping_rejects_clipped_words_and_mixed_language(text):
    from apps.legislation.enhancements.policy_compilation import resolve_policy_groups
    with pytest.raises(ValidationError):
        resolve_policy_groups({'groups': {'0': {'title': 'Program', 'text': text}}},
                              [{'title': 'Program', 'source_quotes': []}], [[0]])


def test_grouping_does_not_drop_an_explicit_exclusion():
    from apps.legislation.enhancements.policy_compilation import resolve_policy_groups
    items = [{'title': 'Define plant products', 'text': 'These products are excluded from plant regulator rules.', 'source_quotes': []}]
    with pytest.raises(ValidationError):
        resolve_policy_groups({'groups': {'0': {'title': 'Define plant products', 'text': 'The bill defines plant products.'}}}, items, [[0]])
    resolve_policy_groups({'groups': {'0': {'title': 'Define plant products', 'text': 'The bill defines plant products and excludes them from plant regulator rules.'}}}, items, [[0]])
