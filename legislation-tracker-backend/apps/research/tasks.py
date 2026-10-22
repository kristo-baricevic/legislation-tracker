"""One bounded stage per durable ingestion delivery; source I/O precedes locks."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from apps.congress.models import Representative
from apps.ingestion.models import IngestionWorkItem
from .models import ResearchRun, RepresentativeBiography, ResearchSourcePolicy
from .biographies import save_official_biography, save_excerpt, save_official_excerpt
from .portraits import save_portrait, prepare_portrait
from .sources import fetch_official_biography, SourceUnavailable


def fenced_work(work):
    current = IngestionWorkItem.objects.select_for_update().get(pk=work.pk)
    valid = (current.status == "processing" and current.dispatch_token == work.dispatch_token
             and current.lease_expires_at and current.lease_expires_at > timezone.now())
    return current if valid else None


def continue_work(current, stage):
    current.payload_json = {**current.payload_json, "stage": stage, "step": current.payload_json.get("step", 0) + 1}
    current.save(update_fields=["payload_json"])


def is_latest_run(run):
    # Caller holds the representative lock, also used when requesting a run.
    return not ResearchRun.objects.filter(representative_id=run.representative_id,
        period=run.period, created_at__gt=run.created_at).exists()


def unchanged_policy(policy):
    if policy is None:
        return None
    current = ResearchSourcePolicy.objects.select_for_update().filter(pk=policy.pk).first()
    fields = ("representative_id", "kind", "url", "approved", "attribution", "license", "element_id", "identity_text")
    if current and current.approved and all(getattr(current, field) == getattr(policy, field) for field in fields):
        return current
    return None


def process_research(work):
    if work.payload_json.get("stage") == "finance":
        from apps.campaign_finance.research import process_finance
        return process_finance(work)
    run = ResearchRun.objects.select_related("representative").get(pk=work.payload_json["run_id"])
    rep = run.representative
    depiction = {"imageUrl": rep.image_url}
    excerpt = None
    source_error = ""
    official_text, prepared = None, None
    bio_policy = ResearchSourcePolicy.objects.filter(representative=rep, kind="biography", approved=True).order_by("-id").first()
    if bio_policy:
        try:
            official_text = fetch_official_biography(bio_policy)
        except (SourceUnavailable, ValueError, ValidationError):
            source_error = "biography_source_unavailable"
    if settings.CONGRESS_API_KEY:
        from apps.ingestion.congress_client import member_detail, CongressAPIError
        try:
            detail = member_detail(rep.bioguide_id)
            if detail.get("bioguideId") == rep.bioguide_id:
                depiction = detail.get("depiction") or depiction
            else:
                source_error = "identity_mismatch"
        except CongressAPIError:
            source_error = "member_source_unavailable"
    if not official_text and getattr(settings, "LEGISLATOR_WIKIPEDIA_ENABLED", False):
        from apps.congress.biography import _snapshot, BiographyUnavailable
        try:
            excerpt = _snapshot(rep.bioguide_id)
        except BiographyUnavailable:
            source_error = source_error or "biography_source_unavailable"
    photo_policy = ResearchSourcePolicy.objects.filter(representative=rep, kind="portrait", approved=True, url=depiction.get("imageUrl", "")).first()
    photo_error = ""
    if photo_policy:
        try:
            prepared = prepare_portrait(photo_policy)
        except (SourceUnavailable, ValueError, ValidationError):
            photo_error = "portrait_source_unavailable"
    with transaction.atomic():
        current = fenced_work(work)
        if current is None:
            return {"status": "superseded"}
        rep = Representative.objects.select_for_update().get(pk=rep.pk)
        if not is_latest_run(run):
            return {"status": "superseded"}
        # Recheck source approval under lock before publishing fetched content.
        bio_policy = unchanged_policy(bio_policy)
        photo_policy = unchanged_policy(photo_policy)
        bio = save_official_excerpt(rep, official_text, bio_policy) if official_text and bio_policy else None
        bio = bio or (save_excerpt(rep, excerpt) if excerpt else None)
        if not bio:
            previous = RepresentativeBiography.objects.filter(representative=rep).order_by("-id").first()
            bio = previous if previous and previous.evidence.get("kind") != "official_service_facts" else save_official_biography(rep)
        portrait = save_portrait(rep, depiction, prepared=prepared, policy=photo_policy) if source_error != "identity_mismatch" and not photo_error else None
        run.sections = {"biography": {"status": "succeeded", "reason": source_error, "revision": bio.pk}, "photo": {"status": "succeeded" if portrait else "not_available", "reason": photo_error}}
        if not getattr(settings, "FEC_API_KEY", ""):
            run.sections["finance"] = {"status": "not_available", "reason": "missing_fec_key"}
            run.status, run.finished_at = "partial", timezone.now()
        else:
            run.sections["finance"] = {"status": "running"}
            run.status = "running"
            continue_work(current, "finance")
        run.save(update_fields=["sections", "status", "finished_at"])
    return {"status": run.status}
