"""Public extraction/API invariants for dates, coordination, and payment schedules."""

from types import SimpleNamespace

import pytest

from apps.legislation.reader_api import financial_items_page
from apps.legislation.tests.test_reader_synopsis import extract


def output(text):
    result = extract("SEC. 1. Fees\n" + text)
    return result, SimpleNamespace(
        contract_json=result.contract_json,
        schema_version=result.schema_version,
        contract_hash="scope-regression",
    )


@pytest.mark.parametrize("date", ["May 1, 2028", "1 May 2028", "June 1, 2028"])
@pytest.mark.parametrize("wrap", [" ", "\n"])
@pytest.mark.parametrize("actor", ["no agency shall", "the Secretary shall not"])
def test_calendar_dates_do_not_override_prohibitions(date, wrap, actor):
    result, _ = output(
        f"Not later than {date}, {actor} require applicants to pay a fee of $100.".replace(
            " ", wrap
        )
    )
    assert result.contract_json["financial_items"] == []
    assert result.contract_json["orientation"]["purpose_clause"] is None


@pytest.mark.parametrize(
    "prefix", ["If an application is approved", "Unless an application is denied"]
)
@pytest.mark.parametrize("reverse", [False, True])
def test_coordinated_payments_retain_governing_condition_in_display_and_source(
    prefix, reverse
):
    parts = [
        "applicants shall pay a fee of $100",
        "renewing applicants shall pay a fee of $50",
    ]
    if reverse:
        parts.reverse()
    result, contract = output(prefix + ", " + " and ".join(parts) + ".")
    page = financial_items_page(contract, page=1, page_size=25)
    assert sorted(i["amount"] for i in page["results"]) == ["100.00", "50.00"]
    for item in result.contract_json["financial_items"]:
        assert prefix in item["display_text"]
        assert any(
            prefix in e.quoted_text
            for e in result.evidence
            if e.field_path in item["evidence_paths"]
        )


def test_shared_year_governs_each_coordinated_fee_through_api():
    _, contract = output(
        "For fiscal year 2027, applicants shall pay a fee of $100 and renewing applicants shall pay a fee of $50."
    )
    page = financial_items_page(contract, page=1, page_size=25, fiscal_year=2027)
    assert [i["amount"] for i in page["results"]] == ["100.00", "50.00"]


@pytest.mark.parametrize("first,second", [(2027, 2028), (2028, 2027)])
@pytest.mark.parametrize("connector", ["and", "or"])
@pytest.mark.parametrize("placement", ["before", "after"])
def test_each_schedule_price_keeps_its_year_in_either_word_order(
    first, second, connector, placement
):
    tail = (
        f"for fiscal year {second}, $50"
        if placement == "before"
        else f"$50 for fiscal year {second}"
    )
    _, contract = output(
        f"Applicants shall pay a fee of $100 for fiscal year {first} {connector} {tail}."
    )
    assert [
        (i["amount"], i["fiscal_years"])
        for i in contract.contract_json["financial_items"]
    ] == [("100.00", [first]), ("50.00", [second])]
    assert [
        i["amount"]
        for i in financial_items_page(
            contract, page=1, page_size=25, fiscal_year=second
        )["results"]
    ] == ["50.00"]


@pytest.mark.parametrize("modal", ["shall", "must", "may"])
@pytest.mark.parametrize("verb", ["impose", "collect"])
def test_active_surcharge_is_separate_from_fee(modal, verb):
    _, contract = output(
        f"The Secretary {modal} require applicants to pay a fee of $100 and {verb} a surcharge of $25."
    )
    assert {
        (i["financial_action"], i["amount"])
        for i in contract.contract_json["financial_items"]
    } == {("fee", "100.00"), ("surcharge", "25.00")}
    assert [
        i["amount"]
        for i in financial_items_page(
            contract, page=1, page_size=25, financial_action="surcharge"
        )["results"]
    ] == ["25.00"]


def test_implicit_negative_coordination_is_complete_source_only():
    text = (
        "The Secretary shall require a fee of $100 and not impose a surcharge of $25."
    )
    result, _ = output(text)
    assert result.contract_json["financial_items"] == []
    assert [i["display_text"] for i in result.contract_json["line_items"]] == [
        "Source text (not simplified): " + text
    ]


def test_may_date_does_not_create_a_phantom_permission_in_breakdown():
    result, _ = output(
        "Not later than May 1, 2028, the Secretary shall not require applicants to pay a fee of $100."
    )
    assert not any(
        i["kind"] == "permission" for i in result.contract_json["line_items"]
    )


def test_repeated_modal_has_independent_polarity():
    _, contract = output(
        "The Secretary shall require a fee of $100 and shall not impose a surcharge of $25."
    )
    assert [
        (i["financial_action"], i["amount"])
        for i in contract.contract_json["financial_items"]
    ] == [("fee", "100.00")]


def test_independent_spending_limit_is_not_suppressed_by_fee_evidence():
    _, contract = output(
        "The Secretary shall require a fee of $100, and the agency shall spend not more than $500 for processing."
    )
    assert {
        (i["financial_action"], i["amount"])
        for i in contract.contract_json["financial_items"]
    } == {("fee", "100.00"), ("limitation", "500.00")}


@pytest.mark.parametrize("reverse", [False, True])
def test_active_payments_are_in_source_order(reverse):
    parts = ["require a fee of $100", "impose a surcharge of $25"]
    if reverse:
        parts.reverse()
    _, contract = output("The Secretary shall " + " and ".join(parts) + ".")
    assert [i["amount"] for i in contract.contract_json["financial_items"]] == (
        ["25.00", "100.00"] if reverse else ["100.00", "25.00"]
    )
