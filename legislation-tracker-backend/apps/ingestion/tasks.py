"""
Celery tasks for Congress.gov ingestion: poll, process_bill, versions, votes.
"""
import hashlib
import logging
from datetime import datetime
from django.utils import timezone

from celery import shared_task
from django.db import transaction

from apps.changelog.models import ChangeLog
from apps.congress.models import Representative, Vote, VoteRecord
from apps.ingestion.congress_client import (
    CongressAPIError,
    bill_detail,
    bill_list,
    bill_text_list,
    vote_detail,
)
from apps.ingestion.models import IngestionState, IngestionTaskFailure
from apps.legislation.models import Bill, BillDocument, ProcessingStatus

logger = logging.getLogger(__name__)

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


def format_bill_number(bill_type, bill_number):
    """Store as e.g. HR 1234 for display/API consistency."""
    t = (bill_type or "hr").upper()
    if t == "HR":
        t = "HR"
    elif t == "S":
        t = "S"
    return f"{t} {bill_number}"


def compute_metadata_hash(status, title, summary, last_action_at):
    raw = "|".join([
        (status or "").strip(),
        (title or "").strip(),
        (summary or "").strip()[:2000],
        str(last_action_at or ""),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_or_create_representative_from_sponsor(sponsor_blob):
    """Get or create Representative from Congress API sponsor object."""
    if not sponsor_blob:
        return None
    bioguide_id = sponsor_blob.get("bioguideId") or sponsor_blob.get("bioguide_id")
    if not bioguide_id:
        return None
    name = sponsor_blob.get("fullName") or sponsor_blob.get("name") or ""
    state = (sponsor_blob.get("state") or "")[:2]
    party = (sponsor_blob.get("party") or "")[:50]
    chamber = (sponsor_blob.get("chamber") or "house").lower()
    district = str(sponsor_blob.get("district") or "")[:10] or None
    rep, _ = Representative.objects.get_or_create(
        bioguide_id=bioguide_id,
        defaults={
            "name": name or bioguide_id,
            "chamber": chamber or "house",
            "party": party or "",
            "state": state or "",
            "district": district,
        },
    )
    return rep


@shared_task
def poll_congress(jurisdiction="federal", congress=119):
    """
    Fetch bill list from Congress API, update IngestionState, enqueue process_bill per bill.
    """
    state, _ = IngestionState.objects.get_or_create(
        jurisdiction=jurisdiction,
        congress=congress,
        defaults={},
    )
    from_date_time = None
    if state.last_bill_update_seen_at:
        from_date_time = state.last_bill_update_seen_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    bill_types = ["hr", "s"]
    all_bill_keys = set()
    latest_update = state.last_bill_update_seen_at
    for bt in bill_types:
        try:
            items = bill_list(congress, bt, from_date_time=from_date_time, limit=250)
        except CongressAPIError as e:
            logger.warning("poll_congress bill_list %s %s: %s", congress, bt, e)
            continue
        for b in items:
            key = bill_key(b["congress"], b["type"], b["number"])
            all_bill_keys.add(key)
            ud = b.get("updateDate")
            if ud:
                if isinstance(ud, str):
                    try:
                        ud = datetime.fromisoformat(ud.replace("Z", "+00:00"))
                    except Exception:
                        ud = None
                if ud and (latest_update is None or ud > latest_update):
                    latest_update = ud
    now = timezone.now()
    state.last_polled_at = now
    if latest_update:
        state.last_bill_update_seen_at = latest_update
    state.save(update_fields=["last_polled_at", "last_bill_update_seen_at"])
    for key in all_bill_keys:
        process_bill.apply_async(args=[key])
    return {"enqueued": len(all_bill_keys)}


def _record_task_failure(task_id, task_name, args, kwargs, bill_id, exc):
    try:
        IngestionTaskFailure.objects.create(
            task_id=task_id or "",
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
        if self.request.retries >= self.max_retries:
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
    metadata_hash = compute_metadata_hash(status, title, summary, last_action_at)
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
                "source_api_id": str(detail.get("url") or bill_key_str),
                "metadata_hash": metadata_hash,
            },
        )
        bill_id = bill.id
        if not created:
            if bill.metadata_hash == metadata_hash:
                bill.processing_status = ProcessingStatus.COMPLETE
                bill.save(update_fields=["processing_status"])
                return {"bill_id": bill.id, "unchanged": True}
            old_status = bill.status
            bill.processing_status = ProcessingStatus.PROCESSING
            bill.title = title or bill.title
            bill.summary = summary if summary is not None else bill.summary
            bill.status = status or bill.status
            bill.introduced_at = introduced_at if introduced_at is not None else bill.introduced_at
            bill.last_action_at = last_action_at if last_action_at is not None else bill.last_action_at
            bill.sponsor = sponsor if sponsor is not None else bill.sponsor
            bill.metadata_hash = metadata_hash
            bill.save()
            ChangeLog.objects.create(
                bill=bill,
                change_type="status_update",
                old_value={"status": old_status, "title": bill.title},
                new_value={"status": status, "title": title},
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
    bill.processing_status = ProcessingStatus.COMPLETE
    bill.save(update_fields=["processing_status"])
    return {"bill_id": bill.id, "unchanged": False}


@shared_task(
    bind=True,
    autoretry_for=(CongressAPIError,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=2,
)
def process_bill_versions(self, bill_id):
    """Fetch bill text versions, create/update BillDocument, enqueue download_document (stub)."""
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
    except CongressAPIError:
        raise
    if not versions:
        return
    # Mark one as active (e.g. last)
    for i, v in enumerate(versions):
        label = v.get("version_label") or v.get("url") or f"v{i}"
        url = v.get("url") or ""
        doc, created = BillDocument.objects.get_or_create(
            bill=bill,
            version_label=label[:50],
            defaults={"source_url": url or None, "is_active_version": False},
        )
        if not created and (doc.source_url or "") != url:
            doc.source_url = url or None
            doc.save(update_fields=["source_url"])
        if i == len(versions) - 1:
            BillDocument.objects.filter(bill=bill).update(is_active_version=False)
            doc.is_active_version = True
            doc.save(update_fields=["is_active_version"])
        download_document.apply_async(args=[doc.id])
    return {"bill_id": bill_id, "versions": len(versions)}


@shared_task(
    bind=True,
    autoretry_for=(CongressAPIError,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=2,
)
def process_bill_votes(self, bill_id):
    """Fetch vote refs from bill detail, create Vote/VoteRecord/Representative, insert ChangeLog(vote)."""
    bill = Bill.objects.filter(pk=bill_id).first()
    if not bill:
        logger.warning("process_bill_votes: bill_id=%s not found", bill_id)
        return
    parts = bill.bill_number.strip().split()
    bill_type = (parts[0].lower() if parts else "hr").replace("hr", "hr").replace("s", "s")
    num = parts[1] if len(parts) >= 2 else bill.bill_number.replace(" ", "")
    congress = bill.session
    detail = bill_detail(congress, bill_type, num)
    votes_refs = detail.get("votes") or []
    if isinstance(votes_refs, dict):
        votes_refs = votes_refs.get("rollCalls") or votes_refs.get("votes") or []
    for ref in votes_refs:
        if not isinstance(ref, dict):
            continue
        chamber = (ref.get("chamber") or ref.get("chamberCode") or "house").lower()
        roll = ref.get("rollNumber") or ref.get("roll_number")
        if roll is None:
            continue
        if Vote.objects.filter(bill=bill, chamber=chamber, roll_number=int(roll)).exists():
            continue
        try:
            vote_data = vote_detail(congress, chamber, roll)
        except CongressAPIError:
            continue
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
            vote, _ = Vote.objects.get_or_create(
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
            members = vote_data.get("members") or vote_data.get("votes") or {}
            if isinstance(members, dict):
                members = members.get("yeas", []) + members.get("nays", []) + members.get("present", [])
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
                rep, _ = Representative.objects.get_or_create(
                    bioguide_id=bio,
                    defaults={"name": name, "chamber": chamber_m, "party": party, "state": state},
                )
                pos = (m.get("position") or m.get("vote") or "yes").lower()[:20]
                VoteRecord.objects.get_or_create(
                    vote=vote,
                    representative=rep,
                    defaults={"position": pos or "yes"},
                )
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
    return {"bill_id": bill_id}


@shared_task
def download_document(document_id):
    """
    Phase 3 stub: no-op. Phase 4 will download from GovInfo/S3 and set downloaded_at.
    """
    doc = BillDocument.objects.filter(pk=document_id).first()
    if doc:
        from django.utils import timezone
        doc.downloaded_at = timezone.now()
        doc.save(update_fields=["downloaded_at"])
    return {"document_id": document_id, "stub": True}
