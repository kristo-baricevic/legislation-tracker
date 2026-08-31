import pytest

from apps.legislation.comparison import compare_contracts
from apps.legislation.models import Bill, BillContract


@pytest.mark.django_db
def test_contract_comparison_uses_stable_identities_for_reordered_requirements():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 908",
        title="Contract diff bill",
        status="Introduced",
    )
    before = BillContract.objects.create(
        bill=bill,
        contract_hash="before-contract",
        contract_json={
            "plain_summary": "Before",
            "requirements": [
                {"section_label": "Sec. 1", "modality": "shall", "actor": "Agency", "action": "report", "object": "results", "deadline": "2027"}
            ],
        },
    )
    after = BillContract.objects.create(
        bill=bill,
        contract_hash="after-contract",
        contract_json={
            "plain_summary": "After",
            "requirements": [
                {"section_label": "Sec. 1", "modality": "shall", "actor": "Agency", "action": "report", "object": "results", "deadline": "2028"}
            ],
        },
    )

    diff = compare_contracts(before=before, after=after)

    assert [(change.path, change.operation) for change in diff.changes] == [
        ("plain_summary", "changed"),
        ("requirements[sec. 1|shall|agency|report|results].deadline", "changed"),
    ]
