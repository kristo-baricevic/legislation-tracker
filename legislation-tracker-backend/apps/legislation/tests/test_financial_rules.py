import pytest

from apps.legislation.extraction.federal_structure import parse_federal_structure
from apps.legislation.extraction.financial_rules import extract_financial_claims


def extract(source: str):
    return extract_financial_claims(source, parse_federal_structure(source))


def assert_exact_evidence(source: str, claims) -> None:
    for claim in claims:
        for span in claim.evidence:
            assert source[span.start_char : span.end_char] == span.text


def test_financial_rules_emit_each_amount_and_preserve_direction():
    source = """SEC. 240. RURAL HEALTH FUNDING
There is appropriated $500,000,000 for rural hospital grants, and $75,000,000 of unobligated balances is rescinded.
"""

    claims = extract(source)

    assert [
        (item.fields["financial_action"], item.fields["amount"]) for item in claims
    ] == [
        ("appropriation", "500000000.00"),
        ("rescission", "75000000.00"),
    ]
    assert [item.fields["direction"] for item in claims] == [
        "increase",
        "decrease",
    ]
    assert_exact_evidence(source, claims)


def test_financial_rules_distinguish_appropriation_from_authorization():
    source = """SEC. 7. FUNDING
There is appropriated $4,000,000 for rural grants.
There is authorized to be appropriated $6,000,000 for rural loans.
"""

    claims = extract(source)

    assert [item.fields["financial_action"] for item in claims] == [
        "appropriation",
        "authorization",
    ]
    assert [item.fields["purpose"] for item in claims] == [
        "rural grants",
        "rural loans",
    ]


def test_financial_rules_preserve_allocation_and_set_aside_actions():
    source = """SEC. 8. DISTRIBUTION
The Secretary shall allocate $20,000,000 for community clinics.
Of the amounts appropriated by this Act, the Secretary shall set aside 10 percent for tribal health programs.
"""

    claims = extract(source)

    assert [item.fields["financial_action"] for item in claims] == [
        "allocation",
        "set_aside",
    ]
    assert claims[1].fields["amount"] == "10.00"
    assert claims[1].fields["amount_type"] == "percentage"
    assert claims[1].fields["currency"] is None


def test_financial_rules_preserve_transfer_source_and_destination():
    source = """SEC. 9. TRANSFER
The Secretary shall transfer $10,000,000 from the Hospital Insurance Trust Fund to the Rural Health Account.
"""

    claim = extract(source)[0]

    assert claim.fields == {
        "financial_action": "transfer",
        "direction": "neutral_transfer",
        "amount": "10000000.00",
        "amount_type": "specified",
        "currency": "USD",
        "fiscal_years": [],
        "purpose": None,
        "source_account": "the Hospital Insurance Trust Fund",
        "destination_account": "the Rural Health Account",
    }


def test_financial_rules_bind_years_and_accounts_to_each_amount_subclause():
    source = """SEC. 9A. TRANSFERS
The Secretary shall transfer $10,000,000 from Account A to Account B for fiscal year 2026, and $20,000,000 from Account C to Account D for fiscal year 2027.
"""

    claims = extract(source)

    assert [item.fields["fiscal_years"] for item in claims] == [[2026], [2027]]
    assert [item.fields["source_account"] for item in claims] == [
        "Account A",
        "Account C",
    ]
    assert [item.fields["destination_account"] for item in claims] == [
        "Account B",
        "Account D",
    ]


@pytest.mark.parametrize(
    ("provision", "action"),
    [
        (
            "$5,000,000 of unobligated balances is hereby rescinded.",
            "rescission",
        ),
        (
            "The amount available for the program is reduced by $4,000,000.",
            "reduction",
        ),
        (
            "$3,000,000 in budget authority is hereby canceled.",
            "cancellation",
        ),
    ],
)
def test_financial_rules_preserve_negative_actions(provision, action):
    claim = extract(f"SEC. 10. SAVINGS\n{provision}\n")[0]

    assert claim.fields["financial_action"] == action
    assert claim.fields["direction"] == "decrease"


@pytest.mark.parametrize(
    ("provision", "amount", "amount_type"),
    [
        (
            "Not more than $5,000,000 may be obligated for administration.",
            "5000000.00",
            "ceiling",
        ),
        (
            "Administrative expenses shall not exceed 5 percent of amounts appropriated.",
            "5.00",
            "ceiling",
        ),
    ],
)
def test_financial_rules_preserve_limitations_and_ceilings(
    provision, amount, amount_type
):
    claim = extract(f"SEC. 11. LIMITATIONS\n{provision}\n")[0]

    assert claim.fields["financial_action"] == "limitation"
    assert claim.fields["direction"] == "limit"
    assert claim.fields["amount"] == amount
    assert claim.fields["amount_type"] == amount_type


def test_financial_rules_preserve_such_sums_as_an_explicit_amount_type():
    source = """SEC. 12. AUTHORIZATION
There are authorized to be appropriated such sums as may be necessary for fiscal year 2030 for administration.
"""

    claim = extract(source)[0]

    assert claim.fields["financial_action"] == "authorization"
    assert claim.fields["amount"] is None
    assert claim.fields["amount_type"] == "such_sums"
    assert claim.fields["currency"] is None
    assert claim.fields["fiscal_years"] == [2030]


def test_financial_rules_preserve_other_explicit_funding_actions():
    source = """SEC. 12A. OTHER FUNDING
$8,000,000 is made available for technical assistance.
"""

    claim = extract(source)[0]

    assert claim.fields["financial_action"] == "other_explicit"
    assert claim.fields["direction"] == "increase"
    assert claim.fields["purpose"] == "technical assistance"


def test_financial_rules_keep_repeated_annual_amount_wording_as_one_provision():
    source = """SEC. 13. ANNUAL AUTHORIZATION
There is authorized to be appropriated $2,000,000 for each of fiscal years 2026 through 2028 for rural clinics.
"""

    claims = extract(source)

    assert len(claims) == 1
    assert claims[0].fields["amount"] == "2000000.00"
    assert claims[0].fields["fiscal_years"] == [2026, 2027, 2028]
    assert claims[0].fields["purpose"] == "rural clinics"


def test_financial_rules_inherit_fiscal_year_and_account_context():
    source = """SEC. 14. ACCOUNT FUNDING
There is authorized to be appropriated from the Rural Health Account for fiscal year 2027—
(1) $5,000,000 for rural clinics.
"""

    claim = extract(source)[0]

    assert claim.fields["financial_action"] == "authorization"
    assert claim.fields["fiscal_years"] == [2027]
    assert claim.fields["source_account"] == "the Rural Health Account"
    assert claim.fields["purpose"] == "rural clinics"
    assert len(claim.evidence) == 2
    assert_exact_evidence(source, (claim,))


def test_financial_rules_preserve_a_purpose_split_across_source_lines():
    source = """SEC. 14A. DEFENSE FUNDING
There are appropriated for fiscal year 2025—
(1) $230,480,000 for restoration and modernization costs
under the Marine Corps Barracks 2030 initiative;
"""

    claim = extract(source)[0]

    assert claim.fields["purpose"] == (
        "restoration and modernization costs under the Marine Corps Barracks "
        "2030 initiative"
    )


def test_financial_rules_preserve_an_infinitive_appropriation_purpose():
    source = """SEC. 14B. DEFENSE SUPPORT
There are appropriated for fiscal year 2025—
(1) $590,000,000 to increase the Temporary Lodging Expense
Allowance under chapter 8 of title 37, United States Code, to 21 days;
"""

    claim = extract(source)[0]

    assert claim.fields["purpose"] == (
        "increase the Temporary Lodging Expense Allowance under chapter 8 of "
        "title 37, United States Code, to 21 days"
    )


def test_financial_rules_reject_nonfinancial_percentages():
    source = """SEC. 15. REPORTING
The Secretary shall report the percentage of applications approved and shall publish 75 percent of survey responses.
"""

    assert extract(source) == ()


def test_financial_rules_reject_population_percentage_limitation():
    source = """SEC. 15A. ELIGIBILITY
Not more than 75 percent of the State population may receive services.
"""

    assert extract(source) == ()


@pytest.mark.parametrize(
    "provision",
    [
        "There is authorized to be appropriated $5,000,000 for a program serving 75 percent of the State population.",
        "The Secretary shall transfer $5,000,000 from Account A to Account B for communities representing 75 percent of the State population.",
    ],
)
def test_financial_rules_reject_population_percentage_in_financial_clause(provision):
    source = f"SEC. 15A. FINANCIAL ACTION\n{provision}\n"

    claims = extract(source)

    assert len(claims) == 1
    assert claims[0].fields["amount"] == "5000000.00"
    assert claims[0].fields["amount_type"] == "specified"


def test_financial_rules_do_not_cap_recognized_provisions():
    provisions = "\n".join(
        f"There is appropriated ${index + 1},000 for program {index + 1}."
        for index in range(101)
    )
    source = f"SEC. 16. COMPLETE LEDGER\n{provisions}\n"

    claims = extract(source)

    assert len(claims) == 101
    assert claims[-1].fields["amount"] == "101000.00"
