from dataclasses import replace

import pytest
from django.utils import timezone

from apps.congress import committee_sync
from apps.congress.models import (
    CommitteeMembership,
    CommitteeRosterSnapshot,
    Representative,
)
from apps.ingestion.committee_sources import CommitteeAssignment
from apps.ingestion.committee_sources import CommitteeRosterSnapshot as SourceSnapshot


def assignment(
    *, bioguide_id, code, name, chamber, parent_code=None, parent_name="", role="member"
):
    return CommitteeAssignment(
        bioguide_id=bioguide_id,
        committee_code=code,
        committee_name=name,
        chamber=chamber,
        parent_code=parent_code,
        parent_name=parent_name,
        rank=1,
        role=role,
        party_side="majority",
        source_code=code.upper(),
    )


def snapshot(*, chamber, assignments):
    return SourceSnapshot(
        congress=119,
        chamber=chamber,
        published_at=timezone.now(),
        source_url=f"https://source.test/{chamber}.xml",
        source_hash=f"{chamber}-hash",
        assignments=tuple(assignments),
    )


@pytest.mark.django_db
def test_committee_sync_replaces_valid_chamber_snapshots_atomically(monkeypatch):
    house_rep = Representative.objects.create(
        bioguide_id="R000001", name="House", chamber="house", party="R", state="NY"
    )
    senate_rep = Representative.objects.create(
        bioguide_id="S000001", name="Senate", chamber="senate", party="D", state="CA"
    )
    house = snapshot(
        chamber="house",
        assignments=[
            assignment(
                bioguide_id=house_rep.bioguide_id,
                code="hsii01",
                name="Procedure",
                chamber="house",
                parent_code="hsii00",
                parent_name="Rules",
                role="vice_chair",
            )
        ],
    )
    senate = snapshot(
        chamber="senate",
        assignments=[
            assignment(
                bioguide_id=senate_rep.bioguide_id,
                code="ssfi00",
                name="Finance",
                chamber="senate",
                role="chair",
            )
        ],
    )
    monkeypatch.setattr(committee_sync, "current_congress", lambda: 119)
    monkeypatch.setattr(
        committee_sync, "fetch_house_committee_roster", lambda **_kwargs: house
    )
    monkeypatch.setattr(
        committee_sync, "fetch_senate_committee_roster", lambda **_kwargs: senate
    )

    result = committee_sync.sync_committee_memberships()

    assert [item.membership_count for item in result] == [1, 1]
    membership = CommitteeMembership.objects.get(representative=house_rep)
    assert (
        membership.committee.system_code,
        membership.committee.parent.system_code,
        membership.role,
    ) == (
        "hsii01",
        "hsii00",
        "vice_chair",
    )
    assert membership.source_hash == "house-hash"
    assert CommitteeRosterSnapshot.objects.count() == 2


@pytest.mark.django_db
def test_invalid_snapshot_leaves_existing_memberships_unchanged(monkeypatch):
    representative = Representative.objects.create(
        bioguide_id="R000002", name="House", chamber="house", party="R", state="NY"
    )
    senate_rep = Representative.objects.create(
        bioguide_id="S000002", name="Senate", chamber="senate", party="D", state="CA"
    )
    house = snapshot(
        chamber="house",
        assignments=[
            assignment(
                bioguide_id=representative.bioguide_id,
                code="hsii00",
                name="Rules",
                chamber="house",
            )
        ],
    )
    senate = snapshot(
        chamber="senate",
        assignments=[
            assignment(
                bioguide_id=senate_rep.bioguide_id,
                code="ssfi00",
                name="Finance",
                chamber="senate",
            )
        ],
    )
    monkeypatch.setattr(committee_sync, "current_congress", lambda: 119)
    monkeypatch.setattr(
        committee_sync, "fetch_house_committee_roster", lambda **_kwargs: house
    )
    monkeypatch.setattr(
        committee_sync, "fetch_senate_committee_roster", lambda **_kwargs: senate
    )
    committee_sync.sync_committee_memberships()

    monkeypatch.setattr(
        committee_sync,
        "fetch_house_committee_roster",
        lambda **_kwargs: replace(house, assignments=()),
    )
    with pytest.raises(committee_sync.CommitteeSnapshotValidationError, match="empty"):
        committee_sync.sync_committee_memberships()

    assert (
        CommitteeMembership.objects.get(representative=representative).is_current
        is True
    )


@pytest.mark.django_db
def test_unknown_roster_member_fails_closed_by_default(monkeypatch):
    house = snapshot(
        chamber="house",
        assignments=[
            assignment(
                bioguide_id="R999999", code="hsii00", name="Rules", chamber="house"
            )
        ],
    )
    senate = snapshot(chamber="senate", assignments=())
    monkeypatch.setattr(committee_sync, "current_congress", lambda: 119)
    monkeypatch.setattr(
        committee_sync, "fetch_house_committee_roster", lambda **_kwargs: house
    )
    monkeypatch.setattr(
        committee_sync, "fetch_senate_committee_roster", lambda **_kwargs: senate
    )

    with pytest.raises(
        committee_sync.CommitteeSnapshotValidationError, match="unknown"
    ):
        committee_sync.sync_committee_memberships()

    assert not CommitteeMembership.objects.exists()
