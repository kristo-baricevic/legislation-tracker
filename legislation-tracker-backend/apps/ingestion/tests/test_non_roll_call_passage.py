import pytest

from apps.ingestion import tasks
from apps.legislation.models import Bill
from apps.legislation.serializers import BillDetailSummarySerializer


@pytest.mark.django_db
def test_passage_without_roll_call_is_saved_deduplicated_and_exposed(monkeypatch):
    bill = Bill.objects.create(jurisdiction="federal", session=119, bill_number="S 2403", title="Test", status="Law")
    actions = [
        {"actionDate": "2025-10-09", "text": "Passed Senate with an amendment by Unanimous Consent."},
        {"actionDate": "2025-10-09", "text": "Passed/agreed to in Senate: Passed Senate with an amendment by Unanimous Consent."},
        {"actionDate": "2025-10-10", "text": "Motion to reconsider laid on the table Agreed to without objection."},
        {"actionDate": "2025-10-11", "text": "Unanimous consent request to pass Senate bill was not agreed to."},
    ]
    monkeypatch.setattr(tasks, "bill_actions", lambda *args: actions)
    tasks._process_bill_votes_impl(bill.id)
    tasks._process_bill_votes_impl(bill.id)
    bill.refresh_from_db()
    assert len(bill.passage_actions) == 1
    assert bill.passage_actions[0]["chamber"] == "Senate"
    assert bill.passage_actions[0]["method"] == "unanimous_consent"
    assert bill.passage_actions[0]["date"] == "2025-10-09"
    assert BillDetailSummarySerializer(bill).data["passage_actions"] == bill.passage_actions
    actions.clear()
    tasks._process_bill_votes_impl(bill.id)
    bill.refresh_from_db()
    assert bill.passage_actions == []


def test_voice_vote_requires_passage_not_just_a_procedural_motion():
    from apps.ingestion.passage_actions import extract_passage_actions
    actions = [
        {"actionDate": "2026-01-02", "text": "On motion to suspend the rules and pass the bill Agreed to by voice vote."},
        {"actionDate": "2026-01-03", "text": "Motion to adjourn agreed to by voice vote."},
        {"actionDate": "bad", "text": "Passed Senate by Unanimous Consent."},
    ]
    result = extract_passage_actions(actions, source_url="https://www.congress.gov/")
    assert [(item["chamber"], item["method"]) for item in result] == [("House", "voice_vote")]
