"""Atomic persistence for validated current-Congress committee rosters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.congress.current import current_congress
from apps.congress.models import (
    Committee,
    CommitteeMembership,
    CommitteeRosterSnapshot,
    Representative,
)
from apps.ingestion.committee_sources import (
    CommitteeAssignment,
    CommitteeRosterError,
    fetch_house_committee_roster,
    fetch_senate_committee_roster,
)
from apps.ingestion.committee_sources import (
    CommitteeRosterSnapshot as SourceSnapshot,
)


class CommitteeSnapshotValidationError(CommitteeRosterError):
    """A fetched roster is not safe to use as a replacement snapshot."""


@dataclass(frozen=True)
class CommitteeSyncResult:
    congress: int
    membership_count: int
    representative_count: int


def _source_name(snapshot: SourceSnapshot) -> str:
    return "house_clerk" if snapshot.chamber == "house" else "senate"


def _committee_chamber(assignment: CommitteeAssignment) -> str:
    return (
        "joint"
        if assignment.committee_code.startswith(("js", "jc"))
        else assignment.chamber
    )


def _validate_snapshot(*, snapshot: SourceSnapshot, congress: int, now) -> set[str]:
    if snapshot.congress != congress:
        raise CommitteeSnapshotValidationError(
            "Committee snapshot Congress did not match"
        )
    if snapshot.chamber not in {"house", "senate"}:
        raise CommitteeSnapshotValidationError(
            "Committee snapshot has an invalid chamber"
        )
    if not snapshot.assignments:
        raise CommitteeSnapshotValidationError("Committee snapshot was empty")
    max_age = timedelta(days=getattr(settings, "COMMITTEE_ROSTER_MAX_AGE_DAYS", 90))
    if snapshot.published_at > now + timedelta(minutes=5):
        raise CommitteeSnapshotValidationError(
            "Committee snapshot publication time is in the future"
        )
    if now - snapshot.published_at > max_age:
        raise CommitteeSnapshotValidationError(
            "Committee snapshot is older than the freshness limit"
        )

    identities = {
        (item.bioguide_id, item.committee_code) for item in snapshot.assignments
    }
    if len(identities) != len(snapshot.assignments):
        raise CommitteeSnapshotValidationError(
            "Committee snapshot has duplicate assignments"
        )
    representative_ids = {item.bioguide_id for item in snapshot.assignments}
    if not representative_ids or any(
        not item.committee_code for item in snapshot.assignments
    ):
        raise CommitteeSnapshotValidationError(
            "Committee snapshot has incomplete identities"
        )
    known_ids = set(
        Representative.objects.filter(bioguide_id__in=representative_ids).values_list(
            "bioguide_id", flat=True
        )
    )
    unknown_ratio = 1 - (len(known_ids) / len(representative_ids))
    if unknown_ratio > getattr(
        settings, "COMMITTEE_ROSTER_MAX_UNKNOWN_MEMBER_RATIO", 0.0
    ):
        raise CommitteeSnapshotValidationError(
            "Committee snapshot references too many unknown representatives"
        )
    previous = CommitteeRosterSnapshot.objects.filter(
        congress=congress, chamber=snapshot.chamber
    ).first()
    if previous:
        minimum = previous.representative_count * getattr(
            settings, "COMMITTEE_ROSTER_MIN_MEMBER_FRACTION", 0.65
        )
        if len(representative_ids) < minimum:
            raise CommitteeSnapshotValidationError(
                "Committee snapshot dropped below the safe representative fraction"
            )
    return known_ids


def _upsert_committees(*, assignments: tuple[CommitteeAssignment, ...], published_at):
    by_code = {item.committee_code: item for item in assignments}
    parent_codes = {item.parent_code for item in assignments if item.parent_code}
    committees: dict[str, Committee] = {}
    for parent_code in sorted(parent_codes):
        parent_assignment = by_code.get(parent_code)
        parent_name = (
            parent_assignment.committee_name
            if parent_assignment
            else next(
                item.parent_name
                for item in assignments
                if item.parent_code == parent_code
            )
            or parent_code
        )
        committees[parent_code], _ = Committee.objects.update_or_create(
            system_code=parent_code,
            defaults={
                "name": parent_name[:255],
                "chamber": "joint" if parent_code.startswith(("js", "jc")) else "house",
                "committee_type": "subcommittee_parent",
                "is_current": True,
                "source_updated_at": published_at,
            },
        )
    for code, assignment in sorted(by_code.items()):
        parent = (
            committees.get(assignment.parent_code) if assignment.parent_code else None
        )
        committees[code], _ = Committee.objects.update_or_create(
            system_code=code,
            defaults={
                "name": assignment.committee_name[:255],
                "chamber": _committee_chamber(assignment),
                "committee_type": "subcommittee" if parent else "committee",
                "parent": parent,
                "is_current": True,
                "source_updated_at": published_at,
            },
        )
    return committees


def _persist_snapshot(
    *, snapshot: SourceSnapshot, congress: int
) -> CommitteeSyncResult:
    source_name = _source_name(snapshot)
    assignments = snapshot.assignments
    committees = _upsert_committees(
        assignments=assignments,
        published_at=snapshot.published_at,
    )
    representative_ids = {item.bioguide_id for item in assignments}
    representatives = {
        representative.bioguide_id: representative
        for representative in Representative.objects.filter(
            bioguide_id__in=representative_ids
        )
    }
    expected = {
        (item.bioguide_id, item.committee_code): item
        for item in assignments
        if item.bioguide_id in representatives
    }
    existing = {
        (
            membership.representative.bioguide_id,
            membership.committee.system_code,
        ): membership
        for membership in CommitteeMembership.objects.select_for_update()
        .select_related("representative", "committee")
        .filter(congress=congress, source_name=source_name)
    }
    for identity, assignment in expected.items():
        membership = existing.get(identity)
        values = {
            "rank": assignment.rank,
            "role": assignment.role,
            "party_side": assignment.party_side[:32],
            "source_code": assignment.source_code[:32],
            "source_hash": snapshot.source_hash,
            "is_current": True,
            "source_updated_at": snapshot.published_at,
        }
        if membership is None:
            CommitteeMembership.objects.create(
                committee=committees[assignment.committee_code],
                representative=representatives[assignment.bioguide_id],
                congress=congress,
                source_name=source_name,
                **values,
            )
            continue
        changed_fields = [
            field
            for field, value in values.items()
            if getattr(membership, field) != value
        ]
        if changed_fields:
            for field in changed_fields:
                setattr(membership, field, values[field])
            membership.save(update_fields=[*changed_fields, "updated_at"])
    stale = [
        membership
        for identity, membership in existing.items()
        if identity not in expected and membership.is_current
    ]
    for membership in stale:
        membership.is_current = False
        membership.save(update_fields=["is_current", "updated_at"])
    CommitteeRosterSnapshot.objects.update_or_create(
        congress=congress,
        chamber=snapshot.chamber,
        defaults={
            "source_url": snapshot.source_url,
            "source_hash": snapshot.source_hash,
            "published_at": snapshot.published_at,
            "assignment_count": len(assignments),
            "representative_count": len(representative_ids),
        },
    )
    return CommitteeSyncResult(
        congress=congress,
        membership_count=len(expected),
        representative_count=len(representative_ids),
    )


def sync_committee_memberships(
    *, congress: int | None = None
) -> list[CommitteeSyncResult]:
    """Replace both chamber rosters only after both official snapshots validate."""

    congress = current_congress() if congress is None else congress
    if congress != current_congress():
        raise CommitteeSnapshotValidationError(
            "Current official committee rosters cannot be used for a historical Congress"
        )
    snapshots = (
        fetch_house_committee_roster(congress=congress),
        fetch_senate_committee_roster(congress=congress),
    )
    now = timezone.now()
    for snapshot in snapshots:
        _validate_snapshot(snapshot=snapshot, congress=congress, now=now)
    with transaction.atomic():
        # Revalidate at the replacement boundary so a long-running fetch can
        # never turn a once-fresh payload into an accepted stale snapshot.
        write_now = timezone.now()
        for snapshot in snapshots:
            _validate_snapshot(snapshot=snapshot, congress=congress, now=write_now)
        return [
            _persist_snapshot(snapshot=snapshot, congress=congress)
            for snapshot in snapshots
        ]
