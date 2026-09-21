import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.test import override_settings

from apps.legislation.extraction.service import extract_contract


def extract(text):
    with override_settings(LEGAL_NLP_V21_WRITE_ENABLED=True):
        result = extract_contract(
            bill=SimpleNamespace(title="Financial rules", jurisdiction="federal"),
            document=SimpleNamespace(extracted_text=text, version_label="Introduced"),
        )
    assert result.fallback_reason is None
    assert all(
        text[e.start_char : e.end_char] == e.quoted_text for e in result.evidence
    )
    return result.contract_json["financial_items"]


@pytest.mark.parametrize(
    "text,action,amount,amount_type",
    [
        (
            "The Secretary may require an applicant to pay a fee commensurate with processing costs but does not exceed $495.00.",
            "fee",
            "495.00",
            "ceiling",
        ),
        (
            "The Secretary shall require an applicant to pay a reasonable fee, but does not exceed $1,140.",
            "fee",
            "1140.00",
            "ceiling",
        ),
        (
            "Except for exempt applicants, a surcharge of $25 shall be imposed and collected for appointed counsel.",
            "surcharge",
            "25.00",
            "specified",
        ),
        (
            "Any person who unlawfully discloses information shall be fined not more than $10,000.",
            "penalty",
            "10000.00",
            "ceiling",
        ),
        (
            "The Secretary may require a fee commensurate with the cost of processing the application.",
            "fee",
            None,
            "unspecified",
        ),
    ],
)
def test_nonspending_money_keeps_category_qualifiers_and_source(
    text, action, amount, amount_type
):
    items = extract("SEC. 1. Applications\n" + text)
    assert len(items) == 1
    item = items[0]
    assert item["financial_action"] == action
    assert item["amount"] == amount
    assert item["amount_type"] == amount_type
    assert item["direction"] == "not_applicable"
    assert "funding" not in item["display_text"].lower()
    assert text in item["display_text"]


def test_exemption_preserves_all_alternative_conditions():
    items = extract(
        "SEC. 1. Fees\n(c) Fee exemption.—An applicant may be exempted from paying an application fee if the applicant—\n(1) is 18 years of age or younger;\n(2) has income less than 150 percent of the Federal poverty line; or\n(3) has a serious disability."
    )
    exemption = next(i for i in items if i["financial_action"] == "fee_exemption")
    assert all(
        term in exemption["display_text"]
        for term in ("18", "150 percent", "poverty", "or", "disability")
    )
    assert exemption["amount"] is None  # Income eligibility is not a budget percentage.


def test_account_deposit_and_availability_are_not_new_appropriations():
    items = extract(
        "SEC. 1. Counsel account\nFees collected under subsection (a) shall be deposited into the Immigration Counsel Account and shall remain available until expended for appointed counsel."
    )
    assert len(items) == 1
    assert items[0]["financial_action"] == "account_rule"
    assert "until expended" in items[0]["display_text"]


def test_availability_does_not_hide_an_appropriation_in_the_same_sentence():
    items = extract(
        "SEC. 1. Funding\nThere is appropriated $5 million for rural hospitals, and such funds shall remain available until expended."
    )
    assert any(
        i["financial_action"] == "appropriation" and i["amount"] == "5000000.00"
        for i in items
    )


@pytest.mark.parametrize(
    "text,amount,kind",
    [
        (
            "The Secretary shall require applicants with annual income above $50,000 to pay a fee of $100.",
            "100.00",
            "specified",
        ),
        (
            "The Secretary shall require applicants to pay a fee of $100 if their income exceeds $50,000.",
            "100.00",
            "specified",
        ),
        (
            "The Secretary shall require applicants to pay a fee equal to 2 percent of the loan amount.",
            "2.00",
            "percentage",
        ),
        (
            "The Secretary shall require applicants to pay a fee of not more than 2 percent of the loan amount.",
            "2.00",
            "ceiling",
        ),
        (
            "The Secretary shall require applicants to pay a $100 application fee.",
            "100.00",
            "specified",
        ),
    ],
)
def test_payment_amount_is_bound_to_fee_not_eligibility(text, amount, kind):
    items = extract("SEC. 1. Fees\n" + text)
    assert [(i["financial_action"], i["amount"], i["amount_type"]) for i in items] == [
        ("fee", amount, kind)
    ]


def test_fee_and_appropriation_both_survive_in_one_sentence():
    items = extract(
        "SEC. 1. Funding\nThe Secretary shall require a fee of $100, and there is appropriated $5 million for processing applications."
    )
    assert {(i["financial_action"], i["amount"]) for i in items} == {
        ("fee", "100.00"),
        ("appropriation", "5000000.00"),
    }


def test_fee_fiscal_year_survives_api_filter():
    from apps.legislation.reader_api import financial_items_page

    text = "SEC. 1. Fees\nFor fiscal year 2027, the Secretary shall require applicants to pay a fee of $100."
    with override_settings(LEGAL_NLP_V21_WRITE_ENABLED=True):
        result = extract_contract(
            bill=SimpleNamespace(title="Fees", jurisdiction="federal"),
            document=SimpleNamespace(extracted_text=text, version_label="Introduced"),
        )
    contract = SimpleNamespace(
        contract_json=result.contract_json,
        schema_version=result.schema_version,
        contract_hash="test",
    )
    page = financial_items_page(contract, page=1, page_size=25, fiscal_year=2027)
    assert page["count"] == 1
    assert page["results"][0]["fiscal_years"] == [2027]


def test_fee_inherits_fiscal_year_from_governing_parent():
    items = extract(
        "SEC. 1. Fees\nFor fiscal years 2027 through 2029:\n(1) The Secretary shall require applicants to pay a fee of $100."
    )
    assert items[0]["fiscal_years"] == [2027, 2028, 2029]


def test_grant_purpose_resolves_this_section_without_duplicate_years():
    items = extract(
        "SEC. 1. Grant program to assist eligible applicants\n(a) Authorization.—There are authorized to be appropriated such sums as may be necessary for each of the fiscal years 2026 through 2036 to carry out this section."
    )
    assert len(items) == 1
    assert "Grant program to assist eligible applicants" in items[0]["display_text"]
    assert items[0]["display_text"].count("2026") == 1


@pytest.mark.parametrize(
    "text",
    [
        "The report shall describe fees collected last year.",
        "The Secretary shall report whether a surcharge of $25 would be appropriate.",
        "The Secretary shall provide fee information to applicants.",
    ],
)
def test_fee_mentions_without_operative_payment_do_not_create_money_items(text):
    assert extract("SEC. 1. Reports\n" + text) == []


def test_hr1589_financial_coverage_against_annotated_complete_bill():
    from apps.legislation.evaluation.reader_quality import score_reader

    case = json.loads(
        (Path(__file__).parent / "fixtures/reader_evals/hr1589-119-ih.json").read_text()
    )
    items = extract(case["text"])
    result = score_reader(
        case, [{"category": "financial", "text": i["display_text"]} for i in items]
    )
    assert result["passed"], result
    from apps.legislation.serializers import (
        FinancialItemsQuerySerializer,
        FinancialPreviewPublicSerializer,
    )

    for item in items:
        preview = FinancialPreviewPublicSerializer(data=item)
        assert preview.is_valid(), preview.errors
        query = FinancialItemsQuerySerializer(
            data={"financial_action": item["financial_action"]}
        )
        assert query.is_valid(), query.errors
