"""Financial coverage regressions from H.R. 3511 (119th Congress, IH)."""
import pytest

from apps.legislation.tests.test_reader_synopsis import extract


PAYMENT = "Subject to the availability of appropriations under subsection (c), the Assistant Secretary shall pay to each eligible institution such sums as may be necessary to pay to each eligible recipient who files an application and agreement in accordance with subsection (b) a grant for school psychology in the amount of $8,000 for each year during which such eligible recipient is within the period of eligibility under paragraph (4) at such eligible institution."
ADVANCE = "Not less than 85 percent of any funds provided to an eligible institution under paragraph (1) shall be advanced to such eligible institution prior to the start of each payment period (as such period is determined by the Assistant Secretary) and shall be based upon an amount requested by such institution as needed to pay eligible recipients who receive grants under this section, until such time as the Assistant Secretary determines and publishes in the Federal Register (with an opportunity for comment) an alternative payment system that provides payments to such institutions in an accurate and timely manner, except that this sentence shall not be construed to limit the authority of the Assistant Secretary to place an institution on a reimbursement system of payment."
UNDERGRAD = "The period during which an eligible recipient who is an undergraduate or post-baccalaureate student may receive a grant under this section shall be the period after such eligible recipient has completed half of the required credit hours for a first undergraduate baccalaureate or post-baccalaureate course of study being pursued by such eligible recipient at an eligible institution at which such eligible recipient is in attendance, except that the total amount that an eligible recipient may receive under this section for undergraduate or post-baccalaureate study shall not exceed $16,000."
GRAD = "The period during which an eligible recipient who is a graduate student may receive grants under this section shall be the first and second year of a graduate or professional degree program in school psychology that is pursued by such eligible recipient at an eligible institution at which such eligible recipient is in attendance, except that the total amount that an eligible recipient may receive under this section for graduate study shall not exceed $16,000."


def test_grant_payments_and_caps_survive_reader_rendering_with_complete_conditions():
    source = "SEC. 554. Grant program for school psychologists\n" + "\n".join(
        f"({label}) {text}" for label, text in zip("abcd", [PAYMENT, ADVANCE, UNDERGRAD, GRAD])
    )
    result = extract(source)
    items = result.contract_json["financial_items"]
    assert [(i["amount"], i["amount_type"]) for i in items] == [
        ("8000.00", "specified"), ("85.00", "percentage"),
        ("16000.00", "ceiling"), ("16000.00", "ceiling"),
    ]
    for item, passage in zip(items, [PAYMENT, ADVANCE, UNDERGRAD, GRAD]):
        assert item["display_text"] == passage
    assert len({i["id"] for i in items}) == 4


def test_quoted_background_grant_is_not_new_funding():
    result = extract("SEC. 1. Findings\nCongress finds the following:\n[[QUOTED_BLOCK_START]]\n"
                     + PAYMENT + "\n[[QUOTED_BLOCK_END]]\nSEC. 2. Report\nThe Secretary shall submit a report.")
    assert result.contract_json["financial_items"] == []


def test_grant_retains_parent_eligibility():
    result = extract("SEC. 1. Grants\n(a) Eligibility.—Only if the State has adopted the required plan—\n"
                     "(1) the Secretary shall pay a grant in the amount of $8,000 to the State.")
    items = result.contract_json["financial_items"]
    assert len(items) == 1
    assert "Only if the State has adopted the required plan" in items[0]["display_text"]


@pytest.mark.parametrize("source", [
    "SEC. 1. Grants\n(a) Prohibition.—The Secretary shall not direct any agency to implement the following payment:\n(1) The agency shall pay a grant in the amount of $8,000.",
    "SEC. 1. Findings\nCongress finds that the Secretary shall pay a grant in the amount of $8,000.",
    "SEC. 1. Report\nThe Secretary shall study whether the agency shall pay a grant in the amount of $8,000.",
    "SEC. 1. Grants\n(a) Prohibition.—The Secretary shall not implement the following payment:\n(1) The grant shall not exceed $8,000.",
    "SEC. 1. Report\nThe Secretary shall study whether a grant shall not exceed $8,000.",
])
def test_nonoperative_grant_is_not_positive_funding(source):
    assert extract(source).contract_json["financial_items"] == []


def test_grant_cap_keeps_complete_parent_conditions_and_source_evidence():
    source = ("SEC. 1. Grants\n(a) Eligibility.—Only if the State has adopted a plan—\n"
              "(1) The grant shall not exceed $8,000.")
    result = extract(source)
    items = result.contract_json["financial_items"]
    assert len(items) == 1
    assert "Only if the State has adopted a plan" in items[0]["display_text"]
    assert "shall not exceed $8,000" in items[0]["display_text"]
