from types import SimpleNamespace

import pytest
from django.test import override_settings

from apps.legislation.extraction.federal_structure import parse_federal_structure
from apps.legislation.extraction.service import extract_contract


def extract(text):
    with override_settings(LEGAL_NLP_V21_WRITE_ENABLED=True):
        result = extract_contract(
            bill=SimpleNamespace(title="Review regression", jurisdiction="federal"),
            document=SimpleNamespace(extracted_text=text, version_label="Introduced"),
        )
    assert result.fallback_reason is None
    return result.contract_json


def test_list_rewrite_preserves_preceding_and_descendant_duties():
    contract = extract(
        "SEC. 2. Reports\nThe Secretary shall publish an annual report. "
        "The Secretary may include the following:\n"
        "(1) Research results. Recipients shall submit annual accounts.\n"
        "(2) Recommendations."
    )
    duties = [
        x["display_text"] for x in contract["line_items"] if x["kind"] == "requirement"
    ]
    assert any("publish an annual report" in x for x in duties)
    assert any("Recipients" in x and "submit annual accounts" in x for x in duties)
    assert any("Research results" in x["display_text"] for x in contract["line_items"])


@pytest.mark.parametrize("outer", ["shall", "may"])
def test_nested_optional_examples_remain_permissions(outer):
    contract = extract(
        f"SEC. 2. Activities\nThe Secretary {outer} fund the following:\n"
        "(1) Student services, which may include the following:\n"
        "(A) Career counseling.\n(B) Financial counseling."
    )
    for phrase in ("Career counseling", "Financial counseling"):
        items = [x for x in contract["line_items"] if phrase in x["display_text"]]
        assert items and all(x["kind"] == "permission" for x in items)
    if outer == "shall":
        assert any(
            x["kind"] == "requirement" and "Student services" in x["display_text"]
            for x in contract["line_items"]
        )


def test_independent_nested_modal_is_not_replaced_with_parent_actor():
    contract = extract(
        "SEC. 2. Programs\nThe Secretary may establish the following:\n"
        "(1) Reports.—Recipients shall include the following:\n"
        "(A) Costs.\n(B) Outcomes."
    )
    for phrase in ("Costs", "Outcomes"):
        assert any(
            x["kind"] == "requirement"
            and "Recipients" in x["display_text"]
            and phrase in x["display_text"]
            for x in contract["line_items"]
        )


@pytest.mark.parametrize("subsection", ["h", "u", "w"])
def test_roman_lists_keep_their_parent_under_alphabetic_collisions(subsection):
    romans = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"]
    text = f"SEC. 2. Activities\n({subsection}) Program.—Text.\n(1) Services.—Text.\n(A) Details.—Text.\n"
    text += "\n".join(f"({label}) Counseling." for label in romans)
    sections = parse_federal_structure(text)
    assert [s.level for s in sections[-10:]] == ["clause"] * 10
    assert all(s.path[1].label == f"({subsection})" for s in sections[-10:])


def test_federal_reserve_reporting_is_not_a_set_aside():
    contract = extract(
        "SEC. 2. Reporting\nThe Federal Reserve shall publish a report on loans exceeding $1,000,000."
    )
    assert contract["financial_items"] == []


@pytest.mark.parametrize("amount", ["$5 million", "$5,000,000", "5 million dollars"])
def test_financial_minimum_preserves_currency_and_scale(amount):
    contract = extract(
        f"SEC. 2. Grants\nThe Secretary shall reserve not less than {amount} for rural grants."
    )
    assert len(contract["financial_items"]) == 1
    assert "at least $5,000,000.00" in contract["financial_items"][0]["display_text"]


def test_minimum_does_not_leak_to_an_equal_amount_elsewhere_in_sentence():
    contract = extract(
        "SEC. 2. Grants\nThere is appropriated at least $5 million for rural grants and $5 million for urban grants."
    )
    money = contract["financial_items"]
    assert "at least" in money[0]["display_text"]
    assert "at least" not in money[1]["display_text"]


@pytest.mark.parametrize("lead", ["submit the following", "do one of the following"])
def test_disjunctive_list_keeps_alternatives_in_one_obligation(lead):
    contract = extract(
        f"SEC. 2. Reports\nThe Secretary shall {lead}:\n(1) Publish an annual report; or\n(2) Publish a certified statement."
    )
    choices = [
        x
        for x in contract["line_items"]
        if "annual report" in x["display_text"]
        or "certified statement" in x["display_text"]
    ]
    assert len(choices) == 1
    assert "annual report; or" in choices[0]["display_text"]
    assert "certified statement" in choices[0]["display_text"]
    assert choices[0]["kind"] == "requirement"


@pytest.mark.parametrize("minimum", ["not less than", "at least"])
def test_nested_reservations_include_minimum_and_maximum(minimum):
    contract = extract(
        f"SEC. 2. Grants\nFrom the total amount appropriated, the Secretary shall reserve—\n(1) {minimum} 20 percent for rural grants; and\n(2) not more than 5 percent for administration."
    )
    money = contract["financial_items"]
    assert len(money) == 2
    assert (
        "at least 20 percent of the total amount appropriated"
        in money[0]["display_text"]
    )
    assert "rural grants" in money[0]["purpose"]
    assert "no more than 5 percent" in money[1]["display_text"]


@pytest.mark.parametrize("outer", ["shall", "may"])
def test_nested_choices_keep_the_parent_modality_and_independent_duties(outer):
    contract = extract(
        f"SEC. 2. Reports\nThe Secretary shall notify Congress. The Secretary {outer} provide the following:\n(1) Reports, including one of the following:\n(A) An annual report; or\n(B) A certified statement.\n(2) Public notices."
    )
    items = contract["line_items"]
    choice = [x for x in items if "annual report" in x["display_text"]]
    assert len(choice) == 1
    assert "certified statement" in choice[0]["display_text"]
    assert "one of" in choice[0]["display_text"] and "; or" in choice[0]["display_text"]
    assert choice[0]["kind"] == ("requirement" if outer == "shall" else "permission")
    assert any("Public notices" in x["display_text"] for x in items)
    assert any(
        x["kind"] == "requirement" and "notify Congress" in x["display_text"]
        for x in items
    )


def test_conjunctive_list_still_exposes_each_required_item():
    contract = extract(
        "SEC. 2. Reports\nThe Secretary shall submit the following:\n(1) An annual report; and\n(2) A certified statement."
    )
    duties = [x for x in contract["line_items"] if x["kind"] == "requirement"]
    assert len(duties) == 2
    assert "annual report" in duties[0]["display_text"]
    assert "certified statement" in duties[1]["display_text"]


def test_bare_modal_choice_replaces_inherited_leaf_duties():
    contract = extract(
        "SEC. 2. Reports\nThe Secretary shall—\n(1) publish an annual report; or\n(2) publish a certified statement."
    )
    duties = [x for x in contract["line_items"] if x["kind"] == "requirement"]
    assert len(duties) == 1
    assert (
        "to publish an annual report; or publish a certified statement"
        in duties[0]["display_text"]
    )


def test_grouped_nested_choice_preserves_independent_child_duties():
    contract = extract(
        "SEC. 2. Reports\nThe Secretary shall provide the following:\n(1) A program using one of the following:\n(A) Grants; or\n(B) Loans. Recipients shall submit annual accounts.\n(2) Public notices."
    )
    assert any(
        x["actor"] == "Recipients" and "annual accounts" in x["display_text"]
        for x in contract["requirements"]
    )


@pytest.mark.parametrize("length", [3950, 5100])
def test_oversized_definition_does_not_discard_other_reader_items(length):
    text = (
        "SEC. 2. Definitions\nThe term eligible entity means—\n"
        "(1) an institution providing "
        + "student services "
        * (length // 17)
        + ".\nSEC. 3. Grants\nThere is appropriated $5 million for rural grants.\n"
        "The Secretary shall publish a report."
    )
    contract = extract(text)
    assert contract["schema_version"] == "2.1-legal-nlp"
    assert contract["financial_items"][0]["amount"] == "5000000.00"
    assert any(
        "publish a report" in item["display_text"] for item in contract["line_items"]
    )
    assert contract["definitions"] == []
    assert "reader_definition_too_long" in contract["extraction"]["warnings"]
    assert (
        "definitions" in contract["coverage_note"]
        and "bill text" in contract["coverage_note"]
    )


@pytest.mark.parametrize(
    "object_text",
    [
        "the right to reject applications requesting more than $5 million",
        "the right to recover $5 million in damages",
        "authority over projects costing $5 million",
        "rooms for a conference costing $5 million",
    ],
)
def test_nonfinancial_reservations_do_not_invent_budget_items(object_text):
    contract = extract(f"SEC. 2. Rules\nThe Secretary may reserve {object_text}.")
    assert contract["financial_items"] == []
    assert any("reserve" in item["display_text"] for item in contract["line_items"])


@pytest.mark.parametrize(
    "provision",
    [
        "The Secretary shall reserve $5 million for rural grants.",
        "The Secretary shall reserve funds totaling $5 million for rural grants.",
        "The Secretary shall reserve for rural grants $5 million.",
        "The Secretary shall reserve, for rural grants, $5 million.",
        "$5 million is reserved for rural grants.",
        "From available funds, the Secretary shall reserve—\n(1) $5 million for rural grants.",
    ],
)
def test_financial_reservation_forms_remain_supported(provision):
    contract = extract("SEC. 2. Grants\n" + provision)
    assert len(contract["financial_items"]) == 1
    assert contract["financial_items"][0]["financial_action"] == "set_aside"
    assert contract["financial_items"][0]["amount"] == "5000000.00"
