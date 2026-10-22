from decimal import Decimal
import pytest
from apps.campaign_finance.normalization import normalize_receipt, normalize_refund


def receipt(**changes):
    return {"sub_id": "1001", "committee_id": "C00000001", "contributor_id": "C00000002", "contributor_name": "Example PAC", "entity_type": "PAC", "line_number": "11C", "contribution_receipt_amount": "100.00", "contribution_receipt_date": "2026-01-10", **changes}


@pytest.mark.parametrize("fields,kind", [
    ({"line_number": "11D"}, "candidate_contribution"),
    ({"line_number": "12"}, "transfer"),
    ({"line_number": "13A"}, "candidate_loan"),
    ({"line_number": "13B"}, "loan"),
    ({"line_number": "11C", "memo_code": "X"}, "contribution"),
])
def test_non_donor_receipts_remain_classified_but_excluded(fields, kind):
    row = normalize_receipt(receipt(**fields))
    assert row["kind"] == kind
    assert not row["effective"]


def test_false_memo_flag_is_not_treated_as_a_memo():
    assert normalize_receipt(receipt(memoed_subtotal=False))["effective"]
    assert normalize_receipt(receipt(memoed_subtotal="false"))["effective"]


def test_unknown_boolean_flag_is_not_silently_published():
    with pytest.raises(ValueError, match="invalid_memo_flag"):
        normalize_receipt(receipt(memoed_subtotal="maybe"))


def test_conduit_and_memo_pair_cannot_make_conduit_the_donor():
    original = normalize_receipt(receipt(entity_type="IND", contributor_id=None, contributor_name="Example Person", conduit_committee_id="C00000002"))
    memo = normalize_receipt(receipt(sub_id="1002", memo_code="X"))
    assert not original["effective"] and not memo["effective"]
    assert original["contributor_kind"] == "individual"
    assert original["identity_key"] != "fec:C00000002"


def test_metadata_keeps_references_not_contact_information():
    row = normalize_receipt(receipt(transaction_id="R1", original_sub_id="42", file_number=99, contributor_street_1="private", contributor_employer="Not the donor"))
    assert row["source_metadata"]["transaction_id"] == "R1"
    assert "contributor_street_1" not in row["source_metadata"]
    assert "contributor_employer" not in row["source_metadata"]


def test_refund_does_not_match_person_by_name():
    original = normalize_receipt(receipt(entity_type="IND", contributor_id=None, contributor_name="Same Name"))
    refund = normalize_refund({"sub_id": "1002", "committee_id": "C00000001", "recipient_name": "Same Name", "entity_type": "IND", "line_number": "20A", "disbursement_amount": 25})
    assert refund["identity_key"] != original["identity_key"]
    assert refund["amount"] == Decimal("25")
    assert refund["source_metadata"]["line_number"] == "20A"
