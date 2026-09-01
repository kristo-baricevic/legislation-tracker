"""
Celery tasks for Congress.gov ingestion: poll, process_bill, versions, votes.
"""

import hashlib
import logging
import uuid
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser

import requests
from celery import shared_task
from django.db import transaction
from django.db.models import Case, IntegerField, Q, When
from django.utils import timezone

from apps.accounts.models import TrackedBill, TrackedLegislator, TrackedTopic
from apps.changelog.events import diff_bill_metadata, snapshot_bill_metadata
from apps.changelog.services import lock_bill_activity, record_bill_change
from apps.congress.current import current_congress, current_congress_session
from apps.congress.models import Representative, RepresentativeTerm, Vote, VoteRecord
from apps.ingestion.committee_sources import (
    CommitteeRosterError,
    CommitteeRosterTransportError,
)
from apps.ingestion.congress_client import (
    CongressAPIError,
    bill_actions,
    bill_detail,
    bill_list,
    bill_summaries,
    bill_text_list,
    member_detail,
    member_list,
    state_code,
    vote_detail,
)
from apps.ingestion.document_download import (
    DocumentValidationError,
    RetryableDocumentStorageError,
    build_object_key,
    download_url,
    extract_document_text,
    guess_extension,
    retryable_storage_error,
    upload_and_metadata,
)
from apps.ingestion.models import (
    IngestionState,
    IngestionTaskFailure,
    IngestionWorkItem,
    IngestionWorkStatus,
    RollCallIngestionState,
)
from apps.ingestion.vote_sources import HouseVoteSource, SenateVoteSource
from apps.ingestion.work_queue import (
    enqueue_ingestion_work,
    fulfill_tracking_requests_for_bill,
)
from apps.legislation.models import Bill, BillDocument, ProcessingStatus

logger = logging.getLogger(__name__)

CURSOR_OVERLAP = timedelta(minutes=5)
TRACKED_REFRESH_INTERVAL = timedelta(minutes=5)
WORK_LEASE_DURATION = timedelta(minutes=10)
MAX_INGESTION_WORK_ATTEMPTS = 5
UNKNOWN_SOURCE_UPDATED_AT = datetime(1970, 1, 1, tzinfo=UTC)
DURABLE_WORK_SOFT_TIME_LIMIT_SECONDS = 60
DURABLE_WORK_TIME_LIMIT_SECONDS = 75
MAX_DISPATCHED_INGESTION_WORK = 100

WORK_KIND_BILL = "bill"
WORK_KIND_BILL_VERSIONS = "bill_versions"
WORK_KIND_BILL_VOTES = "bill_votes"
WORK_KIND_DOCUMENT_DOWNLOAD = "document_download"
WORK_KIND_BILL_RELATIONSHIPS = "bill_relationships"
WORK_KIND_ROLL_CALL_VOTE = "roll_call_vote"
WORK_KIND_REPRESENTATIVE_DETAIL = "representative_detail"

# A backlog of recorded votes must never delay the work that makes a newly
# ingested bill usable in the product. Values are intentionally spaced so a
# future stage can be inserted without changing established ordering.
WORK_KIND_DISPATCH_PRIORITY = {
    # Already-downloaded documents can produce a visible contract immediately;
    # do not strand them behind a broad bill-discovery backlog.
    WORK_KIND_DOCUMENT_DOWNLOAD: 0,
    "document_contract": 10,
    "metadata_contract": 10,
    "topic_update": 20,
    # A roster sync must not be starved by a full Congress bill poll.
    WORK_KIND_REPRESENTATIVE_DETAIL: 30,
    WORK_KIND_BILL: 40,
    WORK_KIND_BILL_VERSIONS: 50,
    WORK_KIND_BILL_RELATIONSHIPS: 60,
    WORK_KIND_BILL_VOTES: 70,
    WORK_KIND_ROLL_CALL_VOTE: 80,
    "search_index": 90,
    "similarity": 100,
}


def _work_dispatch_priority():
    return Case(
        *[
            When(kind=kind, then=priority)
            for kind, priority in WORK_KIND_DISPATCH_PRIORITY.items()
        ],
        default=999,
        output_field=IntegerField(),
    )


class BlockedWork(Exception):
    """Work that is valid but cannot proceed until exact identities exist."""

    def __init__(self, dependency_keys: list[str], reason="blocked_on_dependencies"):
        super().__init__(reason)
        self.dependency_keys = sorted(set(dependency_keys))
        self.reason = reason


def _queue_bill_stage(bill, kind, *, source_updated_at=None):
    return enqueue_ingestion_work(
        kind=kind,
        dedupe_key=str(bill.id),
        source_updated_at=source_updated_at or bill.updated_at or timezone.now(),
        payload_json={"bill_id": bill.id},
        jurisdiction=bill.jurisdiction,
        congress=bill.session,
    )


def _queue_bill_relationships(bill, *, source_updated_at=None):
    return _queue_bill_stage(
        bill,
        WORK_KIND_BILL_RELATIONSHIPS,
        source_updated_at=source_updated_at,
    )


def _wake_blocked_work_for_dependencies(dependency_keys: set[str]) -> int:
    """Make rows ready only when every persisted exact dependency is satisfied."""

    if not dependency_keys:
        return 0
    now = timezone.now()
    woken = 0
    with transaction.atomic():
        candidates = IngestionWorkItem.objects.select_for_update().filter(
            status=IngestionWorkStatus.BLOCKED
        )
        for item in candidates:
            dependencies = set(item.dependency_keys or [])
            resolved = set(dependency_keys)
            for dependency in dependencies:
                if dependency.startswith("bioguide:"):
                    bioguide_id = dependency.removeprefix("bioguide:")
                    if Representative.objects.filter(bioguide_id=bioguide_id).exists():
                        resolved.add(dependency)
            if dependencies and dependencies.issubset(resolved):
                item.status = IngestionWorkStatus.PENDING
                item.available_at = now
                item.lease_expires_at = None
                item.dispatch_token = ""
                item.last_error = ""
                item.save(
                    update_fields=[
                        "status",
                        "available_at",
                        "lease_expires_at",
                        "dispatch_token",
                        "last_error",
                        "updated_at",
                    ]
                )
                woken += 1
    return woken


def _queue_document_download(document):
    source_fingerprint = hashlib.sha256(
        (document.source_url or "").encode("utf-8")
    ).hexdigest()
    return enqueue_ingestion_work(
        kind=WORK_KIND_DOCUMENT_DOWNLOAD,
        dedupe_key=f"{document.id}:{source_fingerprint}",
        source_updated_at=document.created_at or timezone.now(),
        payload_json={"document_id": document.id},
        jurisdiction=document.bill.jurisdiction,
        congress=document.bill.session,
    )


# Bill key format: "119-hr-1234" -> congress, bill_type, bill_number
def parse_bill_key(bill_key):
    parts = str(bill_key).strip().split("-")
    if len(parts) != 3:
        raise ValueError(f"Invalid bill_key: {bill_key}")
    congress = int(parts[0])
    bill_type = (parts[1] or "hr").lower()
    bill_number = parts[2]
    return congress, bill_type, bill_number


def bill_key(congress, bill_type, bill_number):
    return f"{congress}-{(bill_type or 'hr').lower()}-{bill_number}"


def bill_to_bill_key(bill):
    """Convert a stored Bill row (e.g. HR 123) into the Congress task key."""
    parts = str(bill.bill_number or "").strip().split()
    if len(parts) < 2:
        return None
    bill_type = parts[0].lower()
    if bill_type not in ("hr", "s"):
        return None
    return bill_key(bill.session, bill_type, parts[1])


def _ensure_utc_aware(dt):
    """Normalize DB or parsed datetimes so comparisons never mix naive vs aware."""
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, UTC)
    return dt


def _parse_congress_update_datetime(value):
    """Parse bill list updateDate (string or datetime); return UTC-aware or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
        except Exception:
            return None
    else:
        return None
    return _ensure_utc_aware(dt)


class CRSPlainTextParser(HTMLParser):
    """Tolerantly turn a CRS HTML summary into readable plain text."""

    BLOCK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li"}
    IGNORED_TAGS = {"script", "style"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.casefold()
        if tag in self.IGNORED_TAGS:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag == "li":
            self.parts.extend(("\n", "- "))
        elif tag in self.BLOCK_TAGS or tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag.casefold() in self.IGNORED_TAGS and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data):
        if not self._ignored_depth:
            self.parts.append(data)


def clean_crs_summary(value: object) -> str:
    """Return the complete CRS summary as normalized, safe plain text."""

    if not isinstance(value, str):
        return ""
    parser = CRSPlainTextParser()
    parser.feed(value)
    parser.close()
    return "\n".join(
        " ".join(line.split())
        for line in "".join(parser.parts).splitlines()
        if line.split()
    )


def _parse_congress_date(value: object) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


@dataclass(frozen=True)
class CRSSummaryRevision:
    text: str
    action_date: date | None
    version_code: str
    last_updated_at: datetime | None


def select_latest_crs_summary(
    items: Sequence[dict[str, object]],
) -> CRSSummaryRevision | None:
    """Select the newest usable CRS revision independent of version-code order."""

    revisions = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = clean_crs_summary(item.get("text"))
        if not text:
            continue
        revisions.append(
            CRSSummaryRevision(
                text=text,
                action_date=_parse_congress_date(item.get("actionDate")),
                version_code=str(item.get("versionCode") or ""),
                last_updated_at=_parse_congress_update_datetime(
                    item.get("lastSummaryUpdateDate") or item.get("updateDate")
                ),
            )
        )
    if not revisions:
        return None
    return max(
        revisions,
        key=lambda revision: (
            revision.action_date or date.min,
            revision.last_updated_at or datetime.min.replace(tzinfo=UTC),
            revision.version_code,
            revision.text,
        ),
    )


def stored_summary_revision(bill):
    return (
        bill.summary_action_date or date.min,
        bill.summary_last_updated_at or datetime.min.replace(tzinfo=UTC),
        bill.summary_version_code or "",
    )


def format_bill_number(bill_type, bill_number):
    """Store as e.g. HR 1234 for display/API consistency."""
    t = (bill_type or "hr").upper()
    if t == "HR":
        t = "HR"
    elif t == "S":
        t = "S"
    return f"{t} {bill_number}"


def compute_metadata_hash(
    status,
    title,
    summary,
    last_action_at,
    introduced_at=None,
    sponsor_id=None,
    source_api_id=None,
    summary_source="",
    summary_action_date=None,
    summary_version_code="",
    summary_last_updated_at=None,
):
    raw = "|".join(
        [
            (status or "").strip(),
            (title or "").strip(),
            (summary or "").strip(),
            str(last_action_at or ""),
            str(introduced_at or ""),
            str(sponsor_id or ""),
            (source_api_id or "").strip(),
            (summary_source or "").strip(),
            str(summary_action_date or ""),
            (summary_version_code or "").strip(),
            str(summary_last_updated_at or ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _infer_chamber(sponsor_blob):
    """Infer senate vs house from sponsor data when Congress API omits chamber."""
    name = sponsor_blob.get("fullName") or sponsor_blob.get("name") or ""
    if name.startswith("Sen.") or name.startswith("Sen "):
        return "senate"
    if name.startswith("Rep.") or name.startswith("Rep "):
        return "house"
    if sponsor_blob.get("district"):
        return "house"
    return (sponsor_blob.get("chamber") or "house").lower() or "house"


def get_or_create_representative_from_sponsor(sponsor_blob):
    """Get or create Representative from Congress API sponsor object."""
    if not sponsor_blob:
        return None
    bioguide_id = sponsor_blob.get("bioguideId") or sponsor_blob.get("bioguide_id")
    if not bioguide_id:
        return None
    name = sponsor_blob.get("fullName") or sponsor_blob.get("name") or ""
    raw_state = sponsor_blob.get("state")
    state = (raw_state or "")[:2]
    raw_party = sponsor_blob.get("party")
    party = (raw_party or "")[:50]
    chamber = _infer_chamber(sponsor_blob)
    raw_district = sponsor_blob.get("district")
    district = str(raw_district or "")[:10] or None
    chamber_is_supplied = bool(
        sponsor_blob.get("chamber")
        or name.startswith(("Sen.", "Sen ", "Rep.", "Rep "))
        or raw_district is not None
    )
    rep, created = Representative.objects.get_or_create(
        bioguide_id=bioguide_id,
        defaults={
            "name": name or bioguide_id,
            "chamber": chamber,
            "party": party or "",
            "state": state or "",
            "district": district,
        },
    )
    if not created:
        next_chamber = chamber if chamber_is_supplied else rep.chamber
        next_district = (
            district
            if raw_district is not None or next_chamber == "senate"
            else rep.district
        )
        updated_fields = []
        for field, value in {
            "name": name or rep.name,
            "chamber": next_chamber,
            "party": party if raw_party is not None else rep.party,
            "state": state if raw_state is not None else rep.state,
            "district": next_district,
        }.items():
            if getattr(rep, field) != value:
                setattr(rep, field, value)
                updated_fields.append(field)
        if updated_fields:
            rep.save(update_fields=updated_fields)
    return rep


def _normalize_member_chamber(value):
    chamber = str(value or "").strip().casefold()
    if chamber in {"house", "house of representatives"}:
        return "house"
    if chamber == "senate":
        return "senate"
    return ""


def _member_chamber(member):
    terms = member.get("terms") or []
    if isinstance(terms, dict):
        terms = terms.get("item") or terms.get("terms") or []
    if isinstance(terms, list):
        for term in reversed(terms):
            if isinstance(term, dict) and term.get("chamber"):
                chamber = _normalize_member_chamber(term["chamber"])
                if chamber:
                    return chamber
    return _normalize_member_chamber(member.get("chamber")) or "house"


def _member_party(member):
    party = member.get("partyName") or member.get("party")
    if party:
        return str(party)[:50]
    history = member.get("partyHistory") or []
    if isinstance(history, list):
        for entry in reversed(history):
            if isinstance(entry, dict) and entry.get("partyName"):
                return str(entry["partyName"])[:50]
    return ""


def _member_state_code(member):
    terms = member.get("terms") or []
    if isinstance(terms, dict):
        terms = terms.get("item") or terms.get("terms") or []
    if isinstance(terms, list):
        for term in reversed(terms):
            if not isinstance(term, dict):
                continue
            term_state_code = term.get("stateCode")
            if term_state_code:
                return state_code(term_state_code)
    return state_code(member.get("state"))


def _member_profile(summary, detail):
    member = dict(summary)
    member.update(detail or {})
    bioguide_id = member.get("bioguideId") or member.get("bioguide_id")
    if not bioguide_id:
        raise CongressAPIError("Congress member payload is missing bioguideId")
    first_name = str(member.get("firstName") or "")[:255]
    last_name = str(member.get("lastName") or member.get("lastname") or "")[:255]
    name = str(
        member.get("directOrderName")
        or member.get("fullName")
        or member.get("name")
        or " ".join(part for part in (first_name, last_name) if part)
        or bioguide_id
    )[:255]
    depiction = member.get("depiction") or {}
    image_url = depiction.get("imageUrl") if isinstance(depiction, dict) else None
    district = member.get("district")
    chamber = _member_chamber(member)
    return {
        "bioguide_id": str(bioguide_id)[:20],
        "name": name,
        "first_name": first_name,
        "last_name": last_name,
        "chamber": chamber if chamber in ("house", "senate") else "house",
        "party": _member_party(member),
        "state": _member_state_code(member),
        "district": str(district)[:10] if district not in (None, "") else None,
        "official_website_url": member.get("officialWebsiteUrl") or None,
        "image_url": image_url or None,
        "source_api_url": member.get("url") or None,
        "is_current": bool(member.get("currentMember", True)),
    }


def _member_terms(summary, detail):
    member = dict(summary)
    member.update(detail or {})
    if "terms" not in member:
        return None
    terms = member.get("terms") or []
    if isinstance(terms, dict):
        terms = terms.get("item") or terms.get("terms") or []
    if not isinstance(terms, list):
        raise CongressAPIError("Congress member terms payload is invalid")
    if not terms:
        return None
    parsed = []
    for term in terms:
        if not isinstance(term, dict):
            raise CongressAPIError("Congress member terms contain an invalid entry")
        chamber = _normalize_member_chamber(term.get("chamber"))
        try:
            start_year = int(term.get("startYear"))
            raw_end_year = term.get("endYear")
            end_year = int(raw_end_year) if raw_end_year not in (None, "") else None
        except (TypeError, ValueError) as exc:
            raise CongressAPIError(
                "Congress member term is missing a valid service year"
            ) from exc
        if (
            not chamber
            or start_year < 1789
            or (end_year is not None and end_year <= start_year)
        ):
            raise CongressAPIError(
                "Congress member term has an invalid service interval"
            )
        district = term.get("district")
        parsed.append(
            {
                "chamber": chamber,
                "state": state_code(term.get("stateCode") or member.get("state")),
                "district": (
                    str(district)[:10] if district not in (None, "") else None
                ),
                "member_type": str(term.get("memberType") or "")[:50],
                "start_date": date(start_year, 1, 3),
                "end_date": date(end_year, 1, 3) if end_year is not None else None,
            }
        )
    return parsed


def _replace_representative_terms(representative, terms):
    if terms is None:
        return
    retained_ids = []
    for values in terms:
        term, _ = RepresentativeTerm.objects.update_or_create(
            representative=representative,
            chamber=values["chamber"],
            start_date=values["start_date"],
            defaults={
                "state": values["state"],
                "district": values["district"],
                "member_type": values["member_type"],
                "end_date": values["end_date"],
            },
        )
        retained_ids.append(term.id)
    representative.service_terms.exclude(pk__in=retained_ids).delete()


def _process_representative_detail_impl(bioguide_id: str):
    """Upsert one profile only after proving the response identity is exact."""

    expected_id = str(bioguide_id).strip()
    detail = member_detail(expected_id)
    returned_id = str(
        detail.get("bioguideId") or detail.get("bioguide_id") or ""
    ).strip()
    if returned_id != expected_id:
        raise CongressAPIError(
            "Congress member detail identity did not match requested Bioguide ID"
        )
    summary = {"bioguideId": expected_id}
    profile = _member_profile(summary, detail)
    terms = _member_terms(summary, detail)
    with transaction.atomic():
        persisted_id = profile.pop("bioguide_id")
        representative, _ = Representative.objects.update_or_create(
            bioguide_id=persisted_id,
            defaults={**profile, "last_seen_at": timezone.now()},
        )
        _replace_representative_terms(representative, terms)
    woken = _wake_blocked_work_for_dependencies({f"bioguide:{expected_id}"})
    return {"bioguide_id": expected_id, "woken": woken}


@shared_task(
    autoretry_for=(CongressAPIError,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=2,
)
def sync_representatives(congress=None):
    """Synchronize the full current member roster without retiring on partial pulls."""
    active_congress = current_congress()
    if congress is None:
        congress = active_congress
    if congress != active_congress:
        raise ValueError(
            f"Representative roster sync only supports the current Congress ({active_congress})"
        )
    limit = 250
    offset = 0
    summaries = []
    while True:
        page = member_list(
            congress,
            current_member=True,
            limit=limit,
            offset=offset,
        )
        summaries.extend(page)
        if len(page) < limit:
            break
        offset += limit

    if not summaries:
        raise CongressAPIError(
            "Congress member roster was empty; refusing to retire members"
        )

    profiles = []
    for summary in summaries:
        if not isinstance(summary, dict):
            raise CongressAPIError(
                "Congress member list contained an invalid member payload"
            )
        bioguide_id = summary.get("bioguideId") or summary.get("bioguide_id")
        if not bioguide_id:
            raise CongressAPIError("Congress member list entry is missing bioguideId")
        expected_id = str(bioguide_id).strip()
        detail = member_detail(expected_id)
        returned_id = str(
            detail.get("bioguideId") or detail.get("bioguide_id") or ""
        ).strip()
        if returned_id != expected_id:
            raise CongressAPIError(
                "Congress member detail identity did not match requested Bioguide ID"
            )
        profiles.append(
            (
                _member_profile(summary, detail),
                _member_terms(summary, detail),
            )
        )

    now = timezone.now()
    created_count = 0
    updated_count = 0
    seen_ids = {profile["bioguide_id"] for profile, _terms in profiles}
    with transaction.atomic():
        for profile, terms in profiles:
            bioguide_id = profile.pop("bioguide_id")
            profile["last_seen_at"] = now
            representative, created = Representative.objects.update_or_create(
                bioguide_id=bioguide_id,
                defaults=profile,
            )
            _replace_representative_terms(representative, terms)
            created_count += int(created)
            updated_count += int(not created)
        Representative.objects.filter(is_current=True).exclude(
            bioguide_id__in=seen_ids
        ).update(is_current=False)

    try:
        sync_committee_memberships.delay()
    except Exception:
        # The roster is durable only after its own validated sync; a later
        # scheduled representative run will request it again if this handoff
        # fails while the broker is unavailable.
        logger.exception("sync_representatives: could not queue committee roster sync")

    return {
        "congress": congress,
        "members": len(profiles),
        "created": created_count,
        "updated": updated_count,
    }


@shared_task(
    bind=True,
    autoretry_for=(CommitteeRosterTransportError,),
    retry_backoff=True,
    retry_backoff_max=3600,
    max_retries=3,
)
def sync_committee_memberships(self, congress=None):
    """Atomically replace validated current House and Senate committee rosters."""

    from apps.congress.committee_sync import sync_committee_memberships as sync

    resolved_congress = current_congress() if congress is None else int(congress)
    try:
        results = sync(congress=resolved_congress)
    except CommitteeRosterError as exc:
        # Validation failures are immediately actionable. Transport failures
        # are recorded only after Celery's bounded retry budget is exhausted.
        if (
            not isinstance(exc, CommitteeRosterTransportError)
            or self.request.retries >= self.max_retries
        ):
            _record_task_failure(
                self.request.id,
                "apps.ingestion.tasks.sync_committee_memberships",
                (resolved_congress,),
                {},
                None,
                exc,
            )
        raise
    return [result.__dict__ for result in results]


@shared_task
def poll_congress(jurisdiction="federal", congress=None):
    """
    Discover updated Congress bills and persist them before advancing the cursor.

    The worker dispatcher is intentionally separate: a temporary broker outage
    cannot lose a discovered bill or force the cursor to stay behind forever.
    """
    if congress is None:
        congress = current_congress()
    logger.info(
        "poll_congress: starting jurisdiction=%s congress=%s", jurisdiction, congress
    )
    state, _ = IngestionState.objects.get_or_create(
        jurisdiction=jurisdiction,
        congress=congress,
        defaults={},
    )
    from_date_time = None
    if state.last_bill_update_seen_at:
        from_date_time = (
            _ensure_utc_aware(state.last_bill_update_seen_at) - CURSOR_OVERLAP
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        logger.info("poll_congress: incremental from_date_time=%s", from_date_time)
    else:
        logger.info("poll_congress: full fetch (no last_bill_update_seen_at)")
    bill_types = ["hr", "s"]
    discovered_bills = {}
    latest_update = _ensure_utc_aware(state.last_bill_update_seen_at)
    page_limit = 250
    for bt in bill_types:
        offset = 0
        previous_page_keys = None
        while True:
            try:
                items = bill_list(
                    congress,
                    bt,
                    from_date_time=from_date_time,
                    limit=page_limit,
                    offset=offset,
                )
            except CongressAPIError as e:
                logger.warning(
                    "poll_congress: bill_list failed congress=%s bill_type=%s offset=%s: %s",
                    congress,
                    bt,
                    offset,
                    e,
                )
                raise
            logger.info(
                "poll_congress: bill_type=%s offset=%s -> %s bills",
                bt,
                offset,
                len(items),
            )
            if not items:
                break
            page_keys = tuple(
                sorted(bill_key(b["congress"], b["type"], b["number"]) for b in items)
            )
            if offset > 0 and previous_page_keys == page_keys:
                raise CongressAPIError(
                    f"poll_congress: bill_type={bt} offset={offset} repeated same page "
                    "(API may not support offset); refusing to advance cursor"
                )
            previous_page_keys = page_keys
            for b in items:
                key = bill_key(b["congress"], b["type"], b["number"])
                ud = _parse_congress_update_datetime(b.get("updateDate"))
                source_updated_at = ud or UNKNOWN_SOURCE_UPDATED_AT
                prior_update = discovered_bills.get(key)
                if prior_update is None or source_updated_at > prior_update:
                    discovered_bills[key] = source_updated_at
                if ud and (latest_update is None or ud > latest_update):
                    latest_update = ud
            if len(items) < page_limit:
                break
            offset += page_limit
    now = timezone.now()
    created_count = 0
    with transaction.atomic():
        # Concurrent polls may replay the same overlap. The uniqueness key makes
        # that safe while this lock prevents either poll from moving the cursor
        # backward after the other has committed its durable discoveries.
        state = IngestionState.objects.select_for_update().get(pk=state.pk)
        for key, source_updated_at in discovered_bills.items():
            _, created = IngestionWorkItem.objects.get_or_create(
                kind="bill",
                dedupe_key=key,
                source_updated_at=source_updated_at,
                defaults={
                    "jurisdiction": jurisdiction,
                    "congress": congress,
                    "payload_json": {"bill_key": key},
                    "available_at": now,
                },
            )
            created_count += int(created)
        state.last_polled_at = now
        if latest_update and (
            state.last_bill_update_seen_at is None
            or latest_update > _ensure_utc_aware(state.last_bill_update_seen_at)
        ):
            state.last_bill_update_seen_at = latest_update
        state.save(update_fields=["last_polled_at", "last_bill_update_seen_at"])

    try:
        dispatch_ingestion_work.delay()
    except Exception:
        # Beat will pick up pending rows even if the broker is unavailable now.
        logger.exception("poll_congress: could not trigger ingestion work dispatcher")

    logger.info(
        "poll_congress: done discovered=%s created=%s last_bill_update_seen_at=%s",
        len(discovered_bills),
        created_count,
        latest_update,
    )
    return {
        "congress": congress,
        "discovered": len(discovered_bills),
        "created": created_count,
    }


@shared_task(
    autoretry_for=(CongressAPIError,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=2,
)
def discover_roll_calls(congress=None):
    """Durably discover every current Congress chamber/session roll call."""

    runtime_congress = current_congress()
    active_congress = runtime_congress if congress is None else int(congress)
    if active_congress > runtime_congress:
        raise ValueError("Roll-call discovery cannot run for a future Congress")
    session_count = (
        current_congress_session() if active_congress == runtime_congress else 2
    )
    created_count = 0
    for session_number in range(1, session_count + 1):
        for source, chamber in (
            (HouseVoteSource(), "house"),
            (SenateVoteSource(), "senate"),
        ):
            while True:
                state, _ = RollCallIngestionState.objects.get_or_create(
                    congress=active_congress,
                    chamber=chamber,
                    session_number=session_number,
                )
                was_exhausted = state.source_exhausted_at is not None
                cursor = "" if was_exhausted else state.next_page_or_roll
                page = source.discover_page(
                    congress=active_congress,
                    session_number=session_number,
                    cursor=cursor,
                )
                page_updated_at = max(
                    (reference.source_updated_at for reference in page.refs),
                    default=None,
                )
                now = timezone.now()
                retry_with_new_state = False
                with transaction.atomic():
                    locked_state = (
                        RollCallIngestionState.objects.select_for_update().get(
                            pk=state.pk
                        )
                    )
                    if (
                        locked_state.source_exhausted_at is not None
                    ) != was_exhausted or (
                        not was_exhausted and locked_state.next_page_or_roll != cursor
                    ):
                        retry_with_new_state = True
                    elif (
                        was_exhausted
                        and page_updated_at is not None
                        and locked_state.source_updated_at is not None
                        and page_updated_at <= locked_state.source_updated_at
                    ):
                        locked_state.last_polled_at = now
                        locked_state.save(update_fields=["last_polled_at"])
                    else:
                        page_created = 0
                        for reference in page.refs:
                            _, created = IngestionWorkItem.objects.get_or_create(
                                kind=WORK_KIND_ROLL_CALL_VOTE,
                                dedupe_key=(
                                    f"vote:{reference.congress}:{reference.chamber}:"
                                    f"{reference.session_number}:{reference.roll_number}"
                                ),
                                source_updated_at=reference.source_updated_at,
                                defaults={
                                    "congress": reference.congress,
                                    "payload_json": {
                                        "congress": reference.congress,
                                        "chamber": reference.chamber,
                                        "session_number": reference.session_number,
                                        "roll_number": reference.roll_number,
                                        "source_url": reference.source_url,
                                    },
                                    "available_at": now,
                                },
                            )
                            page_created += int(created)
                        # An inserted head item shifts stable rows into later
                        # offset pages. Replaying such a page creates no work,
                        # but its persisted next cursor is still required to
                        # reach the authoritative end without a gap.
                        prefix = f"vote:{active_congress}:{chamber}:{session_number}:"
                        locked_state.discovered_roll_count = (
                            IngestionWorkItem.objects.filter(
                                kind=WORK_KIND_ROLL_CALL_VOTE,
                                dedupe_key__startswith=prefix,
                            )
                            .values("dedupe_key")
                            .distinct()
                            .count()
                        )
                        locked_state.next_page_or_roll = page.next_cursor or ""
                        locked_state.source_exhausted_at = (
                            now if page.next_cursor is None else None
                        )
                        if page_updated_at is not None:
                            locked_state.source_updated_at = max(
                                item
                                for item in (
                                    locked_state.source_updated_at,
                                    page_updated_at,
                                )
                                if item is not None
                            )
                        locked_state.last_polled_at = now
                        locked_state.save()
                        created_count += page_created
                if retry_with_new_state:
                    continue
                if was_exhausted or page.next_cursor is None:
                    break
    if created_count:
        try:
            dispatch_ingestion_work.delay()
        except Exception:
            logger.exception("discover_roll_calls: could not wake the dispatcher")
    return {"congress": active_congress, "created": created_count}


def _retry_delay(attempt_count):
    """Bound exponential delay for persistent ingestion retries."""
    return timedelta(seconds=min(60 * (2 ** max(attempt_count - 1, 0)), 3600))


def _tracked_refresh_bucket(now):
    interval_seconds = int(TRACKED_REFRESH_INTERVAL.total_seconds())
    timestamp = int(_ensure_utc_aware(now).timestamp())
    return datetime.fromtimestamp(
        timestamp - (timestamp % interval_seconds),
        tz=UTC,
    )


@shared_task
def dispatch_ingestion_work(batch_size=100):
    """Lease bounded, priority-ordered durable work and submit it to Celery."""
    now = timezone.now()
    leased_items = []
    with transaction.atomic():
        # Lock one stable row before counting in-flight leases so concurrent
        # dispatcher wakeups cannot each lease a full batch. Rows beyond the
        # cap remain visibly pending and are selected by priority next time.
        IngestionWorkItem.objects.select_for_update().order_by("id").first()
        in_flight = IngestionWorkItem.objects.filter(
            status=IngestionWorkStatus.DISPATCHED
        ).count()
        capacity = max(MAX_DISPATCHED_INGESTION_WORK - in_flight, 0)
        candidates = []
        if capacity:
            candidates = list(
                IngestionWorkItem.objects.select_for_update(skip_locked=True)
                .filter(
                    status=IngestionWorkStatus.PENDING,
                    available_at__lte=now,
                )
                .order_by(_work_dispatch_priority(), "available_at", "id")[
                    : min(batch_size, capacity)
                ]
            )
        for work_item in candidates:
            work_item.status = IngestionWorkStatus.DISPATCHED
            work_item.lease_expires_at = now + WORK_LEASE_DURATION
            work_item.celery_task_id = ""
            work_item.dispatch_token = uuid.uuid4().hex
            work_item.save(
                update_fields=[
                    "status",
                    "lease_expires_at",
                    "celery_task_id",
                    "dispatch_token",
                    "updated_at",
                ]
            )
            leased_items.append((work_item.id, work_item.dispatch_token))

    dispatched = 0
    for work_item_id, dispatch_token in leased_items:
        try:
            result = process_ingestion_work_item.apply_async(
                args=[work_item_id, dispatch_token]
            )
        except Exception as exc:
            # Leave it ready for the next dispatcher pass instead of dropping it.
            IngestionWorkItem.objects.filter(
                pk=work_item_id,
                status=IngestionWorkStatus.DISPATCHED,
                dispatch_token=dispatch_token,
            ).update(
                status=IngestionWorkStatus.PENDING,
                available_at=timezone.now() + timedelta(seconds=30),
                lease_expires_at=None,
                dispatch_token="",
                last_error=str(exc)[:10000],
            )
            logger.exception(
                "dispatch_ingestion_work: could not enqueue work_item=%s",
                work_item_id,
            )
            continue

        updated = IngestionWorkItem.objects.filter(
            pk=work_item_id,
            status=IngestionWorkStatus.DISPATCHED,
            dispatch_token=dispatch_token,
        ).update(celery_task_id=getattr(result, "id", "") or "")
        dispatched += int(bool(updated))

    return {"dispatched": dispatched}


@shared_task(
    bind=True,
    # Requests also use connection/read deadlines, but this outer guard makes
    # a stuck library call retryable instead of pinning a prefork worker.
    soft_time_limit=DURABLE_WORK_SOFT_TIME_LIMIT_SECONDS,
    time_limit=DURABLE_WORK_TIME_LIMIT_SECONDS,
)
def process_ingestion_work_item(self, work_item_id, dispatch_token=None):
    """Execute one durable work item and persist its terminal or retry state."""
    now = timezone.now()
    claimed_dispatch_token = ""
    claimed_payload_json = None
    with transaction.atomic():
        work_item = (
            IngestionWorkItem.objects.select_for_update()
            .filter(pk=work_item_id)
            .first()
        )
        if work_item is None:
            return {"work_item_id": work_item_id, "status": "missing"}
        if work_item.status in (
            IngestionWorkStatus.SUCCEEDED,
            IngestionWorkStatus.DEAD,
            IngestionWorkStatus.BLOCKED,
        ):
            return {"work_item_id": work_item.id, "status": work_item.status}
        if dispatch_token and work_item.dispatch_token != dispatch_token:
            return {"work_item_id": work_item.id, "status": "superseded"}
        if work_item.status == IngestionWorkStatus.PROCESSING:
            return {"work_item_id": work_item.id, "status": "processing"}
        if (
            work_item.status == IngestionWorkStatus.PENDING
            and work_item.available_at > now
        ):
            return {"work_item_id": work_item.id, "status": "not_ready"}

        work_item.status = IngestionWorkStatus.PROCESSING
        work_item.attempt_count += 1
        work_item.lease_expires_at = now + WORK_LEASE_DURATION
        work_item.celery_task_id = self.request.id or work_item.celery_task_id
        claimed_dispatch_token = work_item.dispatch_token
        claimed_payload_json = deepcopy(work_item.payload_json)
        work_item.save(
            update_fields=[
                "status",
                "attempt_count",
                "lease_expires_at",
                "celery_task_id",
                "updated_at",
            ]
        )

    try:
        _process_durable_work(work_item)
    except BlockedWork as exc:
        with transaction.atomic():
            work_item = IngestionWorkItem.objects.select_for_update().get(
                pk=work_item_id
            )
            if (
                work_item.status != IngestionWorkStatus.PROCESSING
                or work_item.dispatch_token != claimed_dispatch_token
            ):
                return {"work_item_id": work_item.id, "status": "superseded"}
            work_item.status = IngestionWorkStatus.BLOCKED
            work_item.attempt_count = max(work_item.attempt_count - 1, 0)
            work_item.dependency_keys = exc.dependency_keys
            work_item.lease_expires_at = None
            work_item.dispatch_token = ""
            work_item.last_error = exc.reason
            work_item.save(
                update_fields=[
                    "status",
                    "attempt_count",
                    "dependency_keys",
                    "lease_expires_at",
                    "dispatch_token",
                    "last_error",
                    "updated_at",
                ]
            )
        return {"work_item_id": work_item_id, "status": "blocked"}
    except Exception as exc:
        error_message = str(exc)[:10000]
        requeued = False
        with transaction.atomic():
            work_item = IngestionWorkItem.objects.select_for_update().get(
                pk=work_item_id
            )
            if (
                work_item.status != IngestionWorkStatus.PROCESSING
                or work_item.dispatch_token != claimed_dispatch_token
            ):
                return {"work_item_id": work_item.id, "status": "superseded"}
            if work_item.payload_json != claimed_payload_json:
                # The failure belongs to the stale claim, not the newer work
                # payload that arrived while it was executing.
                work_item.status = IngestionWorkStatus.PENDING
                work_item.attempt_count = 0
                work_item.available_at = timezone.now()
                work_item.lease_expires_at = None
                work_item.dispatch_token = ""
                work_item.completed_at = None
                work_item.last_error = ""
                work_item.save(
                    update_fields=[
                        "status",
                        "attempt_count",
                        "available_at",
                        "lease_expires_at",
                        "dispatch_token",
                        "completed_at",
                        "last_error",
                        "updated_at",
                    ]
                )
                requeued = True
            elif isinstance(exc, DocumentValidationError) or (
                work_item.attempt_count >= MAX_INGESTION_WORK_ATTEMPTS
            ):
                work_item.status = IngestionWorkStatus.DEAD
                work_item.lease_expires_at = None
                work_item.dispatch_token = ""
                work_item.last_error = error_message
                work_item.save(
                    update_fields=[
                        "status",
                        "lease_expires_at",
                        "dispatch_token",
                        "last_error",
                        "updated_at",
                    ]
                )
                _record_task_failure(
                    self.request.id,
                    "process_ingestion_work_item",
                    (work_item_id,),
                    {},
                    None,
                    exc,
                    work_item=work_item,
                )
                return {"work_item_id": work_item.id, "status": "dead"}

            elif not requeued:
                work_item.status = IngestionWorkStatus.PENDING
                work_item.available_at = timezone.now() + _retry_delay(
                    work_item.attempt_count
                )
                work_item.lease_expires_at = None
                work_item.dispatch_token = ""
                work_item.last_error = error_message
                work_item.save(
                    update_fields=[
                        "status",
                        "available_at",
                        "lease_expires_at",
                        "dispatch_token",
                        "last_error",
                        "updated_at",
                    ]
                )
        if requeued:
            try:
                dispatch_ingestion_work.delay()
            except Exception:
                logger.exception(
                    "process_ingestion_work_item: could not re-dispatch revised work_item=%s",
                    work_item_id,
                )
            return {"work_item_id": work_item_id, "status": "requeued"}
        logger.warning(
            "process_ingestion_work_item: retrying work_item=%s attempt=%s: %s",
            work_item_id,
            work_item.attempt_count,
            exc,
        )
        return {"work_item_id": work_item_id, "status": "retrying"}

    with transaction.atomic():
        work_item = IngestionWorkItem.objects.select_for_update().get(pk=work_item_id)
        if (
            work_item.status != IngestionWorkStatus.PROCESSING
            or work_item.dispatch_token != claimed_dispatch_token
        ):
            return {"work_item_id": work_item.id, "status": "superseded"}
        if work_item.payload_json != claimed_payload_json:
            work_item.status = IngestionWorkStatus.PENDING
            work_item.attempt_count = 0
            work_item.available_at = timezone.now()
            work_item.lease_expires_at = None
            work_item.dispatch_token = ""
            work_item.completed_at = None
            work_item.last_error = ""
            work_item.save(
                update_fields=[
                    "status",
                    "attempt_count",
                    "available_at",
                    "lease_expires_at",
                    "dispatch_token",
                    "completed_at",
                    "last_error",
                    "updated_at",
                ]
            )
            requeued = True
        else:
            requeued = False
        if not requeued:
            work_item.status = IngestionWorkStatus.SUCCEEDED
            work_item.lease_expires_at = None
            work_item.dispatch_token = ""
            work_item.completed_at = timezone.now()
            work_item.last_error = ""
            work_item.save(
                update_fields=[
                    "status",
                    "lease_expires_at",
                    "dispatch_token",
                    "completed_at",
                    "last_error",
                    "updated_at",
                ]
            )
    if requeued:
        try:
            dispatch_ingestion_work.delay()
        except Exception:
            logger.exception(
                "process_ingestion_work_item: could not dispatch revised work_item=%s",
                work_item_id,
            )
        return {"work_item_id": work_item_id, "status": "requeued"}
    return {"work_item_id": work_item_id, "status": "succeeded"}


def _process_durable_work(work_item):
    """Run one durable pipeline stage without publishing another broker message."""
    payload = work_item.payload_json
    if work_item.kind == WORK_KIND_BILL:
        bill_key_str = payload.get("bill_key")
        if not bill_key_str:
            raise ValueError("Bill ingestion work is missing payload_json.bill_key")
        return _process_bill_impl(bill_key_str)
    if work_item.kind == WORK_KIND_BILL_VERSIONS:
        return _process_bill_versions_impl(payload["bill_id"])
    if work_item.kind == WORK_KIND_BILL_VOTES:
        return _process_bill_votes_impl(payload["bill_id"])
    if work_item.kind == WORK_KIND_BILL_RELATIONSHIPS:
        from apps.congress.relationship_sync import sync_bill_relationships

        return sync_bill_relationships(bill_id=payload["bill_id"])
    if work_item.kind == WORK_KIND_REPRESENTATIVE_DETAIL:
        return _process_representative_detail_impl(payload["bioguide_id"])
    if work_item.kind == WORK_KIND_ROLL_CALL_VOTE:
        return _process_roll_call_vote_impl(work_item)
    if work_item.kind == WORK_KIND_DOCUMENT_DOWNLOAD:
        return _download_document_impl(payload["document_id"])

    # Import lazily to avoid loading the legislation task module while Celery
    # discovers ingestion tasks.
    from apps.legislation import tasks as legislation_tasks

    if work_item.kind == legislation_tasks.WORK_KIND_DOCUMENT_CONTRACT:
        return legislation_tasks._generate_contract_impl(
            payload["document_id"],
            reextract_source=bool(payload.get("reextract_source")),
            generation_reason=payload.get("generation_reason", "ingestion"),
            extractor_version=payload.get("extractor_version"),
        )
    if work_item.kind == legislation_tasks.WORK_KIND_METADATA_CONTRACT:
        return legislation_tasks._generate_contract_for_bill_impl(payload["bill_id"])
    if work_item.kind == legislation_tasks.WORK_KIND_TOPIC_UPDATE:
        return legislation_tasks._update_topics_impl(
            contract_id=payload.get("contract_id"),
            bill_id=payload.get("bill_id"),
            generation_reason=payload.get("generation_reason", "ingestion"),
        )
    if work_item.kind == legislation_tasks.WORK_KIND_SIMILARITY:
        return legislation_tasks._schedule_similarity_for_bill_impl(payload["bill_id"])
    if work_item.kind == legislation_tasks.WORK_KIND_SEARCH_INDEX:
        from apps.legislation.search_index import (
            latest_search_index_at,
            rebuild_bill_search_index,
        )

        indexed_at = latest_search_index_at(bill_id=payload["bill_id"])
        if indexed_at is not None and indexed_at >= work_item.source_updated_at:
            return {
                "bill_id": payload["bill_id"],
                "stale": True,
                "changed": False,
            }
        result = rebuild_bill_search_index(bill_id=payload["bill_id"])
        return {
            "bill_id": result.bill_id,
            "stale": False,
            "changed": result.changed,
            "chunk_count": result.chunk_count,
        }
    raise ValueError(f"Unsupported ingestion work kind: {work_item.kind}")


@shared_task
def recover_stale_ingestion_work():
    """Release worker leases left behind by a crash or a broker delivery loss."""
    now = timezone.now()
    with transaction.atomic():
        stale_items = list(
            IngestionWorkItem.objects.select_for_update().filter(
                status__in=[
                    IngestionWorkStatus.DISPATCHED,
                    IngestionWorkStatus.PROCESSING,
                ],
                lease_expires_at__lt=now,
            )
        )
        exhausted_items = [
            item
            for item in stale_items
            if item.attempt_count >= MAX_INGESTION_WORK_ATTEMPTS
        ]
        for work_item in exhausted_items:
            error_message = (
                "Ingestion work lease expired after exhausting the retry budget"
            )
            work_item.status = IngestionWorkStatus.DEAD
            work_item.lease_expires_at = None
            work_item.dispatch_token = ""
            work_item.last_error = error_message
            work_item.save(
                update_fields=[
                    "status",
                    "lease_expires_at",
                    "dispatch_token",
                    "last_error",
                    "updated_at",
                ]
            )
            _record_task_failure(
                work_item.celery_task_id,
                "process_ingestion_work_item",
                (work_item.id,),
                {},
                None,
                RuntimeError(error_message),
                work_item=work_item,
            )

        recovered = len(stale_items) - len(exhausted_items)
        if recovered:
            IngestionWorkItem.objects.filter(
                pk__in=[
                    item.id
                    for item in stale_items
                    if item.attempt_count < MAX_INGESTION_WORK_ATTEMPTS
                ]
            ).update(
                status=IngestionWorkStatus.PENDING,
                available_at=now,
                lease_expires_at=None,
                celery_task_id="",
                dispatch_token="",
            )
    return {"recovered": recovered}


@shared_task
def poll_tracked_bills():
    """
    Refresh bills relevant to user tracking.

    This does not discover new bills by topic/legislator. The broad poll_congress
    schedule handles discovery; this task gives already-tracked corpus rows a
    more direct refresh path.
    """
    direct_bill_ids = TrackedBill.objects.values_list("bill_id", flat=True)
    topic_ids = TrackedTopic.objects.values_list("topic_id", flat=True)
    representative_ids = TrackedLegislator.objects.values_list(
        "representative_id",
        flat=True,
    )
    bills = (
        Bill.objects.filter(
            Q(id__in=direct_bill_ids)
            | Q(bill_topics__topic_id__in=topic_ids)
            | Q(sponsor_id__in=representative_ids)
        )
        .only("id", "jurisdiction", "session", "bill_number")
        .order_by("id")
        .distinct()
    )
    now = timezone.now()
    source_updated_at = _tracked_refresh_bucket(now)
    created_count = 0
    with transaction.atomic():
        for bill in bills:
            key = bill_to_bill_key(bill)
            if not key:
                continue
            _, created = IngestionWorkItem.objects.get_or_create(
                kind="bill",
                dedupe_key=key,
                source_updated_at=source_updated_at,
                defaults={
                    "jurisdiction": bill.jurisdiction,
                    "congress": bill.session,
                    "payload_json": {"bill_key": key},
                    "available_at": now,
                },
            )
            created_count += int(created)

    if created_count:
        try:
            dispatch_ingestion_work.delay()
        except Exception:
            logger.exception(
                "poll_tracked_bills: could not trigger ingestion work dispatcher"
            )

    logger.info("poll_tracked_bills: enqueued=%s", created_count)
    return {"enqueued": created_count}


def _record_task_failure(
    task_id, task_name, args, kwargs, bill_id, exc, work_item=None
):
    try:
        IngestionTaskFailure.objects.create(
            task_id=task_id or "",
            work_item=work_item,
            bill_id=bill_id,
            task_name=task_name or "",
            args_json={"args": list(args), "kwargs": kwargs},
            error_message=str(exc)[:10000],
        )
    except Exception as e:
        logger.exception("Failed to record IngestionTaskFailure: %s", e)


@shared_task(
    bind=True,
    autoretry_for=(CongressAPIError,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=2,
)
def process_bill(self, bill_key_str):
    """
    Fetch bill detail, update Bill and ChangeLog, enqueue process_bill_versions and process_bill_votes.
    Short-circuits if metadata_hash unchanged.
    """
    bill_id = None
    try:
        return _process_bill_impl(bill_key_str)
    except Exception as exc:
        logger.exception(
            "process_bill failed: bill_key=%s retries=%s: %s",
            bill_key_str,
            self.request.retries,
            exc,
        )
        if (
            not isinstance(exc, CongressAPIError)
            or self.request.retries >= self.max_retries
        ):
            if isinstance(bill_key_str, str):
                try:
                    congress, bill_type, bill_number = parse_bill_key(bill_key_str)
                    bn = format_bill_number(bill_type, bill_number)
                    b = Bill.objects.filter(session=congress, bill_number=bn).first()
                    if b:
                        bill_id = b.id
                except Exception:
                    pass
            _record_task_failure(
                self.request.id, "process_bill", (bill_key_str,), {}, bill_id, exc
            )
        raise


def _process_bill_impl(bill_key_str):
    logger.info("process_bill: starting bill_key=%s", bill_key_str)
    congress, bill_type, bill_number = parse_bill_key(bill_key_str)
    bill_number_display = format_bill_number(bill_type, bill_number)
    detail = bill_detail(congress, bill_type, bill_number)
    sponsor_blob = None
    sponsors = detail.get("sponsors") or []
    if sponsors:
        sponsor_blob = sponsors[0] if isinstance(sponsors[0], dict) else None
    if not sponsor_blob and isinstance(detail.get("sponsors"), list):
        for s in detail.get("sponsors", []):
            if isinstance(s, dict):
                sponsor_blob = s
                break
    sponsor = get_or_create_representative_from_sponsor(sponsor_blob)
    latest_action = detail.get("latestAction") or {}
    if isinstance(latest_action, dict):
        action_date = latest_action.get("actionDate") or latest_action.get("date")
        action_text = latest_action.get("text") or latest_action.get("actionText") or ""
    else:
        action_date = None
        action_text = str(detail.get("latestAction", ""))
    status = (action_text or detail.get("status") or "")[:100]
    title = (detail.get("title") or "")[:10000]
    source_metadata_summary = (detail.get("summary") or "")[:10000] or None
    crs_revision = select_latest_crs_summary(
        bill_summaries(congress, bill_type, bill_number)
    )
    summary = crs_revision.text if crs_revision else source_metadata_summary
    summary_source = (
        "crs"
        if crs_revision
        else ("source_metadata" if source_metadata_summary else "")
    )
    summary_action_date = crs_revision.action_date if crs_revision else None
    summary_version_code = crs_revision.version_code if crs_revision else ""
    summary_last_updated_at = crs_revision.last_updated_at if crs_revision else None
    introduced_at = None
    if detail.get("introducedDate"):
        try:
            introduced_at = datetime.strptime(
                detail["introducedDate"][:10], "%Y-%m-%d"
            ).date()
        except Exception:
            pass
    last_action_at = None
    if action_date:
        try:
            last_action_at = datetime.strptime(str(action_date)[:10], "%Y-%m-%d")
            if timezone.is_naive(last_action_at):
                last_action_at = timezone.make_aware(last_action_at)
        except Exception:
            pass
    source_api_id = str(detail.get("url") or bill_key_str)
    metadata_hash = compute_metadata_hash(
        status,
        title,
        summary,
        last_action_at,
        introduced_at,
        sponsor.id if sponsor else None,
        source_api_id,
        summary_source,
        summary_action_date,
        summary_version_code,
        summary_last_updated_at,
    )
    with transaction.atomic():
        bill, created = Bill.objects.get_or_create(
            session=congress,
            bill_number=bill_number_display,
            defaults={
                "jurisdiction": "federal",
                "title": title or bill_number_display,
                "summary": summary,
                "summary_source": summary_source,
                "summary_action_date": summary_action_date,
                "summary_version_code": summary_version_code,
                "summary_last_updated_at": summary_last_updated_at,
                "status": status or "Unknown",
                "processing_status": ProcessingStatus.PROCESSING,
                "introduced_at": introduced_at,
                "last_action_at": last_action_at,
                "sponsor": sponsor,
                "source_api_id": source_api_id,
                "metadata_hash": metadata_hash,
            },
        )
        if not created:
            target_summary = bill.summary
            target_summary_source = bill.summary_source
            target_summary_action_date = bill.summary_action_date
            target_summary_version_code = bill.summary_version_code
            target_summary_last_updated_at = bill.summary_last_updated_at
            if crs_revision:
                candidate_revision = (
                    crs_revision.action_date or date.min,
                    crs_revision.last_updated_at or datetime.min.replace(tzinfo=UTC),
                    crs_revision.version_code,
                )
                if (
                    bill.summary_source != "crs"
                    or candidate_revision > stored_summary_revision(bill)
                ):
                    target_summary = crs_revision.text
                    target_summary_source = "crs"
                    target_summary_action_date = crs_revision.action_date
                    target_summary_version_code = crs_revision.version_code
                    target_summary_last_updated_at = crs_revision.last_updated_at
            elif source_metadata_summary and bill.summary_source != "crs":
                target_summary = source_metadata_summary
                target_summary_source = "source_metadata"
                target_summary_action_date = None
                target_summary_version_code = ""
                target_summary_last_updated_at = None

            metadata_hash = compute_metadata_hash(
                status,
                title,
                target_summary,
                last_action_at,
                introduced_at,
                sponsor.id if sponsor else None,
                source_api_id,
                target_summary_source,
                target_summary_action_date,
                target_summary_version_code,
                target_summary_last_updated_at,
            )
            if bill.metadata_hash == metadata_hash:
                logger.info(
                    "process_bill: unchanged (hash match) bill_id=%s bill_key=%s",
                    bill.id,
                    bill_key_str,
                )
                # Still run the document pipeline if we never stored files. Votes are
                # refreshed independently because vote corrections can arrive without a
                # bill metadata change.
                needs_doc_pipeline = (
                    not bill.documents.exists()
                    or bill.documents.filter(downloaded_at__isnull=True).exists()
                )
                bill.processing_status = (
                    ProcessingStatus.PROCESSING
                    if needs_doc_pipeline
                    else ProcessingStatus.COMPLETE
                )
                bill.save(update_fields=["processing_status"])
                try:
                    if needs_doc_pipeline:
                        _queue_bill_stage(bill, WORK_KIND_BILL_VERSIONS)
                        logger.info(
                            "process_bill: enqueued versions (documents missing or not downloaded) bill_id=%s",
                            bill.id,
                        )
                    _queue_bill_stage(bill, WORK_KIND_BILL_VOTES)
                    _queue_bill_relationships(bill)
                except Exception:
                    logger.exception(
                        "process_bill: failed to enqueue versions/votes bill_id=%s",
                        bill.id,
                    )
                    raise
                # Topics are a required bill projection, not a best-effort
                # downstream enrichment. Persist them before this bill work is
                # allowed to succeed; document contracts may refine them later.
                from apps.legislation.tasks import _update_topics_impl

                _update_topics_impl(bill_id=bill.id)
                fulfill_tracking_requests_for_bill(
                    bill,
                    bill_type=bill_type,
                    bill_number=bill_number,
                )
                return {"bill_id": bill.id, "unchanged": True}
            before_metadata = snapshot_bill_metadata(bill)
            bill.processing_status = ProcessingStatus.PROCESSING
            bill.title = title or bill.title
            bill.summary = target_summary
            bill.summary_source = target_summary_source
            bill.summary_action_date = target_summary_action_date
            bill.summary_version_code = target_summary_version_code
            bill.summary_last_updated_at = target_summary_last_updated_at
            bill.status = status or bill.status
            bill.introduced_at = (
                introduced_at if introduced_at is not None else bill.introduced_at
            )
            bill.last_action_at = (
                last_action_at if last_action_at is not None else bill.last_action_at
            )
            bill.sponsor = sponsor if sponsor is not None else bill.sponsor
            bill.source_api_id = source_api_id
            bill.metadata_hash = metadata_hash
            bill.save()
            for pending_change in diff_bill_metadata(
                before_metadata,
                snapshot_bill_metadata(bill),
            ):
                record_bill_change(
                    bill=bill,
                    change_type=pending_change.change_type,
                    old_value=pending_change.old_value,
                    new_value=pending_change.new_value,
                    event_key=(
                        f"bill:metadata:{bill.metadata_hash}:"
                        f"{pending_change.change_type}"
                    ),
                )
        else:
            record_bill_change(
                bill=bill,
                change_type="bill_created",
                old_value=None,
                new_value={"status": status, "title": title},
                event_key=f"bill:create:{bill.id}",
            )
        # Topics are a required bill projection, not a best-effort downstream
        # enrichment. Persist them before this bill work is allowed to succeed;
        # document contracts may refine them later.
        from apps.legislation.tasks import _update_topics_impl

        _update_topics_impl(bill_id=bill.id)
        fulfill_tracking_requests_for_bill(
            bill,
            bill_type=bill_type,
            bill_number=bill_number,
        )
    try:
        _queue_bill_stage(bill, WORK_KIND_BILL_VERSIONS)
        _queue_bill_stage(bill, WORK_KIND_BILL_VOTES)
        _queue_bill_relationships(bill)
        from apps.legislation.tasks import enqueue_search_index

        enqueue_search_index(bill)
    except Exception:
        bill.processing_status = ProcessingStatus.FAILED
        bill.save(update_fields=["processing_status"])
        raise
    logger.info(
        "process_bill: success bill_id=%s bill_key=%s (updated, enqueued versions+votes)",
        bill.id,
        bill_key_str,
    )
    return {"bill_id": bill.id, "unchanged": False}


@shared_task(
    bind=True,
    autoretry_for=(CongressAPIError,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=2,
)
def process_bill_versions(self, bill_id):
    return _process_bill_versions_impl(bill_id)


def _process_bill_versions_impl(bill_id):
    """Fetch bill text versions, create/update BillDocument, enqueue download_document."""
    logger.info("process_bill_versions: starting bill_id=%s", bill_id)
    bill = Bill.objects.filter(pk=bill_id).first()
    if not bill:
        logger.warning("process_bill_versions: bill_id=%s not found", bill_id)
        return
    congress = bill.session
    # bill_number is "HR 1234" -> type hr, number 1234
    parts = bill.bill_number.strip().split()
    if len(parts) >= 2:
        bill_type = parts[0].lower().replace("hr", "hr").replace("s", "s")
        if bill_type == "hr" or bill_type == "s":
            pass
        else:
            bill_type = "hr"
        num = parts[1]
    else:
        bill_type = "hr"
        num = bill.bill_number.replace(" ", "").strip() or "0"
    try:
        versions = bill_text_list(congress, bill_type, num)
    except CongressAPIError as e:
        logger.warning(
            "process_bill_versions: bill_id=%s bill_text_list failed: %s", bill_id, e
        )
        raise
    if not versions:
        logger.info("process_bill_versions: bill_id=%s no versions returned", bill_id)
        from apps.legislation.tasks import enqueue_metadata_contract

        enqueue_metadata_contract(bill)
        return {"bill_id": bill_id, "versions": 0, "fallback_enqueued": True}
    # Mark one as active (e.g. last)
    for i, v in enumerate(versions):
        label = v.get("version_label") or v.get("url") or f"v{i}"
        url = v.get("url") or ""
        source_order = v.get("source_order", i + 1)
        try:
            source_order = int(source_order)
        except (TypeError, ValueError) as exc:
            raise CongressAPIError(
                "Congress bill text version has an invalid source order"
            ) from exc
        if source_order < 1:
            raise CongressAPIError(
                "Congress bill text version has an invalid source order"
            )
        doc, created = BillDocument.objects.get_or_create(
            bill=bill,
            version_label=label[:50],
            defaults={
                "source_url": url or None,
                "source_order": source_order,
                "is_active_version": False,
            },
        )
        source_url_changed = not created and (doc.source_url or "") != url
        source_order_changed = not created and doc.source_order != source_order
        update_fields = []
        if source_url_changed:
            doc.source_url = url or None
            update_fields.append("source_url")
        if source_order_changed:
            doc.source_order = source_order
            update_fields.append("source_order")
        if update_fields:
            doc.save(update_fields=update_fields)
        if i == len(versions) - 1:
            BillDocument.objects.filter(bill=bill).update(is_active_version=False)
            doc.is_active_version = True
            doc.save(update_fields=["is_active_version"])
        needs_download = (
            created
            or source_url_changed
            or not doc.object_storage_key
            or doc.downloaded_at is None
        )
        if needs_download:
            _queue_document_download(doc)
    logger.info(
        "process_bill_versions: success bill_id=%s versions=%s", bill_id, len(versions)
    )
    return {"bill_id": bill_id, "versions": len(versions)}


@shared_task
def backfill_process_bill_versions_for_all_bills(session=None):
    """
    Enqueue process_bill_versions for every Bill in the database (optional congress session).

    Use this to download bill text for **all** rows already ingested. Each bill triggers
    Congress API text-version calls and download_document tasks (watch rate limits).
    """
    qs = Bill.objects.all().order_by("id")
    if session is not None:
        qs = qs.filter(session=int(session))
    enqueued = 0
    backfill_requested_at = timezone.now()
    for bid in qs.values_list("id", flat=True):
        bill = Bill.objects.get(pk=bid)
        _queue_bill_stage(
            bill,
            WORK_KIND_BILL_VERSIONS,
            source_updated_at=backfill_requested_at,
        )
        enqueued += 1
    logger.info(
        "backfill_process_bill_versions_for_all_bills: enqueued=%s (session=%s)",
        enqueued,
        session,
    )
    return {"enqueued": enqueued, "session": session}


@shared_task(
    bind=True,
    autoretry_for=(CongressAPIError,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=2,
)
def process_bill_votes(self, bill_id):
    return _process_bill_votes_impl(bill_id)


def _queue_roll_call_vote(*, bill, reference: dict):
    chamber = str(
        reference.get("chamber") or reference.get("chamberCode") or ""
    ).casefold()
    if chamber not in {"house", "senate"}:
        raise CongressAPIError("recorded vote has an unsupported chamber")
    try:
        session_number = int(
            reference.get("sessionNumber") or reference.get("session_number")
        )
        roll_number = int(reference.get("rollNumber") or reference.get("roll_number"))
    except (TypeError, ValueError) as exc:
        raise CongressAPIError(
            "recorded vote is missing session or roll number"
        ) from exc
    source_updated_at = (
        _parse_congress_update_datetime(
            reference.get("updateDate") or reference.get("actionDate")
        )
        or UNKNOWN_SOURCE_UPDATED_AT
    )
    work_item = enqueue_ingestion_work(
        kind=WORK_KIND_ROLL_CALL_VOTE,
        dedupe_key=(f"vote:{bill.session}:{chamber}:{session_number}:{roll_number}"),
        source_updated_at=source_updated_at,
        congress=bill.session,
        payload_json={
            "bill_id": bill.id,
            "congress": bill.session,
            "chamber": chamber,
            "session_number": session_number,
            "roll_number": roll_number,
            "source_url": str(reference.get("url") or "")[:1024],
        },
    )
    requeued = False
    with transaction.atomic():
        work_item = IngestionWorkItem.objects.select_for_update().get(pk=work_item.pk)
        payload = dict(work_item.payload_json)
        existing_bill_id = payload.get("bill_id")
        if existing_bill_id not in (None, bill.id):
            raise CongressAPIError(
                "recorded vote identity is already associated with another bill"
            )
        if existing_bill_id is None:
            payload["bill_id"] = bill.id
            work_item.payload_json = payload
            update_fields = ["payload_json", "updated_at"]
            if work_item.status in (
                IngestionWorkStatus.SUCCEEDED,
                IngestionWorkStatus.DEAD,
            ):
                work_item.status = IngestionWorkStatus.PENDING
                work_item.attempt_count = 0
                work_item.available_at = timezone.now()
                work_item.lease_expires_at = None
                work_item.dispatch_token = ""
                work_item.last_error = ""
                work_item.completed_at = None
                update_fields.extend(
                    [
                        "status",
                        "attempt_count",
                        "available_at",
                        "lease_expires_at",
                        "dispatch_token",
                        "last_error",
                        "completed_at",
                    ]
                )
                requeued = True
            work_item.save(update_fields=update_fields)
    if requeued:
        try:
            dispatch_ingestion_work.delay()
        except Exception:
            logger.exception(
                "_queue_roll_call_vote: could not re-dispatch roll-call work_item=%s",
                work_item.id,
            )
    return work_item


def _normalize_vote_position(value: object) -> str:
    raw = str(value or "").strip().casefold()
    return {
        "aye": "yes",
        "ayes": "yes",
        "yea": "yes",
        "yeas": "yes",
        "yes": "yes",
        "nay": "no",
        "nays": "no",
        "no": "no",
        "present": "present",
        "not voting": "not_voting",
        "not_voting": "not_voting",
    }.get(raw, "other")


def _normalized_vote_members(raw_members, *, chamber: str) -> list[dict]:
    if isinstance(raw_members, dict):
        members = []
        for key, default_position in (
            ("yeas", "yes"),
            ("ayes", "yes"),
            ("nays", "no"),
            ("noes", "no"),
            ("present", "present"),
            ("notVoting", "not_voting"),
        ):
            for member in raw_members.get(key, []):
                if isinstance(member, dict):
                    members.append(
                        {
                            **member,
                            "position": member.get("position") or default_position,
                        }
                    )
    elif isinstance(raw_members, list):
        members = raw_members
    else:
        raise CongressAPIError("roll-call detail has an invalid voter collection")

    normalized = []
    seen = set()
    for member in members:
        if not isinstance(member, dict):
            raise CongressAPIError("roll-call detail contains an invalid voter")
        bioguide_id = str(
            member.get("bioguideId") or member.get("bioguide_id") or ""
        ).strip()
        if not bioguide_id:
            raise CongressAPIError(
                "roll-call detail contains a voter without Bioguide ID"
            )
        if bioguide_id in seen:
            raise CongressAPIError(
                "roll-call detail contains duplicate voter identities"
            )
        seen.add(bioguide_id)
        raw_position = str(member.get("position") or member.get("vote") or "").strip()
        normalized.append(
            {
                "bioguide_id": bioguide_id,
                "position": _normalize_vote_position(raw_position),
                "raw_position": raw_position[:100],
                "chamber": chamber,
            }
        )
    if not normalized:
        raise CongressAPIError("roll-call detail contains no voters")
    return normalized


def _parse_vote_datetime(value):
    if isinstance(value, datetime):
        return _ensure_utc_aware(value)
    if isinstance(value, str):
        try:
            return _ensure_utc_aware(
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            )
        except ValueError:
            pass
    raise CongressAPIError("roll-call detail has no valid vote date")


def _process_roll_call_vote_impl(work_item):
    """Persist a complete official roll call after all exact members are known."""

    payload = work_item.payload_json
    congress = int(payload["congress"])
    chamber = str(payload["chamber"])
    session_number = int(payload["session_number"])
    roll_number = int(payload["roll_number"])
    vote_data = vote_detail(
        congress,
        chamber,
        roll_number,
        session_number=session_number,
        source_url=payload.get("source_url") or None,
    )
    members = _normalized_vote_members(
        vote_data.get("members") or vote_data.get("votes"), chamber=chamber
    )
    known = set(
        Representative.objects.filter(
            bioguide_id__in=[member["bioguide_id"] for member in members]
        ).values_list("bioguide_id", flat=True)
    )
    missing = {member["bioguide_id"] for member in members} - known
    if missing:
        for bioguide_id in missing:
            enqueue_ingestion_work(
                kind=WORK_KIND_REPRESENTATIVE_DETAIL,
                dedupe_key=f"bioguide:{bioguide_id}",
                source_updated_at=work_item.source_updated_at,
                congress=congress,
                payload_json={"bioguide_id": bioguide_id},
            )
        raise BlockedWork([f"bioguide:{bioguide_id}" for bioguide_id in missing])

    vote_date = _parse_vote_datetime(vote_data.get("date") or vote_data.get("voteDate"))
    bill = None
    bill_id = payload.get("bill_id")
    if bill_id is not None:
        bill = Bill.objects.filter(pk=bill_id, session=congress).first()
        if bill is None:
            raise ValueError("roll-call work references a missing bill")
    result = str(vote_data.get("result") or vote_data.get("question") or "unknown")[:50]
    question = str(vote_data.get("question") or "")
    with transaction.atomic():
        vote, created = Vote.objects.select_for_update().get_or_create(
            congress=congress,
            chamber=chamber,
            session_number=session_number,
            roll_number=roll_number,
            defaults={
                "bill": bill,
                "vote_date": vote_date,
                "result": result,
                "question": question,
                "source_url": str(payload.get("source_url") or "")[:1024],
                "source_updated_at": work_item.source_updated_at,
                "yeas": int(vote_data.get("yeas") or 0),
                "nays": int(vote_data.get("nays") or 0),
            },
        )
        if (
            not created
            and vote.source_updated_at is not None
            and work_item.source_updated_at < vote.source_updated_at
        ):
            attached_bill = bill is not None and vote.bill_id is None
            if attached_bill:
                vote.bill = bill
                vote.save(update_fields=["bill"])
                record_bill_change(
                    bill=bill,
                    change_type="vote",
                    new_value={
                        "vote_id": vote.id,
                        "congress": congress,
                        "chamber": chamber,
                        "session_number": session_number,
                        "roll_number": roll_number,
                        "result": vote.result,
                        "yeas": vote.yeas,
                        "nays": vote.nays,
                    },
                    event_key=(
                        f"vote:{congress}:{chamber}:{session_number}:{roll_number}:"
                        f"{work_item.source_updated_at.isoformat()}"
                    ),
                )
            return {
                "vote_id": vote.id,
                "created_or_updated": attached_bill,
                "member_count": 0,
                "stale": True,
            }
        changed = created
        for field, value in {
            "bill": bill or vote.bill,
            "vote_date": vote_date,
            "result": result,
            "question": question,
            "source_url": str(payload.get("source_url") or "")[:1024],
            "source_updated_at": work_item.source_updated_at,
            "yeas": int(vote_data.get("yeas") or 0),
            "nays": int(vote_data.get("nays") or 0),
        }.items():
            if getattr(vote, field) != value:
                setattr(vote, field, value)
                changed = True
        if changed and not created:
            vote.save()
        representative_by_id = {
            representative.bioguide_id: representative
            for representative in Representative.objects.filter(
                bioguide_id__in=[member["bioguide_id"] for member in members]
            )
        }
        member_ids = set()
        for member in members:
            representative = representative_by_id[member["bioguide_id"]]
            member_ids.add(representative.id)
            record, record_created = VoteRecord.objects.get_or_create(
                vote=vote,
                representative=representative,
                defaults={
                    "position": member["position"],
                    "raw_position": member["raw_position"],
                },
            )
            if not record_created and (
                record.position != member["position"]
                or record.raw_position != member["raw_position"]
            ):
                record.position = member["position"]
                record.raw_position = member["raw_position"]
                record.save(update_fields=["position", "raw_position"])
                changed = True
            changed = changed or record_created
        deleted, _ = (
            VoteRecord.objects.filter(vote=vote)
            .exclude(representative_id__in=member_ids)
            .delete()
        )
        changed = changed or bool(deleted)
        if changed and bill is not None:
            record_bill_change(
                bill=bill,
                change_type="vote",
                new_value={
                    "vote_id": vote.id,
                    "congress": congress,
                    "chamber": chamber,
                    "session_number": session_number,
                    "roll_number": roll_number,
                    "result": vote.result,
                    "yeas": vote.yeas,
                    "nays": vote.nays,
                },
                event_key=(
                    f"vote:{congress}:{chamber}:{session_number}:{roll_number}:"
                    f"{work_item.source_updated_at.isoformat()}"
                ),
            )
    return {
        "vote_id": vote.id,
        "created_or_updated": changed,
        "member_count": len(members),
    }


def _process_bill_votes_impl(bill_id):
    """Discover bill action references and queue canonical roll-call work only."""
    logger.info("process_bill_votes: starting bill_id=%s", bill_id)
    bill = Bill.objects.filter(pk=bill_id).first()
    if not bill:
        logger.warning("process_bill_votes: bill_id=%s not found", bill_id)
        return
    parts = bill.bill_number.strip().split()
    bill_type = (
        (parts[0].lower() if parts else "hr").replace("hr", "hr").replace("s", "s")
    )
    num = parts[1] if len(parts) >= 2 else bill.bill_number.replace(" ", "")
    congress = bill.session
    actions = bill_actions(congress, bill_type, num)
    votes_refs = []
    for action in actions:
        recorded_votes = action.get("recordedVotes") or []
        if isinstance(recorded_votes, list):
            votes_refs.extend(
                recorded_vote
                for recorded_vote in recorded_votes
                if isinstance(recorded_vote, dict)
            )
    queued = 0
    for reference in votes_refs:
        _queue_roll_call_vote(bill=bill, reference=reference)
        queued += 1
    logger.info(
        "process_bill_votes: queued canonical roll calls bill_id=%s count=%s",
        bill_id,
        queued,
    )
    return {"bill_id": bill_id, "queued": queued}


@shared_task(
    bind=True,
    autoretry_for=(
        requests.RequestException,
        OSError,
        RetryableDocumentStorageError,
    ),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
)
def download_document(self, document_id):
    return _download_document_impl(document_id)


def _download_document_impl(document_id):
    """
    Download file from BillDocument.source_url, upload to storage (MinIO/S3 or local_media),
    set content_hash, extracted_text when PDF/XML/HTML, enqueue generate_contract.
    """
    logger.info("download_document: starting document_id=%s", document_id)
    doc = BillDocument.objects.select_related("bill").filter(pk=document_id).first()
    if not doc:
        logger.warning("download_document: document_id=%s not found", document_id)
        return {"document_id": document_id, "skipped": True, "reason": "not_found"}

    if not doc.source_url:
        logger.warning(
            "download_document: no source_url for document_id=%s", document_id
        )
        return {"document_id": document_id, "skipped": True, "reason": "no_source_url"}

    bill = doc.bill
    try:
        downloaded = download_url(doc.source_url)
    except requests.RequestException as exc:
        logger.warning(
            "download_document: HTTP error document_id=%s: %s",
            document_id,
            exc,
        )
        raise

    with downloaded:
        content_type = downloaded.content_type
        new_hash = downloaded.checksum
        unchanged = doc.content_hash == new_hash and bool(doc.object_storage_key)
        extracted = None
        if unchanged:
            saved_key = doc.object_storage_key
            size = doc.file_size_bytes
            logger.info(
                "download_document: unchanged hash, reconciling event document_id=%s",
                document_id,
            )
        else:
            ext = ""
            if content_type and "pdf" in content_type.lower():
                ext = ".pdf"
            elif content_type and "xml" in content_type.lower():
                ext = ".xml"
            elif content_type and "html" in content_type.lower():
                ext = ".html"
            else:
                ext = guess_extension(doc.source_url, content_type)

            object_key = build_object_key(
                bill.session,
                bill.bill_number,
                doc.version_label,
                ext,
            )
            extracted = extract_document_text(
                downloaded.file,
                content_type,
                doc.source_url,
            )
            try:
                saved_key, size = upload_and_metadata(
                    object_key,
                    downloaded.file,
                    content_type,
                    size=downloaded.size,
                )
            except Exception as exc:
                retryable_error = retryable_storage_error(exc)
                if retryable_error:
                    raise retryable_error from exc
                raise

    now = timezone.now()
    with transaction.atomic():
        locked_bill, _clock = lock_bill_activity(bill_id=bill.pk)
        locked_doc = BillDocument.objects.select_for_update().get(pk=doc.pk)

        update_fields = ["downloaded_at"]
        locked_doc.downloaded_at = now
        if not unchanged:
            locked_doc.object_storage_key = saved_key
            locked_doc.file_size_bytes = size
            locked_doc.content_hash = new_hash
            locked_doc.content_type = content_type[:128] if content_type else None
            locked_doc.extracted_text = extracted or None
            locked_doc.parsed_at = now if extracted else None
            update_fields.extend(
                [
                    "object_storage_key",
                    "file_size_bytes",
                    "content_hash",
                    "content_type",
                    "extracted_text",
                    "parsed_at",
                ]
            )
        locked_doc.save(update_fields=update_fields)
        record_bill_change(
            bill=locked_bill,
            document=locked_doc,
            change_type="new_version",
            new_value={
                "document_id": locked_doc.id,
                "version_label": locked_doc.version_label,
                "content_hash": new_hash,
                "is_active_version": locked_doc.is_active_version,
            },
            event_key=f"document:{locked_doc.id}:{new_hash}",
        )

    logger.info(
        "download_document: success document_id=%s key=%s bytes=%s",
        document_id,
        saved_key,
        size,
    )
    from apps.legislation.tasks import enqueue_document_contract

    enqueue_document_contract(locked_doc)
    from apps.legislation.tasks import enqueue_search_index

    enqueue_search_index(locked_bill)
    return {
        "document_id": document_id,
        "object_storage_key": saved_key,
        "size": size,
        "unchanged": unchanged,
    }
