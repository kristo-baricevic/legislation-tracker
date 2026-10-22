"""One bounded stage per durable ingestion delivery; source I/O precedes locks."""
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from apps.congress.models import Representative
from apps.ingestion.models import IngestionWorkItem
from .models import ResearchRun, RepresentativeBiography
from .biographies import save_official_biography, save_excerpt
from .portraits import save_portrait


def fenced_work(work):
    current = IngestionWorkItem.objects.select_for_update().get(pk=work.pk)
    valid = (current.status == "processing" and current.dispatch_token == work.dispatch_token
             and current.lease_expires_at and current.lease_expires_at > timezone.now())
    return current if valid else None


def continue_work(current, stage):
    current.payload_json = {**current.payload_json, "stage": stage, "step": current.payload_json.get("step", 0) + 1}
    current.save(update_fields=["payload_json"])


def process_research(work):
    if work.payload_json.get("stage") == "finance":
        from apps.campaign_finance.research import process_finance
        return process_finance(work)
    run = ResearchRun.objects.select_related("representative").get(pk=work.payload_json["run_id"])
    rep = run.representative
    depiction = {"imageUrl": rep.image_url}
    excerpt = None
    source_error = ""
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
    if getattr(settings, "LEGISLATOR_WIKIPEDIA_ENABLED", False):
        from apps.congress.biography import _snapshot, BiographyUnavailable
        try:
            excerpt = _snapshot(rep.bioguide_id)
        except BiographyUnavailable:
            source_error = source_error or "biography_source_unavailable"
    with transaction.atomic():
        current = fenced_work(work)
        if current is None:
            return {"status": "superseded"}
        Representative.objects.select_for_update().get(pk=rep.pk)
        bio = save_excerpt(rep, excerpt) if excerpt else None
        if not bio:
            bio = RepresentativeBiography.objects.filter(representative=rep).order_by("-id").first() or save_official_biography(rep)
        portrait = save_portrait(rep, depiction) if not source_error == "identity_mismatch" else None
        run.sections = {"biography": {"status": "succeeded", "reason": source_error, "revision": bio.pk}, "photo": {"status": "succeeded" if portrait else "not_available"}}
        if not getattr(settings, "FEC_API_KEY", ""):
            run.sections["finance"] = {"status": "not_available", "reason": "missing_fec_key"}
            run.status, run.finished_at = "partial", timezone.now()
        else:
            run.sections["finance"] = {"status": "running"}
            run.status = "running"
            continue_work(current, "finance")
        run.save(update_fields=["sections", "status", "finished_at"])
    return {"status": run.status}
