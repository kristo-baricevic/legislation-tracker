"""Batch-load saved profile facts, without starting research or fetching donors."""
from django.db.models import F, Prefetch
from django.utils import timezone
from apps.legislation.models import Bill
from apps.research.models import RepresentativeBiography, RepresentativePortrait, ResearchRun
from apps.research.portraits import may_serve_portrait


def with_card_facts(queryset, prefix="representative__"):
    return queryset.prefetch_related(
        Prefetch(f"{prefix}researchrun_set",
                 queryset=ResearchRun.objects.filter(period=timezone.now().year + timezone.now().year % 2).select_related("work_item").order_by("-created_at")[:1],
                 to_attr="card_runs"),
        Prefetch(f"{prefix}representativebiography_set",
                 queryset=RepresentativeBiography.objects.select_related("source").order_by("-id")[:1],
                 to_attr="card_bios"),
        Prefetch(f"{prefix}representativeportrait_set",
                 queryset=RepresentativePortrait.objects.select_related("source").order_by("-id")[:1],
                 to_attr="card_photos"),
        Prefetch(f"{prefix}sponsored_bills",
                 queryset=Bill.objects.filter(introduced_at__isnull=False).order_by(F("introduced_at").desc(), "-id")[:1],
                 to_attr="card_bills"),
    )


def card_facts(rep):
    bio = next(iter(getattr(rep, "card_bios", [])), None)
    photo = next(iter(getattr(rep, "card_photos", [])), None)
    bill = next(iter(getattr(rep, "card_bills", [])), None)
    run = next(iter(getattr(rep, "card_runs", [])), None)
    from apps.research.views import run_data
    job = run_data(run)
    def source(item):
        return {"url": item.source.url, "attribution": item.source.attribution, "license": item.source.license}
    return {
        "biography": {"text": bio.text, "source": source(bio)} if bio else None,
        "portrait": {"url": f"/api/representatives/{rep.pk}/portraits/{photo.pk}/" if photo.object_key and may_serve_portrait(photo) else photo.image_url, "source": source(photo)} if photo else None,
        "latest_bill": {"id": bill.pk, "title": bill.title, "bill_number": bill.bill_number, "introduced_at": bill.introduced_at, "session": bill.session} if bill else None,
        "research": {"status": job["status"] if job else "not_started", "period": run.period if run else timezone.now().year + timezone.now().year % 2,
                     "overview_ready": bool(run and run.work_item and run.work_item.payload_json.get("finance_phase") == "receipts")},
    }


def cards_for_representatives(ids, activities=None):
    """One batch of profile queries and one activity catalog for the whole row."""
    from apps.congress.models import Representative
    from apps.congress.topic_activity import representative_activity_catalog
    from .recommendation_support import RecommendationError
    ids = list(ids)
    if not ids:
        return {}
    if activities is None:
        try:
            catalog = representative_activity_catalog()
            activities = {int(key): item["activity"] for key, item in catalog["representatives"].items()}
        except RecommendationError:
            activities = {}
    cards = {}
    for rep in with_card_facts(Representative.objects.filter(pk__in=ids), prefix=""):
        activity = activities.get(rep.pk)
        topics = {}
        for channel in ("sponsor", "active_cosponsor"):
            for metric in (activity or {}).get("channels", {}).get(channel, {}).get("topics", []):
                count = metric["grouped"]["topic_observation_count"]
                if count > 0:
                    topic = metric["topic"]
                    entry = topics.setdefault(topic["id"], {"id": topic["id"], "name": topic["name"], "count": 0})
                    entry["count"] += count
        cards[rep.pk] = {**card_facts(rep), "top_topics": sorted(topics.values(), key=lambda item: (-item["count"], item["id"]))[:3], "topics_available": activity is not None}
    return cards
