import pytest

from apps.legislation.tests.test_reader_synopsis import extract


@pytest.mark.parametrize("cap", ["must not exceed", "shall not exceed"])
def test_cap_does_not_cancel_unrelated_relative_scope(cap):
    text = f"The Secretary shall review a program which provides that applicants shall pay a fee that {cap} $100."
    c = extract("SEC. 1. Fees\n" + text).contract_json
    assert c["financial_items"] == []
    assert c["orientation"]["purpose_clause"] is None
    assert [i["display_text"] for i in c["line_items"]] == [
        "Source text (not simplified): " + text
    ]


@pytest.mark.parametrize("first,second", [(2027, 2028), (2028, 2027)])
def test_each_fee_retains_its_own_year_and_api_filter(first, second):
    from types import SimpleNamespace

    from apps.legislation.reader_api import financial_items_page

    result = extract(
        f"SEC. 1. Fees\nApplicants shall pay a fee of $100 for fiscal year {first} and $50 for fiscal year {second}."
    )
    c = result.contract_json
    assert [(i["amount"], i["fiscal_years"]) for i in c["financial_items"]] == [
        ("100.00", [first]),
        ("50.00", [second]),
    ]
    contract = SimpleNamespace(
        contract_json=c, schema_version=result.schema_version, contract_hash="test"
    )
    page = financial_items_page(contract, page=1, page_size=25, fiscal_year=second)
    assert [i["amount"] for i in page["results"]] == ["50.00"]


@pytest.mark.parametrize("reverse", [False, True])
def test_uncertain_condition_preserves_complete_governing_provision(reverse):
    conditions = [
        "are citizens",
        "hold a permit which may be renewed and shall expire after one year",
    ]
    if reverse:
        conditions.reverse()
    text = f"Applicants shall pay a fee of $100 if they—\n(1) {conditions[0]}; and\n(2) {conditions[1]}."
    result = extract("SEC. 1. Fees\n" + text)
    c = result.contract_json
    assert c["financial_items"] == []
    assert [i["display_text"] for i in c["line_items"]] == [
        "Source text (not simplified): " + text
    ]
    assert any(e.quoted_text == text for e in result.evidence)
