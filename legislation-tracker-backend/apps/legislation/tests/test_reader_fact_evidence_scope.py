import pytest
from jsonschema import ValidationError

from apps.legislation.enhancements.reader_facts import (
    factual_record_ids,
    resolve_factual_records,
)
from apps.legislation.tests.test_reader_facts import _claim, _record, _sources


def test_exception_citation_cannot_supply_the_claims_spending_authority():
    sources = _sources("There is authorized to be appropriated $100 for grants.")
    sources += _sources(
        "During emergencies. Under a separate program, the Secretary must spend $100 for grants.",
        first_ref=2,
    )
    owner, other = factual_record_ids(sources)
    claim = _claim(
        owner,
        "Spend the grant funding.",
        money=[
            dict(
                amount="100",
                currency="USD",
                measure="dollars",
                comparator=None,
                purpose="grants",
                period=None,
                base=None,
            )
        ],
        exceptions=[
            {"operator": "leaf", "text": "During emergencies.", "evidence_ids": [other]}
        ],
    )
    records = [_record(owner, claims=[claim]), _record(other, claims=[])]
    with pytest.raises(ValidationError) as error:
        resolve_factual_records(records, sources)
    assert error.value.validator == "reader_amount_conflict"

    claim["action"] = "Authorize appropriations."
    claim["modality"] = "permitted"
    assert resolve_factual_records(records, sources) == records


@pytest.mark.parametrize("branch", ["conditions", "exceptions"])
@pytest.mark.parametrize("amount, valid", [(100, False), (200, True)])
def test_condition_leaf_checks_its_own_evidence(branch, amount, valid):
    sources = _sources(
        "The Secretary shall review applications. The filing fee is $100."
    )
    sources += _sources("The application has a balance of $200.", first_ref=2)
    owner, other = factual_record_ids(sources)
    leaf = {
        "operator": "leaf",
        "text": f"The application has a balance of ${amount}.",
        "evidence_ids": [other],
    }
    group = {"operator": "all", "children": [leaf]}
    claim = _claim(
        owner,
        "Review applications.",
        **{branch: group if branch == "conditions" else [group]},
    )
    records = [_record(owner, claims=[claim]), _record(other, claims=[])]
    if valid:
        assert resolve_factual_records(records, sources) == records
    else:
        with pytest.raises(ValidationError) as error:
            resolve_factual_records(records, sources)
        assert error.value.validator == "reader_amount_conflict"


def test_a_conditional_appropriation_is_not_an_enacted_appropriation():
    sources = _sources(
        "The advisory board may meet if Congress appropriates $100 for grants."
    )
    (owner,) = factual_record_ids(sources)
    claim = _claim(
        owner,
        "Convene the board.",
        modality="permitted",
        conditions={
            "operator": "leaf",
            "text": "Congress appropriates $100 for grants",
            "evidence_ids": [owner],
        },
    )
    records = [_record(owner, claims=[claim])]
    assert resolve_factual_records(records, sources) == records
