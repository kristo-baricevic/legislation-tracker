"""Regressions derived from the pinned whole-bill review, not model output."""

import pytest

from apps.legislation.tests.test_reader_synopsis import extract


@pytest.mark.parametrize("dash", ["—", "--"])
@pytest.mark.parametrize("connector", ["and", "or"])
def test_eligibility_list_is_not_published_as_independent_conditions(dash, connector):
    rule = (
        f"The Secretary shall approve an application if the applicant{dash}\n"
        f"(A) holds a permit; {connector}\n"
        "(B) has completed training."
    )
    result = extract("SEC. 1. Eligibility\n" + rule)
    lines = result.contract_json["line_items"]
    assert len(lines) == 1
    assert "holds a permit" in lines[0]["display_text"]
    assert "has completed training" in lines[0]["display_text"]
    assert connector in lines[0]["display_text"]
    assert any(e.quoted_text == rule for e in result.evidence)


def test_nested_conditions_keep_exception_and_activity_alternatives_together():
    rule = (
        "Subject to paragraph (2), the Secretary shall remove conditions if the applicant--\n"
        "(A) remains eligible;\n(B) has not abandoned residence; and\n"
        "(C)(i) has a degree;\n(ii) has served for 2 years; or\n"
        "(iii) has earned income for 3 years and 75 percent of authorized time."
    )
    result = extract("SEC. 104. Removing conditions\n(1) " + rule)
    lines = result.contract_json["line_items"]
    assert len(lines) == 1
    for fragment in (
        "Subject to paragraph (2)",
        "remains eligible",
        "not abandoned",
        "degree",
        "2 years",
        "3 years",
        "75 percent",
    ):
        assert fragment in lines[0]["display_text"]
    assert any(e.quoted_text == rule for e in result.evidence)


def test_wrapped_cross_reference_is_not_a_new_condition():
    rule = (
        "The Secretary shall grant status if the applicant--\n"
        "(A) satisfies the requirements under subparagraphs\n"
        "    (A) and (B) of paragraph (1);\n"
        "(B) demonstrates compelling circumstances; and\n(C) has a disability."
    )
    result = extract("SEC. 104. Hardship\n(2) " + rule)
    assert len(result.contract_json["line_items"]) == 1
    assert any(e.quoted_text == rule for e in result.evidence)


def test_heading_and_line_wraps_do_not_remove_percentage_exclusions():
    result = extract(
        "SEC. 5. Grants\n"
        "(f) Permissive Use of Funds.--From the total amount appropriated for a fiscal year\n"
        "and not reserved under section 4 or subsection (d), the Secretary may set aside--\n"
        "(1) not more than 5 percent for administration; and\n"
        "(2) not more than 2 percent for technical assistance."
    )
    money = result.contract_json["financial_items"]
    assert len(money) == 2
    for item in money:
        assert (
            "not reserved under section 4 or subsection (d)" in item["source_account"]
        )
        assert "not reserved under section 4 or subsection (d)" in item["display_text"]


def test_pinned_hr9300_money_keeps_its_actual_residual_bases():
    from apps.legislation.evaluation.whole_bill import load_cases

    case = next(c for c in load_cases() if c["id"] == "BILLS-119hr9300ih")
    money = extract(case["text"]).contract_json["financial_items"]
    assert len(money) == 4
    assert "not reserved under section 4" in money[1]["source_account"]
    for item in money[2:]:
        assert "not reserved under section 4 or subsection (d)" in " ".join(
            item["source_account"].split()
        )


def test_later_nested_condition_cannot_clear_an_earlier_uncertain_branch():
    rule = (
        "Applicants shall pay $100 if they--\n"
        "(A) hold a permit which may be renewed and shall expire annually; and\n"
        "(B) the Secretary shall approve them if they--\n"
        "(i) qualify; and\n(ii) complete training."
    )
    result = extract("SEC. 1. Fees\n" + rule)
    assert result.contract_json["financial_items"] == []
    assert any(e.quoted_text == rule for e in result.evidence)
