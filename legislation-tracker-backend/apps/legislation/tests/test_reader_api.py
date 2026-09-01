import pytest
from rest_framework.test import APIClient

from apps.legislation.models import Bill, BillContract, BillDocument, EvidenceSpan


def _path(section="Sec. 1"):
    return [{"level": "section", "label": section, "heading": "Programs"}]


def _financial(index, *, action="appropriation", year=2026, section_id="section-1"):
    return {
        "id": f"financial-{index}",
        "source_id": f"financial-{index}",
        "section_id": section_id,
        "section_label": "Sec. 1",
        "section_path": _path(),
        "display_text": f"Appropriates ${index + 1},000.00.",
        "financial_action": action,
        "direction": "increase",
        "amount": f"{index + 1}000.00",
        "amount_type": "specified",
        "currency": "USD",
        "fiscal_years": [year],
        "purpose": "hospital grants",
        "source_account": None,
        "destination_account": None,
        "evidence_paths": [f"financial_items[{index}].display_text"],
    }


def _timeline(index, *, section_id="section-1"):
    return {
        "id": f"timeline-{index}",
        "source_id": f"timeline-{index}",
        "section_id": section_id,
        "section_label": "Sec. 1",
        "section_path": _path(),
        "display_text": f"Sets a deadline {index + 1} days after enactment.",
        "timeline_type": "relative",
        "date": None,
        "relative_value": index + 1,
        "relative_unit": "days",
        "trigger": "enactment",
        "evidence_paths": [f"timeline_items[{index}].display_text"],
    }


def _definition(index):
    return {
        "id": f"definition-{index}",
        "source_id": f"definition-{index}",
        "section_id": "section-2",
        "section_label": "Sec. 2",
        "section_path": _path("Sec. 2"),
        "display_text": f"Defines term {index}.",
        "term": f"term {index}",
        "definition": f"meaning {index}",
        "definition_type": "means",
        "evidence_paths": [f"definitions[{index}].display_text"],
    }


@pytest.fixture
def reader_contract(db):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 501",
        title="Reader API Act",
        summary="Reader API Act\n"
        + ("A complete official explanation " * 70)
        + "\nMore detail.",
        summary_source="crs",
        summary_action_date="2026-08-01",
        summary_version_code="RS",
        summary_last_updated_at="2026-08-02T10:00:00Z",
        status="Introduced",
    )
    document = BillDocument.objects.create(
        bill=bill,
        version_label="Introduced",
        extracted_text="First source chunk.Second source chunk.",
    )
    financial_items = [
        _financial(index, action="transfer" if index == 4 else "appropriation")
        for index in range(7)
    ]
    timeline_items = [_timeline(index) for index in range(5)]
    definitions = [_definition(index) for index in range(3)]
    line_items = []
    for index in range(101):
        line_items.append(
            {
                "id": f"line-{index}",
                "source_id": f"requirement-{index}",
                "section_id": "section-1" if index < 100 else "section-2",
                "section_path": _path("Sec. 1" if index < 100 else "Sec. 2"),
                "kind": "requirement",
                "display_text": f"Requires action {index}.",
                "actor": "the Secretary",
                "action": f"take action {index}",
                "effect": None,
                "claim_refs": [f"requirement-{index}"],
                "exact_financial_refs": [f"financial-{item}" for item in range(5)]
                if index == 0
                else [],
                "timeline_refs": [f"timeline-{item}" for item in range(4)]
                if index == 0
                else [],
                "definition_refs": ["definition-0", "definition-1"]
                if index == 0
                else [],
                "evidence_paths": [f"line_items[{index}].display_text"],
            }
        )
    contract = BillContract.objects.create(
        bill=bill,
        document=document,
        schema_version="2.1-legal-nlp",
        contract_hash="reader-contract-hash",
        contract_json={
            "schema_version": "2.1-legal-nlp",
            "coverage_note": "Recognized deterministic extraction coverage.",
            "orientation": {
                "purpose_clause": None,
                "purpose_line_item_id": None,
            },
            "reader_stats": {
                "line_item_count": 101,
                "financial_item_count": 7,
                "timeline_item_count": 5,
                "definition_item_count": 3,
                "section_group_count": 2,
            },
            "section_groups": [
                {
                    "source_id": "section-1",
                    "section_path": _path(),
                    "line_item_ids": [f"line-{index}" for index in range(100)],
                    "section_financial_refs": ["financial-5", "financial-6"],
                    "section_timeline_refs": ["timeline-4"],
                },
                {
                    "source_id": "section-2",
                    "section_path": _path("Sec. 2"),
                    "line_item_ids": ["line-100"],
                    "section_financial_refs": [],
                    "section_timeline_refs": [],
                },
            ],
            "line_items": line_items,
            "financial_items": financial_items,
            "timeline_items": timeline_items,
            "definitions": definitions,
        },
    )
    bill.latest_contract = contract
    bill.save(update_fields=["latest_contract"])
    EvidenceSpan.objects.bulk_create(
        [
            EvidenceSpan(
                bill=bill,
                document=document,
                contract=contract,
                field_path="line_items[0].display_text",
                start_char=0,
                end_char=19,
                quoted_text="First source chunk.",
            ),
            EvidenceSpan(
                bill=bill,
                document=document,
                contract=contract,
                field_path="requirements[0].display_text",
                start_char=0,
                end_char=19,
                quoted_text="First source chunk.",
            ),
            EvidenceSpan(
                bill=bill,
                document=document,
                contract=contract,
                field_path="line_items[0].display_text",
                start_char=19,
                end_char=39,
                quoted_text="Second source chunk.",
            ),
        ]
    )
    contract.contract_json["line_items"][0]["evidence_paths"].append(
        "requirements[0].display_text"
    )
    contract.save(update_fields=["contract_json"])
    return bill, contract


@pytest.mark.django_db
def test_reader_items_are_bounded_source_ordered_public_projections(reader_contract):
    _, contract = reader_contract
    client = APIClient()

    page = client.get(
        f"/api/contracts/{contract.id}/reader-items/",
        {"page": 2, "page_size": 25},
    )
    preview = client.get(
        f"/api/contracts/{contract.id}/reader-items/", {"page_size": 1}
    )

    assert page.status_code == 200
    assert page.json()["count"] == 101
    assert len(page.json()["results"]) == 25
    assert page.json()["results"][0]["id"] == "line-25"
    assert preview.status_code == 200
    item = preview.json()["results"][0]
    assert item["exact_financial_count"] == 5
    assert [entry["id"] for entry in item["exact_financial_preview"]] == [
        "financial-0",
        "financial-1",
        "financial-2",
    ]
    assert item["timeline_count"] == 4
    assert [entry["id"] for entry in item["timeline_preview"]] == [
        "timeline-0",
        "timeline-1",
        "timeline-2",
    ]
    assert item["definition_count"] == 2
    assert not ({"evidence_paths", "claim_refs", "exact_financial_refs"} & item.keys())
    assert preview.json()["section_supplements"] == [
        {
            "section_id": "section-1",
            "section_path": _path(),
            "section_financial_count": 2,
            "section_timeline_count": 1,
        }
    ]


@pytest.mark.django_db
def test_reader_actions_enforce_strict_query_bounds_and_v21_availability(
    reader_contract,
):
    bill, contract = reader_contract
    legacy = BillContract.objects.create(
        bill=bill,
        schema_version="2.0-legal-nlp",
        contract_hash="legacy-hash",
        contract_json={"schema_version": "2.0-legal-nlp", "plain_summary": "Legacy"},
    )
    client = APIClient()

    assert (
        client.get(
            f"/api/contracts/{contract.id}/reader-items/", {"page_size": 100}
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/contracts/{contract.id}/reader-items/", {"page_size": 101}
        ).status_code
        == 400
    )
    unknown = client.get(
        f"/api/contracts/{contract.id}/reader-items/", {"ranking": "importance"}
    )
    unavailable = client.get(f"/api/contracts/{legacy.id}/reader-items/")

    assert unknown.status_code == 400
    assert unknown.json()["ranking"] == ["Unknown query parameter."]
    assert unavailable.status_code == 409
    assert unavailable.json()["code"] == "reader_contract_unavailable"


@pytest.mark.django_db
def test_financial_timeline_and_definition_filters_are_validated(reader_contract):
    _, contract = reader_contract
    client = APIClient()
    base = f"/api/contracts/{contract.id}"

    financial = client.get(
        f"{base}/financial-items/",
        {"line_item_id": "line-0", "page_size": 100},
    )
    transfer = client.get(
        f"{base}/financial-items/",
        {"financial_action": "transfer", "fiscal_year": 2026},
    )
    section_financial = client.get(
        f"{base}/financial-items/", {"section_id": "section-1"}
    )
    timeline = client.get(f"{base}/timeline-items/", {"line_item_id": "line-0"})
    definitions = client.get(f"{base}/definition-items/", {"line_item_id": "line-0"})
    unlinked = client.get(f"{base}/definition-items/", {"unlinked": "true"})

    assert definitions.status_code == 200, definitions.json()
    assert unlinked.status_code == 200, unlinked.json()
    assert [item["id"] for item in financial.json()["results"]] == [
        "financial-0",
        "financial-1",
        "financial-2",
        "financial-3",
        "financial-4",
    ]
    assert [item["id"] for item in transfer.json()["results"]] == ["financial-4"]
    assert [item["id"] for item in section_financial.json()["results"]] == [
        "financial-5",
        "financial-6",
    ]
    assert [item["id"] for item in timeline.json()["results"]] == [
        f"timeline-{index}" for index in range(4)
    ]
    assert [item["id"] for item in definitions.json()["results"]] == [
        "definition-0",
        "definition-1",
    ]
    assert [item["id"] for item in unlinked.json()["results"]] == ["definition-2"]

    for response in (
        client.get(
            f"{base}/financial-items/",
            {"line_item_id": "line-0", "section_id": "section-1"},
        ),
        client.get(
            f"{base}/timeline-items/",
            {"line_item_id": "line-0", "section_id": "section-1"},
        ),
        client.get(
            f"{base}/definition-items/",
            {"line_item_id": "line-0", "unlinked": "true"},
        ),
        client.get(f"{base}/financial-items/", {"line_item_id": "line-missing"}),
        client.get(f"{base}/timeline-items/", {"section_id": "section-missing"}),
    ):
        assert response.status_code == 400


@pytest.mark.django_db
def test_evidence_requires_one_item_id_and_returns_deduplicated_chunks(reader_contract):
    _, contract = reader_contract
    client = APIClient()
    url = f"/api/contracts/{contract.id}/evidence/"

    first = client.get(url, {"line_item_id": "line-0", "page_size": 1})
    second = client.get(url, {"line_item_id": "line-0", "page": 2, "page_size": 1})

    assert first.status_code == 200
    assert first.json()["count"] == 2
    assert first.json()["results"] == [
        {
            "start_char": 0,
            "end_char": 19,
            "quoted_text": "First source chunk.",
            "page_number": None,
        }
    ]
    assert second.json()["results"][0]["start_char"] == 19
    assert client.get(url).status_code == 400
    assert (
        client.get(
            url,
            {"line_item_id": "line-0", "financial_item_id": "financial-0"},
        ).status_code
        == 400
    )
    assert client.get(url, {"line_item_id": "line-missing"}).status_code == 400
    assert (
        client.get(url, {"field_path": "line_items[0].display_text"}).status_code == 400
    )


@pytest.mark.django_db
def test_compact_bill_and_history_omit_full_summary_contract_and_evidence(
    reader_contract,
):
    bill, contract = reader_contract
    client = APIClient()

    compact = client.get(f"/api/bills/{bill.id}/", {"contract_view": "summary"})
    full = client.get(f"/api/bills/{bill.id}/")
    history = client.get("/api/contracts/", {"bill": bill.id, "view": "summary"})
    full_history = client.get("/api/contracts/", {"bill": bill.id})
    official = client.get(f"/api/bills/{bill.id}/official-summary/")

    assert compact.status_code == 200
    compact_body = compact.json()
    assert "summary" not in compact_body
    assert 0 < len(compact_body["summary_preview"]) <= 1200
    assert compact_body["summary_preview"].startswith("A complete official explanation")
    assert compact_body["summary_has_more"] is True
    assert set(compact_body["latest_contract"]) == {
        "id",
        "schema_version",
        "contract_hash",
        "computed_at",
        "document",
        "document_version_label",
        "coverage_note",
        "orientation",
        "reader_stats",
    }
    assert "contract_json" not in compact_body["latest_contract"]
    assert "evidence_spans" not in compact_body["latest_contract"]

    assert full.status_code == 200
    assert full.json()["summary"] == bill.summary
    assert full.json()["latest_contract"]["contract_json"]["line_items"]
    assert "summary_preview" not in full.json()
    assert set(history.json()["results"][0]) == set(compact_body["latest_contract"])
    assert full_history.json()["results"][0]["contract_json"]["financial_items"]
    assert official.json() == {
        "summary": bill.summary,
        "summary_source": "crs",
        "summary_action_date": "2026-08-01",
        "summary_version_code": "RS",
        "summary_last_updated_at": "2026-08-02T10:00:00Z",
    }
    assert (
        client.get(f"/api/bills/{bill.id}/", {"contract_view": "brief"}).status_code
        == 400
    )
    assert (
        client.get(
            f"/api/bills/{bill.id}/official-summary/", {"full": "true"}
        ).status_code
        == 400
    )


@pytest.mark.django_db
def test_reader_contract_requires_nonempty_persisted_hash(reader_contract):
    _, contract = reader_contract
    BillContract.objects.filter(pk=contract.pk).update(contract_hash="")

    response = APIClient().get(f"/api/contracts/{contract.id}/reader-items/")

    assert response.status_code == 409
    assert response.json()["code"] == "reader_contract_unavailable"
