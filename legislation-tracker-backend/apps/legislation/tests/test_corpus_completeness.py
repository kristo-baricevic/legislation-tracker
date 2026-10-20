from apps.legislation.tests.test_reader_synopsis import extract
import pytest


@pytest.mark.parametrize('source, required', [
    ('It is the sense of Congress that—\n(1) the program is beneficial; and\n(2) States should support participation.', 'States should'),
    ('Notwithstanding any other provision of law, no Federal funds are authorized to be appropriated to support—\n(1) participation in the proceeding; or\n(2) reconstitution of the group.', 'reconstitution'),
    ('The activities are hereby designated as being categorically excluded from preparation of an environmental assessment under section 102.', 'categorically excluded'),
    ('During a lapse in appropriations, a State agency shall, after the conclusion of that period, be eligible for reimbursement of State funds used to maintain WIC participation.', 'after the conclusion'),
    ('With respect to any covered project, the State is encouraged to choose to participate in the environmental review process.', 'is encouraged'),
])
def test_unsimplified_policy_and_eligibility_rules_are_not_discarded(source, required):
    result = extract('SEC. 1. Provision\n' + source)
    assert any(required in x['display_text'] for x in result.contract_json['line_items'])
    assert 'reader_uncertain_clause' in result.contract_json['extraction']['warnings']


def test_long_official_title_does_not_reject_analysis():
    from types import SimpleNamespace
    from django.test import override_settings
    from apps.legislation.extraction.service import extract_contract
    title = 'To require the Administrator to report on safety. ' * 12
    with override_settings(LEGAL_NLP_V21_WRITE_ENABLED=True):
        result = extract_contract(bill=SimpleNamespace(title=title, jurisdiction='federal'),
            document=SimpleNamespace(extracted_text='SEC. 1. Report\nThe Administrator shall report annually.', version_label='Introduced'))
    assert result.fallback_reason is None
    assert result.contract_json['title'] == title


def test_tax_on_transfer_is_not_an_instruction_to_transfer_funds():
    text = ('SEC. 1. Taxes\nThere is hereby imposed on any amount transferred pursuant to an improper conduit arrangement a tax equal to 20 percent of the amount so transferred, unless the transfer was due to reasonable cause.')
    result = extract(text)
    money = result.contract_json['financial_items']
    assert len(money) == 1
    assert money[0]['financial_action'] == 'source_rule'
    assert '20 percent' in money[0]['display_text']
    assert 'unless' in money[0]['display_text']
    assert money[0]['amount'] is None


def test_statutes_at_large_citation_does_not_split_amendment():
    result = extract('SEC. 1. Reauthorization\nSection 9 of the Fort Peck Reservation Rural Water System Act of 2000 (Public Law 106–382; 114 Stat. 1457; 123 Stat. 2856) is amended, in each of subsections (a)(1) and (b), by striking 2026 and inserting 2028.')
    assert any('2026' in x['display_text'] and '2028' in x['display_text'] for x in result.contract_json['line_items'])


def test_named_act_repeal_keeps_restoration_effect():
    result = extract('SEC. 1. Repeal\nThe Second Chance Amendment Act of 2022 (D.C. Law 24–284) is hereby repealed, and any provision of law amended or repealed by such Act is restored or revived as if such Act had not been enacted into law.')
    assert any('is hereby repealed' in x['display_text'] and 'restored or revived' in x['display_text'] for x in result.contract_json['line_items'])


def test_uncertain_group_is_retained_even_without_simplifiable_claims():
    text = ('SEC. 1. Definition\nFor purposes of Federal securities laws, an issuer shall be a well-known seasoned issuer if—\n(1) the aggregate market value is $75,000,000 or more; and\n(2) the issuer otherwise satisfies the applicable requirements.')
    result = extract(text)
    assert any('$75,000,000' in x['display_text'] and 'otherwise satisfies' in x['display_text'] for x in result.contract_json['line_items'])


def test_nested_amendment_locator_inherits_actual_target():
    result = extract('SEC. 1. Update\nSection 354 of the Public Health Service Act is amended—\n(1) in subparagraph (D)—\n(A) in the matter preceding clause (i), by striking physician who and inserting physician or an AI system that.')
    assert any('physician who' in x['display_text'] and 'AI system' in x['display_text'] for x in result.contract_json['line_items'])


def test_unquoted_year_amendment_is_a_reader_change():
    r = extract('SEC. 1. Extension\nSection 101 of division JJ of the Consolidated Appropriations Act, 2023 (16 U.S.C. 1387 note) is amended by striking 2028 each place it appears and inserting 2035.')
    assert any('2028' in x['display_text'] and '2035' in x['display_text'] for x in r.contract_json['line_items'])


def test_nested_penalty_amendment_is_in_money_without_becoming_an_appropriation():
    r = extract('SEC. 1. Civil penalties\n(a) In general.—Section 1760(c)(1)(A) of the Export Control Reform Act of 2018 is amended—\n(1) by striking $300,000 and inserting $1,200,000; and\n(2) by striking twice the value of the transaction and inserting four times the value of the transaction.')
    items = r.contract_json['financial_items']
    assert len(items) == 1
    assert '$300,000' in items[0]['display_text'] and '$1,200,000' in items[0]['display_text']
    assert items[0]['financial_action'] != 'appropriation'
    assert any('twice' in i['display_text'] and 'four times' in i['display_text'] for i in r.contract_json['line_items'])


def test_funding_reauthorization_preserves_amount_and_both_periods():
    r = extract('SEC. 1. Reauthorization\nSection 399Z–1(m) of the Public Health Service Act (42 U.S.C. 280h–5(m)) is amended by striking such sums as may be necessary for each of the fiscal years 2022 through 2026 and inserting $55,000,000 for each of fiscal years 2027 through 2031.')
    items = r.contract_json['financial_items']
    assert len(items) == 1
    for text in ['$55,000,000', '2022 through 2026', '2027 through 2031']:
        assert text in items[0]['display_text']


def test_nested_penalty_formula_preserves_greater_of_not_just_flat_amount():
    r = extract('SEC. 4. Enforcement\n(a) Civil penalty.—The Secretary shall assess a civil penalty for each violation in an amount not less than the greater of—\n(1) $1,500,000; or\n(2) five times the value of the transaction.')
    items = r.contract_json['financial_items']
    assert len(items) == 1
    assert 'greater of' in items[0]['display_text']
    assert '$1,500,000' in items[0]['display_text']
    assert 'five times' in items[0]['display_text']


def test_complex_effective_date_is_in_timeline_without_inventing_calendar_date():
    r = extract('SEC. 2. Effective date\nThe amendments made by this section shall take effect on the first day of the first month beginning after the date of the enactment of this Act and shall apply to payments for months beginning on or after that date.')
    items = r.contract_json['timeline_items']
    assert len(items) == 1
    assert 'first day of the first month' in items[0]['display_text']
    assert items[0]['date'] is None


def test_source_supplement_does_not_publish_deleted_quoted_money():
    r = extract('SEC. 1. Repeal\nThe Secretary shall report annually.\nSection 2 is amended by striking the following:\n[[QUOTED_BLOCK_START]]\nSEC. 2. Penalties\nThe Secretary shall impose a penalty of $500.\n[[QUOTED_BLOCK_END]]')
    assert not r.contract_json['financial_items']


def test_unparsed_deadline_is_not_labeled_as_effective_date():
    r = extract('SEC. 1. Report\nThe Secretary shall report not later than the first Monday after the program closes.')
    items = r.contract_json['timeline_items']
    assert len(items) == 1
    assert items[0]['timeline_type'] == 'relative'
    assert 'first Monday' in items[0]['display_text']


def test_source_financial_rule_can_be_requested_by_public_filter():
    from apps.legislation.serializers import FinancialItemsQuerySerializer
    query = FinancialItemsQuerySerializer(data={'financial_action': 'source_rule'})
    assert query.is_valid(), query.errors


def test_proportional_grant_reduction_keeps_eligibility_condition():
    result = extract('SEC. 1. Grant reductions\nIn any case in which an eligible recipient attends on less than a full-time basis, the amount of a grant shall be reduced in proportion to the degree to which the recipient is not attending on a full-time basis, in accordance with a schedule established by the Secretary.')
    items = result.contract_json['financial_items']
    assert len(items) == 1
    assert 'less than a full-time basis' in items[0]['display_text']
    assert 'reduced in proportion' in items[0]['display_text']
    assert items[0]['amount'] is None


def test_deep_eligibility_hierarchy_keeps_gpa_alternative_with_parent():
    text = ('SEC. 1. Eligibility\n(a) Applications\n(1) Demonstration\n(A) Each application shall demonstrate that—\n'
        '(i) if the applicant is enrolled—\n(I) the applicant is eligible; and\n(II) the applicant—\n'
        '(aa) has a grade point average of 3.25; or\n(bb) scored above the 75th percentile; and\n'
        '(ii) the applicant has an educational plan.')
    from apps.legislation.extraction.federal_structure import parse_federal_structure
    sections = parse_federal_structure(text)
    gpa = next(s for s in sections if s.label == '(aa)')
    assert [p.label for p in gpa.path][-4:] == ['(A)', '(i)', '(II)', '(aa)']
    result = extract(text)
    lines = [x['display_text'] for x in result.contract_json['line_items']]
    assert any('3.25' in x and '75th' in x and 'educational plan' in x for x in lines)


def test_parent_index_matches_containment_without_rescanning_document():
    from apps.legislation.extraction.federal_structure import parse_federal_structure
    from apps.legislation.extraction.federal_clauses import _parent_section
    from apps.legislation.extraction.financial_rules import _parent_section as money_parent
    source = '\n'.join(f'SEC. {i}. Test\n(a) Duty\n(1) The Secretary shall report.\n(2) A second duty.' for i in range(1, 101))
    sections = parse_federal_structure(source)
    legacy = list(sections)
    class IndexedOnly:
        parents = sections.parents
        def __iter__(self):
            raise AssertionError('Parent lookup must not scan all sections')
    for section in sections:
        expected = _parent_section(section, legacy)
        assert _parent_section(section, IndexedOnly()) == expected
        assert money_parent(section, IndexedOnly()) == expected
