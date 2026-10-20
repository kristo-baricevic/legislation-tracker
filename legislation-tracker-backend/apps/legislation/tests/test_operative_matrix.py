"""Consumer-level invariants over wording, order and structural variants."""

import pytest

from apps.legislation.tests.test_reader_synopsis import extract


def test_container_does_not_spread_definition_uncertainty_into_other_sections():
    source = """TITLE I Worker protection
SEC. 100. Definitions
In this title:
(1) Employer.—An employer means an entity that shall report whether workers may qualify.
SEC. 101. Funding
There is appropriated $100,000 for worker advocacy services.
"""
    result = extract(source).contract_json
    assert [(i["financial_action"], i["amount"]) for i in result["financial_items"]] == [
        ("appropriation", "100000.00")
    ]


def test_allotment_minimum_retains_governing_threshold_and_recipient():
    source = """SEC. 433. Allotments and payments
(a) Allotments.—
(1) Minimum allotments.—In any case in which—
(A) the total amount appropriated for a fiscal year is not less than $20,000,000, the allotment for such fiscal year—
(i) to each of American Samoa and Guam may not be less than $100,000; and
(ii) to any other State may not be less than $200,000.
"""
    result = extract(source).contract_json
    items = result["financial_items"]
    assert {"100000.00", "200000.00"} <= {i["amount"] for i in items}
    for item in items:
        if item["amount"] in {"100000.00", "200000.00"}:
            assert "$20,000,000" in item["display_text"]
            assert "not less than" in item["display_text"]
            assert ("American Samoa" if item["amount"] == "100000.00" else "other State") in item["display_text"]


def test_conditional_technical_assistance_percentage_keeps_threshold():
    source = """SEC. 433. Allotments
(a) Technical assistance.—In any case in which the total amount appropriated for a fiscal year is more than $24,500,000, the Secretary shall—
(1) use not more than 2 percent of the amount appropriated to provide technical assistance to qualifying systems; and
(2) provide a grant to an American Indian consortium.
SEC. 436. Authorization
There are authorized to be appropriated for allotments under section 433 such sums as may be necessary.
"""
    items = extract(source).contract_json["financial_items"]
    percentage = next(i for i in items if i["amount"] == "2.00")
    assert "more than $24,500,000" in percentage["display_text"]
    assert "of the amount appropriated" in percentage["display_text"]
    assert any(i["financial_action"] == "authorization" and i["amount_type"] == "such_sums" for i in items)


@pytest.mark.parametrize(
    "prefix",
    [
        "",
        "Not later than 180 days after enactment, ",
        "No later than January 1, 2028, ",
    ],
)
@pytest.mark.parametrize("actor", ["An applicant", "An applicant who is not a minor"])
@pytest.mark.parametrize("price", ["a fee of $100", "a $100 application fee"])
def test_conditions_do_not_negate_payment(prefix, actor, price):
    c = extract(f"SEC. 1. Fees\n{prefix}{actor} shall pay {price}.").contract_json
    assert [(i["financial_action"], i["amount"]) for i in c["financial_items"]] == [
        ("fee", "100.00")
    ]


@pytest.mark.parametrize("actor", ["the agency", "the U.S. Government"])
@pytest.mark.parametrize("separator", [" ", "\n"])
def test_reporting_does_not_create_a_program(actor, separator):
    c = extract(
        "SEC. 1. Grants\nThe Secretary shall report whether "
        + actor
        + separator
        + "shall establish a program to award grants to eligible nonprofit organizations to assist eligible applicants."
    ).contract_json
    assert c["orientation"]["purpose_clause"] is None


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("price", ["a fee of $100", "a $100 application fee"])
@pytest.mark.parametrize("separator", [" ", "\n"])
def test_each_mixed_payment_has_its_own_amount(reverse, price, separator):
    parts = [
        f"Applicants shall pay {price}",
        "a surcharge of $25" + separator + "shall" + separator + "be imposed",
    ]
    if reverse:
        parts.reverse()
    items = extract("SEC. 1. Fees\n" + ", and ".join(parts) + ".").contract_json[
        "financial_items"
    ]
    assert sorted((i["financial_action"], i["amount"]) for i in items) == [
        ("fee", "100.00"),
        ("surcharge", "25.00"),
    ]


def test_fee_and_its_exemption_are_both_available():
    items = extract(
        "SEC. 1. Fees\nApplicants shall pay a fee of $100, but a minor may be exempted from paying the fee."
    ).contract_json["financial_items"]
    assert {(i["financial_action"], i["amount"]) for i in items} == {
        ("fee", "100.00"),
        ("fee_exemption", None),
    }


@pytest.mark.parametrize("separator", [" ", "\n"])
@pytest.mark.parametrize("prefix", ["", "Not later than 180 days after enactment, "])
def test_affirmative_program_is_preserved_with_deadlines_and_wrapping(
    separator, prefix
):
    text = (
        "SEC. 1. Grants\n"
        + prefix
        + "The Secretary shall establish a program to award grants to eligible nonprofit organizations to assist eligible applicants."
    )
    text = text.replace("shall establish", "shall" + separator + "establish")
    assert (
        "Creates a grant program"
        in extract(text).contract_json["orientation"]["purpose_clause"]
    )


def test_parent_reporting_scope_prevents_child_fee_claims():
    text = "SEC. 1. Reports\nThe Secretary shall report whether—\n(1) applicants shall pay a fee of $100; and\n(2) a surcharge of $25 shall be imposed."
    assert extract(text).contract_json["financial_items"] == []


def test_explicit_parent_price_is_not_lost_when_it_has_conditions():
    text = "SEC. 1. Fees\nAn applicant shall pay a fee of $100 if the applicant—\n(1) applies for a permit; and\n(2) requests expedited processing."
    items = extract(text).contract_json["financial_items"]
    assert [(i["financial_action"], i["amount"]) for i in items] == [("fee", "100.00")]


@pytest.mark.parametrize("explicit", [False, True])
def test_parent_context_does_not_duplicate_child_prices(explicit):
    a = "Applicants shall pay a fee of " if explicit else ""
    items = extract(
        f"SEC. 1. Fees\nThe Secretary shall require a fee of—\n(1) {a}$100 for applications; and\n(2) {a}$50 for renewal."
    ).contract_json["financial_items"]
    assert [(i["financial_action"], i["amount"]) for i in items] == [
        ("fee", "100.00"),
        ("fee", "50.00"),
    ]


@pytest.mark.parametrize(
    "requirement,expected",
    [
        (
            "The Secretary shall require that the alien has been continuously physically present in the United States since January 1, 2021.",
            True,
        ),
        (
            "The Secretary shall not require that the alien has been continuously physically present in the United States since January 1, 2021.",
            False,
        ),
        (
            "The Secretary shall report whether the alien has been continuously physically present in the United States since January 1, 2021.",
            False,
        ),
    ],
)
def test_synopsis_date_requires_an_affirmative_eligibility_fact(requirement, expected):
    c = extract(
        "SEC. 1. Permanent resident status on a conditional basis for certain long-term residents who entered the United States as children\nThe Secretary shall adjust to the status of an alien lawfully admitted for permanent residence an eligible alien.\n"
        + requirement
    ).contract_json
    assert ("January 1, 2021" in c["orientation"]["purpose_clause"]) is expected
