"""A summary may omit the dollar figure while still asserting a funding decision."""

import pytest

from .test_provision_validation import _check_funding_statement


@pytest.mark.parametrize("path", ["reader", "provision"])
@pytest.mark.parametrize(
    "source,statement,valid",
    [
        (
            "There is authorized to be appropriated $100 for grants.",
            "The bill appropriates funds for grants.",
            False,
        ),
        (
            "There is authorized to be appropriated $100 for grants.",
            "The bill provides funding for grants.",
            False,
        ),
        (
            "There is appropriated $100 for grants.",
            "The Secretary must spend the funds for grants.",
            False,
        ),
        (
            "There is appropriated $100 for grants.",
            "The bill appropriates funds for grants.",
            True,
        ),
        (
            "There is authorized to be appropriated $100 for grants.",
            "The bill authorizes funding for grants.",
            True,
        ),
        (
            "The Secretary shall spend $100 for grants.",
            "The Secretary must spend the funds for grants.",
            True,
        ),
        (
            "There is authorized to be appropriated $100 for grants. There is appropriated $100 for salaries.",
            "The bill provides funds for grants.",
            False,
        ),
        (
            "The bill appropriates funds for grants. The filing fee is $100.",
            "The bill provides funds for grants.",
            True,
        ),
        (
            "The bill authorizes funding for grants. The filing fee is $100.",
            "The Secretary must spend funds for grants.",
            False,
        ),
        (
            "There is appropriated $100 for grants only if the governor approves.",
            "The bill appropriates funds for grants.",
            False,
        ),
        (
            "The bill authorizes funding for grants. The filing fee is $100.",
            "The bill authorizes funding for grants.",
            True,
        ),
        (
            "There is authorized to be appropriated funding for grants. The filing fee is $100.",
            "The bill authorizes funding for grants.",
            True,
        ),
        (
            "There is appropriated funding for grants. The filing fee is $100.",
            "The bill provides funds for grants.",
            True,
        ),
    ],
)
def test_funding_language_without_a_dollar_figure(path, source, statement, valid):
    condition = "only if the governor approves" if "only if" in source else None
    _check_funding_statement(path, source, statement, valid, condition)


@pytest.mark.parametrize("path", ["reader", "provision"])
@pytest.mark.parametrize("amount", ["100 dollars", "USD 100", "100 USD"])
@pytest.mark.parametrize("bound,valid", [("up to", True), ("exactly", False)])
def test_spelled_currency_preserves_amount_and_comparator(path, amount, bound, valid):
    source = "There is appropriated not more than $100 for grants."
    statement = f"The bill appropriates {bound} {amount} for grants."
    _check_funding_statement(path, source, statement, valid)
