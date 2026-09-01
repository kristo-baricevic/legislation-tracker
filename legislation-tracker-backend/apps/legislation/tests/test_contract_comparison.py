import pytest

from apps.legislation.comparison import compare_contracts, semantic_contract_items
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
                {
                    "section_label": "Sec. 1",
                    "modality": "shall",
                    "actor": "Agency",
                    "action": "report",
                    "object": "results",
                    "conditions": ["in 2027"],
                }
            ],
        },
    )
    after = BillContract.objects.create(
        bill=bill,
        contract_hash="after-contract",
        contract_json={
            "plain_summary": "After",
            "requirements": [
                {
                    "section_label": "Sec. 1",
                    "modality": "shall",
                    "actor": "Agency",
                    "action": "report",
                    "object": "results",
                    "conditions": ["in 2028"],
                }
            ],
        },
    )

    diff = compare_contracts(before=before, after=after)

    assert [(change.path, change.operation) for change in diff.changes] == [
        ("requirements[1]", "changed"),
    ]
    assert diff.changes[0].before["conditions"] == ("in 2027",)
    assert diff.changes[0].after["conditions"] == ("in 2028",)


@pytest.mark.django_db
def test_contract_comparison_preserves_duplicate_identity_rows():
    """Removing one of two same-identity requirements must remain visible."""
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 910",
        title="Duplicate identity diff bill",
        status="Introduced",
    )
    shared = {
        "section_label": "Sec. 1",
        "modality": "shall",
        "actor": "Agency",
        "action": "report",
        "object": "results",
    }
    before = BillContract.objects.create(
        bill=bill,
        contract_hash="duplicate-before",
        contract_json={
            "requirements": [
                {**shared, "conditions": ["in 2027"]},
                {**shared, "conditions": ["in 2028"]},
            ]
        },
    )
    after = BillContract.objects.create(
        bill=bill,
        contract_hash="duplicate-after",
        contract_json={"requirements": [{**shared, "conditions": ["in 2027"]}]},
    )

    diff = compare_contracts(before=before, after=after)

    assert diff.total_change_count == 1
    assert diff.changes[0].operation == "removed"
    assert diff.changes[0].before["conditions"] == ("in 2028",)


def requirement(*, source_id, section="Sec. 2", action="publish a report"):
    return {
        "id": f"requirement-{source_id.rsplit('-', 1)[-1]}",
        "source_id": source_id,
        "section_id": source_id,
        "section_label": section,
        "section_path": [{"level": "section", "label": section, "heading": "Reports"}],
        "display_text": f"Requires the Secretary to {action}.",
        "evidence_paths": ["requirements[0].display_text"],
        "modality": "required",
        "actor": "the Secretary",
        "action": action,
        "object": None,
        "conditions": [],
    }


def financial(*, source_id, amount, purpose="rural hospital grants"):
    return {
        "id": f"financial-{source_id.rsplit('-', 1)[-1]}",
        "source_id": source_id,
        "section_id": source_id,
        "section_label": "Sec. 3",
        "section_path": [{"level": "section", "label": "Sec. 3", "heading": "Funding"}],
        "display_text": f"Authorizes ${amount} for {purpose}.",
        "evidence_paths": ["financial_items[0].display_text"],
        "financial_action": "authorization",
        "direction": "increase",
        "amount": amount,
        "amount_type": "specified",
        "currency": "USD",
        "fiscal_years": [2027],
        "purpose": purpose,
        "source_account": None,
        "destination_account": None,
    }


def make_contract(bill, contract_hash, payload):
    return BillContract.objects.create(
        bill=bill,
        contract_hash=contract_hash,
        schema_version=payload.get("schema_version", "2.1-legal-nlp"),
        contract_json=payload,
    )


@pytest.mark.django_db
def test_offset_shifts_and_source_reordering_do_not_create_semantic_changes():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 911",
        title="Offsets",
        status="Introduced",
    )
    before = make_contract(
        bill,
        "offset-before",
        {
            "schema_version": "2.1-legal-nlp",
            "requirements": [
                requirement(source_id="section-10", action="publish a report"),
                requirement(
                    source_id="section-70", section="Sec. 4", action="issue guidance"
                ),
            ],
        },
    )
    after = make_contract(
        bill,
        "offset-after",
        {
            "schema_version": "2.1-legal-nlp",
            "requirements": [
                requirement(
                    source_id="section-900", section="Sec. 4", action="issue guidance"
                ),
                requirement(source_id="section-500", action="publish a report"),
            ],
        },
    )

    assert "section-10" not in repr(semantic_contract_items(before.contract_json))
    assert compare_contracts(before=before, after=after).total_change_count == 0


@pytest.mark.django_db
def test_amount_change_is_one_semantic_mutation():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 912",
        title="Funding",
        status="Introduced",
    )
    before = make_contract(
        bill,
        "amount-before",
        {
            "schema_version": "2.1-legal-nlp",
            "financial_items": [
                financial(source_id="section-10", amount="25000000.00")
            ],
        },
    )
    after = make_contract(
        bill,
        "amount-after",
        {
            "schema_version": "2.1-legal-nlp",
            "financial_items": [
                financial(source_id="section-900", amount="30000000.00")
            ],
        },
    )

    diff = compare_contracts(before=before, after=after)

    assert diff.total_change_count == 1
    assert diff.changes[0].operation == "changed"
    assert diff.changes[0].before["amount"] == "25000000.00"
    assert diff.changes[0].after["amount"] == "30000000.00"


@pytest.mark.django_db
def test_equivalent_v2_and_v21_claims_do_not_report_schema_migration_as_change():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 913",
        title="Mixed schema",
        status="Introduced",
    )
    before = make_contract(
        bill,
        "mixed-before",
        {
            "schema_version": "2.0-legal-nlp",
            "requirements": [
                {
                    "section_label": "Sec. 2",
                    "display_text": "The Secretary is required to publish a report.",
                    "modality": "required",
                    "actor": "the Secretary",
                    "action": "publish a report",
                    "object": None,
                    "conditions": [],
                }
            ],
        },
    )
    after = make_contract(
        bill,
        "mixed-after",
        {
            "schema_version": "2.1-legal-nlp",
            "requirements": [requirement(source_id="section-500")],
        },
    )

    assert compare_contracts(before=before, after=after).total_change_count == 0


@pytest.mark.django_db
def test_unrelated_same_bucket_claims_remain_remove_and_add():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 914",
        title="Replacement",
        status="Introduced",
    )
    before = make_contract(
        bill,
        "unrelated-before",
        {
            "schema_version": "2.1-legal-nlp",
            "requirements": [
                requirement(
                    source_id="section-10", action="publish annual hospital statistics"
                )
            ],
        },
    )
    after = make_contract(
        bill,
        "unrelated-after",
        {
            "schema_version": "2.1-legal-nlp",
            "requirements": [
                requirement(
                    source_id="section-900", action="prohibit disposal of nuclear waste"
                )
            ],
        },
    )

    operations = [
        change.operation
        for change in compare_contracts(before=before, after=after).changes
    ]

    assert operations == ["removed", "added"]


@pytest.mark.django_db
def test_new_and_removed_provisions_remain_explicit():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 915",
        title="Added and removed provisions",
        status="Introduced",
    )
    retained = requirement(source_id="section-10", action="publish a report")
    removed = requirement(
        source_id="section-20",
        section="Sec. 4",
        action="issue hospital guidance",
    )
    added = requirement(
        source_id="section-900",
        section="Sec. 5",
        action="audit grant recipients",
    )
    before = make_contract(
        bill,
        "add-remove-before",
        {
            "schema_version": "2.1-legal-nlp",
            "requirements": [retained, removed],
        },
    )
    after = make_contract(
        bill,
        "add-remove-after",
        {
            "schema_version": "2.1-legal-nlp",
            "requirements": [
                {**retained, "source_id": "section-500", "section_id": "section-500"},
                added,
            ],
        },
    )

    operations = {
        change.operation
        for change in compare_contracts(before=before, after=after).changes
    }

    assert operations == {"added", "removed"}


@pytest.mark.django_db
def test_legacy_requirement_funding_and_effective_date_changes_are_substantive():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 916",
        title="Legacy comparison",
        status="Introduced",
    )
    before = make_contract(
        bill,
        "legacy-before",
        {
            "schema_version": "1.1-deterministic",
            "plain_summary": "The bill creates a program.",
            "requirements": [],
            "funding_mentions": [],
            "effective_dates": [],
        },
    )
    after = make_contract(
        bill,
        "legacy-after",
        {
            "schema_version": "1.1-deterministic",
            "plain_summary": "The bill creates a program.",
            "requirements": [
                {"text": "The Secretary shall report.", "category": "requirement"}
            ],
            "funding_mentions": [
                {"text": "$5,000,000 is authorized.", "category": "funding"}
            ],
            "effective_dates": [
                {
                    "text": "The Act takes effect after enactment.",
                    "category": "effective_date",
                }
            ],
        },
    )

    diff = compare_contracts(before=before, after=after)

    assert diff.total_change_count == 3
    assert {change.path.split("[", 1)[0] for change in diff.changes} == {
        "legacy_requirements",
        "legacy_funding_mentions",
        "legacy_effective_dates",
    }
    assert {change.operation for change in diff.changes} == {"added"}


@pytest.mark.django_db
def test_equivalent_v2_leaf_and_v21_full_hierarchy_do_not_churn():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 917",
        title="Hierarchy migration",
        status="Introduced",
    )
    before = make_contract(
        bill,
        "hierarchy-v2",
        {
            "schema_version": "2.0-legal-nlp",
            "requirements": [
                {
                    "section_label": "Sec. 2",
                    "modality": "required",
                    "actor": "The Secretary",
                    "action": "publish a report",
                    "object": None,
                    "conditions": [],
                }
            ],
        },
    )
    v21_item = requirement(source_id="section-500")
    v21_item["section_path"] = [
        {"level": "division", "label": "DIVISION A", "heading": "Health"},
        {"level": "title", "label": "TITLE I", "heading": "Programs"},
        {"level": "section", "label": "Sec. 2", "heading": "Reports"},
    ]
    after = make_contract(
        bill,
        "hierarchy-v21",
        {"schema_version": "2.1-legal-nlp", "requirements": [v21_item]},
    )

    assert compare_contracts(before=before, after=after).total_change_count == 0


@pytest.mark.django_db
def test_same_leaf_in_distinct_v21_hierarchies_is_not_collapsed():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 918",
        title="Repeated section labels",
        status="Introduced",
    )
    first = requirement(source_id="section-10")
    first["section_path"] = [
        {"level": "division", "label": "DIVISION A", "heading": None},
        {"level": "section", "label": "Sec. 2", "heading": None},
    ]
    second = requirement(source_id="section-20")
    second["section_path"] = [
        {"level": "division", "label": "DIVISION B", "heading": None},
        {"level": "section", "label": "Sec. 2", "heading": None},
    ]
    before = make_contract(
        bill,
        "repeated-hierarchy-before",
        {"schema_version": "2.1-legal-nlp", "requirements": [first, second]},
    )
    after = make_contract(
        bill,
        "repeated-hierarchy-after",
        {"schema_version": "2.1-legal-nlp", "requirements": [first]},
    )

    diff = compare_contracts(before=before, after=after)

    assert diff.total_change_count == 1
    assert diff.changes[0].operation == "removed"
    assert diff.changes[0].before["structural_path"][0] == "division b"


@pytest.mark.django_db
def test_short_unrelated_actions_do_not_match_on_json_scaffolding():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 919",
        title="Short actions",
        status="Introduced",
    )
    before = make_contract(
        bill,
        "short-before",
        {
            "schema_version": "2.1-legal-nlp",
            "requirements": [requirement(source_id="section-10", action="tax")],
        },
    )
    after = make_contract(
        bill,
        "short-after",
        {
            "schema_version": "2.1-legal-nlp",
            "requirements": [requirement(source_id="section-20", action="run")],
        },
    )

    assert [
        change.operation
        for change in compare_contracts(before=before, after=after).changes
    ] == ["removed", "added"]
