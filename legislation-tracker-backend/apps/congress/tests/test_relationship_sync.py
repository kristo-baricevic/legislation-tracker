import pytest

from apps.changelog.models import ChangeLog
from apps.congress.models import BillCommittee, BillCosponsor, Representative
from apps.congress.relationship_sync import sync_bill_relationships
from apps.ingestion.models import IngestionWorkItem
from apps.legislation.models import Bill


@pytest.mark.django_db
def test_relationship_sync_replaces_complete_collections_and_records_activity(monkeypatch):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 1",
        title="Relationship bill",
        status="Introduced",
    )
    representative = Representative.objects.create(
        bioguide_id="R000001",
        name="Relationship Representative",
        chamber="house",
        party="Independent",
        state="NY",
    )
    monkeypatch.setattr(
        "apps.congress.relationship_sync.bill_cosponsors",
        lambda *_args: [
            {
                "bioguideId": representative.bioguide_id,
                "sponsorshipDate": "2026-01-01",
                "isOriginalCosponsor": True,
                "updateDate": "2026-01-02T00:00:00Z",
            }
        ],
    )
    monkeypatch.setattr(
        "apps.congress.relationship_sync.bill_committees",
        lambda *_args: [
            {
                "systemCode": "hsii00",
                "chamber": "house",
                "name": "House Rules",
                "relationshipType": "referred",
                "updateDate": "2026-01-02T00:00:00Z",
            }
        ],
    )

    result = sync_bill_relationships(bill_id=bill.id)

    assert result.changed is True
    assert BillCosponsor.objects.get().representative == representative
    assert BillCommittee.objects.get().committee.system_code == "hsii00"
    assert set(ChangeLog.objects.filter(bill=bill).values_list("change_type", flat=True)) == {
        "cosponsor_update",
        "committee_update",
    }


@pytest.mark.django_db
def test_relationship_sync_blocks_on_missing_exact_bioguide_without_partial_writes(
    monkeypatch,
):
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 2",
        title="Blocked relationship bill",
        status="Introduced",
    )
    monkeypatch.setattr(
        "apps.congress.relationship_sync.bill_cosponsors",
        lambda *_args: [{"bioguideId": "R000002"}],
    )
    monkeypatch.setattr(
        "apps.congress.relationship_sync.bill_committees",
        lambda *_args: [],
    )

    from apps.ingestion.tasks import BlockedWork

    with pytest.raises(BlockedWork, match="blocked_on_dependencies"):
        sync_bill_relationships(bill_id=bill.id)

    assert not BillCosponsor.objects.exists()
    dependency = IngestionWorkItem.objects.get(kind="representative_detail")
    assert dependency.dedupe_key == "bioguide:R000002"
