"""Atomic, identity-safe synchronization of a bill's official relationships."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from django.db import transaction
from django.utils import timezone

from apps.changelog.services import record_bill_change
from apps.congress.models import BillCommittee, BillCosponsor, Committee, Representative
from apps.ingestion.congress_client import bill_committees, bill_cosponsors
from apps.ingestion.work_queue import enqueue_ingestion_work
from apps.legislation.models import Bill


@dataclass(frozen=True)
class RelationshipSyncResult:
    bill_id: int
    cosponsor_count: int
    committee_count: int
    changed: bool


def _bill_parts(bill: Bill) -> tuple[str, str]:
    parts = bill.bill_number.split(maxsplit=1)
    if len(parts) != 2 or parts[0].casefold() not in {"hr", "s"}:
        raise ValueError(f"Bill {bill.id} has unsupported official number")
    return parts[0].casefold(), parts[1]


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _parse_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _committee_code(*, chamber: str, raw_code: str) -> str:
    normalized = str(raw_code or "").strip().casefold()
    if not normalized:
        raise ValueError("Congress committee relationship is missing a system code")
    if normalized.startswith(("hs", "ss", "js")):
        return normalized
    prefix = {"house": "hs", "senate": "ss", "joint": "js"}.get(chamber)
    if not prefix:
        raise ValueError(f"Unsupported committee chamber: {chamber}")
    return f"{prefix}{normalized}"


def _relationship_event(*, bill: Bill, change_type: str, added: set[str], removed: set[str]):
    if not added and not removed:
        return
    cap = 100
    payload = {
        "added": sorted(added)[:cap],
        "removed": sorted(removed)[:cap],
        "added_count": len(added),
        "removed_count": len(removed),
        "truncated": len(added) > cap or len(removed) > cap,
    }
    fingerprint = hashlib.sha256(repr(payload).encode()).hexdigest()
    record_bill_change(
        bill=bill,
        change_type=change_type,
        old_value=None,
        new_value=payload,
        event_key=f"bill:{change_type}:{bill.id}:{fingerprint}",
    )


def sync_bill_relationships(*, bill_id: int) -> RelationshipSyncResult:
    """Replace bill relationships only after both complete upstream collections validate."""

    bill = Bill.objects.get(pk=bill_id)
    bill_type, bill_number = _bill_parts(bill)
    # Fetch both full collections before starting a write transaction. A source
    # failure therefore leaves the current persisted relationships untouched.
    raw_cosponsors = bill_cosponsors(bill.session, bill_type, bill_number)
    raw_committees = bill_committees(bill.session, bill_type, bill_number)
    if not all(isinstance(item, dict) for item in raw_cosponsors + raw_committees):
        raise ValueError("Congress relationship collection contains malformed entries")

    cosponsors = {}
    missing_dependencies = set()
    for item in raw_cosponsors:
        bioguide_id = str(item.get("bioguideId") or item.get("bioguide_id") or "").strip()
        if not bioguide_id:
            raise ValueError("Congress cosponsor is missing bioguideId")
        cosponsors[bioguide_id] = item
    known_ids = set(
        Representative.objects.filter(bioguide_id__in=cosponsors).values_list(
            "bioguide_id", flat=True
        )
    )
    missing_dependencies = set(cosponsors) - known_ids
    if missing_dependencies:
        discovered_at = timezone.now()
        for bioguide_id in missing_dependencies:
            enqueue_ingestion_work(
                kind="representative_detail",
                dedupe_key=f"bioguide:{bioguide_id}",
                source_updated_at=discovered_at,
                payload_json={"bioguide_id": bioguide_id},
                congress=bill.session,
            )
        from apps.ingestion.tasks import BlockedWork

        raise BlockedWork([f"bioguide:{item}" for item in missing_dependencies])

    normalized_committees = {}
    for item in raw_committees:
        chamber = str(item.get("chamber") or "").casefold()
        raw_code = item.get("systemCode") or item.get("system_code") or item.get("code")
        code = _committee_code(chamber=chamber, raw_code=raw_code)
        normalized_committees[(code, str(item.get("relationshipType") or "referred"))] = (
            item,
            chamber,
        )

    with transaction.atomic():
        bill = Bill.objects.select_for_update().get(pk=bill_id)
        existing_cosponsors = {
            relationship.representative.bioguide_id: relationship
            for relationship in BillCosponsor.objects.select_for_update()
            .select_related("representative")
            .filter(bill=bill)
        }
        existing_committees = {
            (relationship.committee.system_code, relationship.relationship_type): relationship
            for relationship in BillCommittee.objects.select_for_update()
            .select_related("committee")
            .filter(bill=bill)
        }
        for bioguide_id, item in cosponsors.items():
            representative = Representative.objects.get(bioguide_id=bioguide_id)
            BillCosponsor.objects.update_or_create(
                bill=bill,
                representative=representative,
                defaults={
                    "sponsorship_date": _parse_date(item.get("sponsorshipDate")),
                    "is_original_cosponsor": bool(item.get("isOriginalCosponsor", False)),
                    "withdrawn_at": _parse_datetime(item.get("withdrawnDate")),
                    "source_updated_at": _parse_datetime(item.get("updateDate")),
                },
            )
        for bioguide_id, relationship in existing_cosponsors.items():
            if bioguide_id not in cosponsors and relationship.withdrawn_at is None:
                relationship.withdrawn_at = timezone.now()
                relationship.save(update_fields=["withdrawn_at", "updated_at"])

        for (code, relationship_type), (item, chamber) in normalized_committees.items():
            committee, _ = Committee.objects.update_or_create(
                system_code=code,
                defaults={
                    "name": str(item.get("name") or item.get("committeeName") or code)[:255],
                    "chamber": chamber,
                    "committee_type": str(item.get("type") or "")[:32],
                    "website_url": str(item.get("url") or "")[:1024],
                    "is_current": True,
                    "source_updated_at": _parse_datetime(item.get("updateDate")),
                },
            )
            BillCommittee.objects.update_or_create(
                bill=bill,
                committee=committee,
                relationship_type=relationship_type[:32],
                defaults={
                    "activity_name": str(item.get("activityName") or "")[:255],
                    "source_name": "congress",
                    "source_code": str(item.get("systemCode") or item.get("code") or "")[:32],
                    "source_updated_at": _parse_datetime(item.get("updateDate")),
                },
            )
        for key, relationship in existing_committees.items():
            if key not in normalized_committees:
                relationship.delete()
        _relationship_event(
            bill=bill,
            change_type="cosponsor_update",
            added=set(cosponsors) - set(existing_cosponsors),
            removed=set(existing_cosponsors) - set(cosponsors),
        )
        _relationship_event(
            bill=bill,
            change_type="committee_update",
            added={":".join(key) for key in normalized_committees}
            - {":".join(key) for key in existing_committees},
            removed={":".join(key) for key in existing_committees}
            - {":".join(key) for key in normalized_committees},
        )
    return RelationshipSyncResult(
        bill_id=bill_id,
        cosponsor_count=len(cosponsors),
        committee_count=len(normalized_committees),
        changed=bool(
            set(cosponsors) != set(existing_cosponsors)
            or set(normalized_committees) != set(existing_committees)
        ),
    )
