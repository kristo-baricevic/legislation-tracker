"""
Celery tasks for Congress.gov ingestion: poll, process_bill, versions, votes.
"""
import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone

import requests
from django.utils import timezone

from celery import shared_task
from django.db import transaction
from django.db.models import Q

from apps.accounts.models import TrackedBill, TrackedLegislator, TrackedTopic
from apps.changelog.models import ChangeLog
from apps.congress.models import Representative, Vote, VoteRecord
from apps.ingestion.congress_client import (
    CongressAPIError,
    bill_actions,
    bill_detail,
    bill_list,
    bill_text_list,
    member_detail,
    member_list,
    vote_detail,
)
from apps.ingestion.document_download import (
    build_object_key,
    download_url,
    extract_text_from_pdf,
    extract_text_from_xml_or_html,
    guess_extension,
    sha256_hex,
    upload_and_metadata,
)
from apps.ingestion.models import (
    IngestionState,
    IngestionTaskFailure,
    IngestionWorkItem,
    IngestionWorkStatus,
)
from apps.legislation.models import Bill, BillDocument, ProcessingStatus
from apps.legislation.tasks import generate_contract, generate_contract_for_bill

logger = logging.getLogger(__name__)

CURSOR_OVERLAP = timedelta(minutes=5)
TRACKED_REFRESH_INTERVAL = timedelta(minutes=5)
WORK_LEASE_DURATION = timedelta(minutes=10)
MAX_INGESTION_WORK_ATTEMPTS = 5
UNKNOWN_SOURCE_UPDATED_AT = datetime(1970, 1, 1, tzinfo=dt_timezone.utc)
CURRENT_CONGRESS = 119

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
        return timezone.make_aware(dt, dt_timezone.utc)
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
):
    raw = "|".join([
        (status or "").strip(),
        (title or "").strip(),
        (summary or "").strip(),
        str(last_action_at or ""),
        str(introduced_at or ""),
        str(sponsor_id or ""),
        (source_api_id or "").strip(),
    ])
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


def _member_chamber(member):
    terms = member.get("terms") or []
    if isinstance(terms, dict):
        terms = terms.get("item") or terms.get("terms") or []
    if isinstance(terms, list):
        for term in reversed(terms):
            if isinstance(term, dict) and term.get("chamber"):
                return str(term["chamber"]).lower()
    chamber = member.get("chamber") or ""
    return str(chamber).lower() if chamber else "house"


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


def _member_profile(summary, detail):
    member = dict(summary)
    member.update(detail or {})
    bioguide_id = member.get("bioguideId") or member.get("bioguide_id")
    if not bioguide_id:
        raise CongressAPIError("Congress member payload is missing bioguideId")
    first_name = str(member.get("firstName") or "")[:255]
    last_name = str(member.get("lastName") or "")[:255]
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
        "state": str(member.get("state") or "")[:2],
        "district": str(district)[:10] if district not in (None, "") else None,
        "official_website_url": member.get("officialWebsiteUrl") or None,
        "image_url": image_url or None,
        "source_api_url": member.get("url") or None,
        "is_current": bool(member.get("currentMember", True)),
    }


@shared_task
def sync_representatives(congress=119):
    """Synchronize the full current member roster without retiring on partial pulls."""
    if congress != CURRENT_CONGRESS:
        raise ValueError(
            f"Representative roster sync only supports the current Congress ({CURRENT_CONGRESS})"
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
        raise CongressAPIError("Congress member roster was empty; refusing to retire members")

    profiles = []
    for summary in summaries:
        if not isinstance(summary, dict):
            raise CongressAPIError("Congress member list contained an invalid member payload")
        bioguide_id = summary.get("bioguideId") or summary.get("bioguide_id")
        if not bioguide_id:
            raise CongressAPIError("Congress member list entry is missing bioguideId")
        profiles.append(_member_profile(summary, member_detail(bioguide_id)))

    now = timezone.now()
    created_count = 0
    updated_count = 0
    seen_ids = {profile["bioguide_id"] for profile in profiles}
    with transaction.atomic():
        for profile in profiles:
            bioguide_id = profile.pop("bioguide_id")
            profile["last_seen_at"] = now
            _, created = Representative.objects.update_or_create(
                bioguide_id=bioguide_id,
                defaults=profile,
            )
            created_count += int(created)
            updated_count += int(not created)
        Representative.objects.filter(is_current=True).exclude(
            bioguide_id__in=seen_ids
        ).update(is_current=False)

    return {
        "congress": congress,
        "members": len(profiles),
        "created": created_count,
        "updated": updated_count,
    }


@shared_task
def poll_congress(jurisdiction="federal", congress=119):
    """
    Discover updated Congress bills and persist them before advancing the cursor.

    The worker dispatcher is intentionally separate: a temporary broker outage
    cannot lose a discovered bill or force the cursor to stay behind forever.
    """
    logger.info("poll_congress: starting jurisdiction=%s congress=%s", jurisdiction, congress)
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
                sorted(
                    bill_key(b["congress"], b["type"], b["number"]) for b in items
                )
            )
            if offset > 0 and previous_page_keys == page_keys:
                logger.warning(
                    "poll_congress: bill_type=%s offset=%s repeated same page (API may not support offset); stopping pagination",
                    bt,
                    offset,
                )
                break
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
    return {"discovered": len(discovered_bills), "created": created_count}


def _retry_delay(attempt_count):
    """Bound exponential delay for persistent ingestion retries."""
    return timedelta(seconds=min(60 * (2 ** max(attempt_count - 1, 0)), 3600))


def _tracked_refresh_bucket(now):
    interval_seconds = int(TRACKED_REFRESH_INTERVAL.total_seconds())
    timestamp = int(_ensure_utc_aware(now).timestamp())
    return datetime.fromtimestamp(
        timestamp - (timestamp % interval_seconds),
        tz=dt_timezone.utc,
    )


@shared_task
def dispatch_ingestion_work(batch_size=100):
    """Lease pending durable work and submit it to Celery without losing rows."""
    now = timezone.now()
    leased_items = []
    with transaction.atomic():
        candidates = list(
            IngestionWorkItem.objects.select_for_update(skip_locked=True)
            .filter(
                status=IngestionWorkStatus.PENDING,
                available_at__lte=now,
            )
            .order_by("available_at", "id")[:batch_size]
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

        IngestionWorkItem.objects.filter(
            pk=work_item_id,
            status=IngestionWorkStatus.DISPATCHED,
        ).update(celery_task_id=getattr(result, "id", "") or "")
        dispatched += 1

    return {"dispatched": dispatched}


@shared_task(bind=True)
def process_ingestion_work_item(self, work_item_id, dispatch_token=None):
    """Execute one durable work item and persist its terminal or retry state."""
    now = timezone.now()
    with transaction.atomic():
        work_item = IngestionWorkItem.objects.select_for_update().filter(pk=work_item_id).first()
        if work_item is None:
            return {"work_item_id": work_item_id, "status": "missing"}
        if work_item.status in (IngestionWorkStatus.SUCCEEDED, IngestionWorkStatus.DEAD):
            return {"work_item_id": work_item.id, "status": work_item.status}
        if dispatch_token and work_item.dispatch_token != dispatch_token:
            return {"work_item_id": work_item.id, "status": "superseded"}
        if work_item.status == IngestionWorkStatus.PROCESSING:
            return {"work_item_id": work_item.id, "status": "processing"}
        if work_item.status == IngestionWorkStatus.PENDING and work_item.available_at > now:
            return {"work_item_id": work_item.id, "status": "not_ready"}

        work_item.status = IngestionWorkStatus.PROCESSING
        work_item.attempt_count += 1
        work_item.lease_expires_at = now + WORK_LEASE_DURATION
        work_item.celery_task_id = self.request.id or work_item.celery_task_id
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
        if work_item.kind != "bill":
            raise ValueError(f"Unsupported ingestion work kind: {work_item.kind}")
        bill_key_str = work_item.payload_json.get("bill_key")
        if not bill_key_str:
            raise ValueError("Bill ingestion work is missing payload_json.bill_key")
        _process_bill_impl(bill_key_str)
    except Exception as exc:
        error_message = str(exc)[:10000]
        with transaction.atomic():
            work_item = IngestionWorkItem.objects.select_for_update().get(pk=work_item_id)
            if work_item.attempt_count >= MAX_INGESTION_WORK_ATTEMPTS:
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

            work_item.status = IngestionWorkStatus.PENDING
            work_item.available_at = timezone.now() + _retry_delay(work_item.attempt_count)
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
        logger.warning(
            "process_ingestion_work_item: retrying work_item=%s attempt=%s: %s",
            work_item_id,
            work_item.attempt_count,
            exc,
        )
        return {"work_item_id": work_item_id, "status": "retrying"}

    with transaction.atomic():
        work_item = IngestionWorkItem.objects.select_for_update().get(pk=work_item_id)
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
    return {"work_item_id": work_item_id, "status": "succeeded"}


@shared_task
def recover_stale_ingestion_work():
    """Release worker leases left behind by a crash or a broker delivery loss."""
    now = timezone.now()
    recovered = IngestionWorkItem.objects.filter(
        status__in=[IngestionWorkStatus.DISPATCHED, IngestionWorkStatus.PROCESSING],
        lease_expires_at__lt=now,
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


def _record_task_failure(task_id, task_name, args, kwargs, bill_id, exc, work_item=None):
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
        logger.exception("process_bill failed: bill_key=%s retries=%s: %s", bill_key_str, self.request.retries, exc)
        if not isinstance(exc, CongressAPIError) or self.request.retries >= self.max_retries:
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
    summary = (detail.get("summary") or "")[:10000] or None
    introduced_at = None
    if detail.get("introducedDate"):
        try:
            introduced_at = datetime.strptime(detail["introducedDate"][:10], "%Y-%m-%d").date()
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
    )
    with transaction.atomic():
        bill, created = Bill.objects.get_or_create(
            session=congress,
            bill_number=bill_number_display,
            defaults={
                "jurisdiction": "federal",
                "title": title or bill_number_display,
                "summary": summary,
                "status": status or "Unknown",
                "processing_status": ProcessingStatus.PROCESSING,
                "introduced_at": introduced_at,
                "last_action_at": last_action_at,
                "sponsor": sponsor,
                "source_api_id": source_api_id,
                "metadata_hash": metadata_hash,
            },
        )
        bill_id = bill.id
        if not created:
            if bill.metadata_hash == metadata_hash:
                logger.info("process_bill: unchanged (hash match) bill_id=%s bill_key=%s", bill.id, bill_key_str)
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
                        process_bill_versions.apply_async(args=[bill.id])
                        logger.info(
                            "process_bill: enqueued versions (documents missing or not downloaded) bill_id=%s",
                            bill.id,
                        )
                    process_bill_votes.apply_async(args=[bill.id])
                except Exception:
                    logger.exception(
                        "process_bill: failed to enqueue versions/votes bill_id=%s",
                        bill.id,
                    )
                    raise
                return {"bill_id": bill.id, "unchanged": True}
            old_status = bill.status
            old_title = bill.title
            bill.processing_status = ProcessingStatus.PROCESSING
            bill.title = title or bill.title
            bill.summary = summary if summary is not None else bill.summary
            bill.status = status or bill.status
            bill.introduced_at = introduced_at if introduced_at is not None else bill.introduced_at
            bill.last_action_at = last_action_at if last_action_at is not None else bill.last_action_at
            bill.sponsor = sponsor if sponsor is not None else bill.sponsor
            bill.source_api_id = source_api_id
            bill.metadata_hash = metadata_hash
            bill.save()
            ChangeLog.objects.create(
                bill=bill,
                change_type="status_update",
                old_value={"status": old_status, "title": old_title},
                new_value={"status": bill.status, "title": bill.title},
            )
        else:
            ChangeLog.objects.create(
                bill=bill,
                change_type="status_update",
                old_value=None,
                new_value={"status": status, "title": title},
            )
    try:
        process_bill_versions.apply_async(args=[bill.id])
        process_bill_votes.apply_async(args=[bill.id])
    except Exception:
        bill.processing_status = ProcessingStatus.FAILED
        bill.save(update_fields=["processing_status"])
        raise
    logger.info("process_bill: success bill_id=%s bill_key=%s (updated, enqueued versions+votes)", bill.id, bill_key_str)
    return {"bill_id": bill.id, "unchanged": False}


@shared_task(
    bind=True,
    autoretry_for=(CongressAPIError,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=2,
)
def process_bill_versions(self, bill_id):
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
        logger.warning("process_bill_versions: bill_id=%s bill_text_list failed: %s", bill_id, e)
        raise
    if not versions:
        logger.info("process_bill_versions: bill_id=%s no versions returned", bill_id)
        generate_contract_for_bill.apply_async(args=[bill.id])
        return {"bill_id": bill_id, "versions": 0, "fallback_enqueued": True}
    # Mark one as active (e.g. last)
    for i, v in enumerate(versions):
        label = v.get("version_label") or v.get("url") or f"v{i}"
        url = v.get("url") or ""
        doc, created = BillDocument.objects.get_or_create(
            bill=bill,
            version_label=label[:50],
            defaults={"source_url": url or None, "is_active_version": False},
        )
        source_url_changed = not created and (doc.source_url or "") != url
        if source_url_changed:
            doc.source_url = url or None
            doc.save(update_fields=["source_url"])
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
            download_document.apply_async(args=[doc.id])
    logger.info("process_bill_versions: success bill_id=%s versions=%s", bill_id, len(versions))
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
    for bid in qs.values_list("id", flat=True):
        process_bill_versions.apply_async(args=[bid])
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
    """Fetch vote refs from bill detail, create Vote/VoteRecord/Representative, insert ChangeLog(vote)."""
    logger.info("process_bill_votes: starting bill_id=%s", bill_id)
    bill = Bill.objects.filter(pk=bill_id).first()
    if not bill:
        logger.warning("process_bill_votes: bill_id=%s not found", bill_id)
        return
    parts = bill.bill_number.strip().split()
    bill_type = (parts[0].lower() if parts else "hr").replace("hr", "hr").replace("s", "s")
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
    votes_created = 0
    for ref in votes_refs:
        if not isinstance(ref, dict):
            continue
        chamber = (ref.get("chamber") or ref.get("chamberCode") or "house").lower()
        roll = ref.get("rollNumber") or ref.get("roll_number")
        if roll is None:
            continue
        vote_data = vote_detail(
            congress,
            chamber,
            roll,
            session_number=ref.get("sessionNumber") or ref.get("session_number"),
            source_url=ref.get("url"),
        )
        vote_date = vote_data.get("date") or vote_data.get("voteDate")
        if isinstance(vote_date, str):
            try:
                vote_date = datetime.fromisoformat(vote_date.replace("Z", "+00:00"))
            except Exception:
                vote_date = timezone.now()
        if vote_date and timezone.is_naive(vote_date):
            vote_date = timezone.make_aware(vote_date)
        result = (vote_data.get("result") or vote_data.get("question") or "unknown")[:50]
        yeas = int(vote_data.get("yeas") or vote_data.get("total", {}).get("yeas") or 0)
        nays = int(vote_data.get("nays") or vote_data.get("total", {}).get("nays") or 0)
        with transaction.atomic():
            vote, vote_created = Vote.objects.get_or_create(
                bill=bill,
                chamber=chamber,
                roll_number=int(roll),
                defaults={
                    "vote_date": vote_date or timezone.now(),
                    "result": result,
                    "yeas": yeas,
                    "nays": nays,
                },
            )
            vote_updated = False
            for field, value in {
                "vote_date": vote_date or timezone.now(),
                "result": result,
                "yeas": yeas,
                "nays": nays,
            }.items():
                if getattr(vote, field) != value:
                    setattr(vote, field, value)
                    vote_updated = True
            if vote_updated:
                vote.save(update_fields=["vote_date", "result", "yeas", "nays"])
            members = vote_data.get("members") or vote_data.get("votes") or {}
            if isinstance(members, dict):
                grouped_members = []
                for group_name, position in (
                    ("yeas", "yes"),
                    ("ayes", "yes"),
                    ("nays", "no"),
                    ("noes", "no"),
                    ("present", "present"),
                    ("abstain", "abstain"),
                    ("notVoting", "not_voting"),
                ):
                    for member in members.get(group_name, []):
                        if isinstance(member, dict):
                            grouped_members.append(
                                {**member, "position": member.get("position") or member.get("vote") or position}
                            )
                members = grouped_members
            records_updated = False
            for m in members if isinstance(members, list) else []:
                if not isinstance(m, dict):
                    continue
                bio = m.get("bioguideId") or m.get("bioguide_id")
                if not bio:
                    continue
                name = m.get("name") or m.get("fullName") or bio
                state = (m.get("state") or "")[:2]
                party = (m.get("party") or "")[:50]
                chamber_m = (m.get("chamber") or chamber).lower()
                rep = get_or_create_representative_from_sponsor(
                    {
                        "bioguideId": bio,
                        "fullName": name,
                        "chamber": chamber_m,
                        "party": party,
                        "state": state,
                    }
                )
                pos = (m.get("position") or m.get("vote") or "yes").lower()[:20]
                record, record_created = VoteRecord.objects.get_or_create(
                    vote=vote,
                    representative=rep,
                    defaults={"position": pos or "yes"},
                )
                if not record_created and record.position != pos:
                    record.position = pos
                    record.save(update_fields=["position"])
                    records_updated = True
                records_updated = records_updated or record_created
            if vote_created or vote_updated or records_updated:
                ChangeLog.objects.create(
                    bill=bill,
                    change_type="vote",
                    new_value={
                        "vote_id": vote.id,
                        "roll_number": vote.roll_number,
                        "result": vote.result,
                        "chamber": vote.chamber,
                    },
                )
                votes_created += 1
    logger.info("process_bill_votes: done bill_id=%s votes_created=%s", bill_id, votes_created)
    return {"bill_id": bill_id, "votes_created": votes_created}


@shared_task(
    bind=True,
    autoretry_for=(requests.RequestException, OSError),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
)
def download_document(self, document_id):
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
        logger.warning("download_document: no source_url for document_id=%s", document_id)
        return {"document_id": document_id, "skipped": True, "reason": "no_source_url"}

    bill = doc.bill
    try:
        data, content_type = download_url(doc.source_url)
    except requests.RequestException as e:
        logger.warning("download_document: HTTP error document_id=%s: %s", document_id, e)
        raise

    new_hash = sha256_hex(data)
    if doc.content_hash == new_hash and doc.object_storage_key:
        logger.info(
            "download_document: unchanged hash, skipping upload document_id=%s", document_id
        )
        doc.downloaded_at = timezone.now()
        doc.save(update_fields=["downloaded_at"])
        generate_contract.apply_async(args=[document_id])
        return {"document_id": document_id, "unchanged": True}

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

    saved_key, size = upload_and_metadata(object_key, data, content_type)

    extracted = ""
    if content_type and "pdf" in content_type.lower():
        extracted = extract_text_from_pdf(data)
    elif content_type and ("xml" in content_type.lower() or "html" in content_type.lower()):
        extracted = extract_text_from_xml_or_html(data, content_type)

    now = timezone.now()
    doc.object_storage_key = saved_key
    doc.file_size_bytes = size
    doc.content_hash = new_hash
    doc.content_type = (content_type[:128] if content_type else None)
    doc.extracted_text = extracted or None
    doc.downloaded_at = now
    doc.parsed_at = now if extracted else None
    doc.save(
        update_fields=[
            "object_storage_key",
            "file_size_bytes",
            "content_hash",
            "content_type",
            "extracted_text",
            "downloaded_at",
            "parsed_at",
        ]
    )
    logger.info(
        "download_document: success document_id=%s key=%s bytes=%s",
        document_id,
        saved_key,
        size,
    )
    generate_contract.apply_async(args=[document_id])
    return {"document_id": document_id, "object_storage_key": saved_key, "size": size}
