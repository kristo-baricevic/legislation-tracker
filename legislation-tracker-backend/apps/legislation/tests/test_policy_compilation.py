def test_same_program_conditions_are_grouped_before_generation_not_left_to_model():
    from types import SimpleNamespace
    from apps.legislation.enhancements.policy_compilation import section_assignments
    text = 'SEC. 1. Housing\nLoans must be repaid.\nIncome limits apply.\nSEC. 2. Tax\nA tax credit applies.'
    source = {'source_ref': 'src_0001', 'start_char': 0, 'quoted_text': text, 'discovery_source': True}
    items = [{'source_quotes': [{'source_ref': 'src_0001', 'quote': q}]} for q in ['Loans must be repaid.', 'Income limits apply.', 'A tax credit applies.']]
    assert section_assignments(SimpleNamespace(source_snapshot=[source]), items) == [[0, 1], [2]]


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
