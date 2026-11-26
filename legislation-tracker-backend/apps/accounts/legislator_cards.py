"""Batch-load saved profile facts, without starting research or fetching donors."""

from django.db.models import Exists, OuterRef, Prefetch
from django.db.models.functions import JSONObject
from django.utils import timezone

from apps.legislation.models import Bill
from apps.research.models import (
    RepresentativeBiography,
    RepresentativePortrait,
    ResearchRun,
)
from apps.research.portraits import approved_portrait_policy


def with_card_facts(queryset):
    # Each scalar subquery returns at most one row per representative, even
    # when multiple biographies, portraits and bills exist for the same person.
    source = JSONObject(
        url="source__url", attribution="source__attribution", license="source__license"
    )
    latest_bio = RepresentativeBiography.objects.filter(
        representative_id=OuterRef("pk")
    ).order_by("-pk")
    latest_photo = RepresentativePortrait.objects.filter(
        representative_id=OuterRef("pk")
    ).order_by("-pk")
    latest_bill = Bill.objects.filter(
        sponsor_id=OuterRef("pk"), introduced_at__isnull=False
    ).order_by("-introduced_at", "-pk")
    policy = approved_portrait_policy(
        OuterRef("representative_id"),
        OuterRef("image_url"),
        OuterRef("source__license"),
        OuterRef("source__attribution"),
    )
    return (
        queryset.only("pk")
        .annotate(
            card_bio=latest_bio.values(data=JSONObject(text="text", source=source))[:1],
            card_photo=latest_photo.values(
                data=JSONObject(
                    id="pk",
                    object_key="object_key",
                    url="image_url",
                    approved=Exists(policy),
                    source=source,
                )
            )[:1],
            card_bill=latest_bill.values(
                data=JSONObject(
                    id="pk",
                    title="title",
                    bill_number="bill_number",
                    introduced_at="introduced_at",
                    session="session",
                )
            )[:1],
        )
        .prefetch_related(
            Prefetch(
                "researchrun_set",
                queryset=ResearchRun.objects.filter(
                    period=timezone.now().year + timezone.now().year % 2
                )
                .select_related("work_item")
                .order_by("-created_at", "-pk")[:1],
                to_attr="card_runs",
            )
        )
    )


def card_facts(rep):
    photo = getattr(rep, "card_photo", None)
    run = next(iter(getattr(rep, "card_runs", [])), None)
    return {
        "biography": getattr(rep, "card_bio", None),
        "portrait": (
            {
                "url": (
                    f"/api/representatives/{rep.pk}/portraits/{photo['id']}/"
                    if photo["object_key"] and photo["approved"]
                    else photo["url"]
                ),
                "source": photo["source"],
            }
            if photo
            else None
        ),
        "latest_bill": getattr(rep, "card_bill", None),
        "research": {
            "status": run.effective_status if run else "not_started",
            "period": (
                run.period if run else timezone.now().year + timezone.now().year % 2
            ),
            "overview_ready": bool(
                run
                and run.work_item
                and run.work_item.payload_json.get("finance_phase") == "receipts"
            ),
        },
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
            catalog = representative_activity_catalog(
                representative_ids=ids, wait_for_build=True
            )
            activities = {
                int(key): item["activity"]
                for key, item in catalog["representatives"].items()
            }
        except RecommendationError:
            activities = {}
    cards = {}
    for rep in with_card_facts(Representative.objects.filter(pk__in=ids)):
        activity = activities.get(rep.pk)
        topics = {}
        for channel in ("sponsor", "active_cosponsor"):
            for metric in (
                (activity or {}).get("channels", {}).get(channel, {}).get("topics", [])
            ):
                count = metric["grouped"]["topic_observation_count"]
                if count > 0:
                    topic = metric["topic"]
                    entry = topics.setdefault(
                        topic["id"],
                        {"id": topic["id"], "name": topic["name"], "count": 0},
                    )
                    entry["count"] += count
        cards[rep.pk] = {
            **card_facts(rep),
            "top_topics": sorted(
                topics.values(), key=lambda item: (-item["count"], item["id"])
            )[:3],
            "topics_available": activity is not None,
        }
    return cards
