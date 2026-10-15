"""Explicit-follow content ranking; all weights are provisional local policy."""

import hashlib
import json
from dataclasses import dataclass
from fractions import Fraction

from django.db.models import (
    Case,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Prefetch,
    Q,
    Value,
    When,
    prefetch_related_objects,
)

from apps.congress.models import BillCosponsor
from apps.legislation.models import Bill, BillTopic

from .models import TrackedBill, TrackedLegislator, TrackedTopic
from .recommendation_support import FALLBACK_TOPIC, USABLE_TOPIC

ALGORITHM = "explicit-facets-mmr-v1"
POOL_LIMIT = 500
RANKING_LIMIT = 60


@dataclass
class InterestProfile:
    user_id: int
    fingerprint: str
    topics: dict
    representatives: dict
    seeds: dict
    topic_seeds: dict
    sponsor_seeds: dict
    follow_count: int
    unsupported: list

    @property
    def denominator(self):
        return 60 * bool(self.topics) + 40 * bool(
            self.representatives or self.sponsor_seeds
        )


def load_profile(user_id):
    topics = list(
        TrackedTopic.objects.filter(user_id=user_id)
        .order_by("topic_id")
        .values("topic_id", "topic__slug", "topic__name", "created_at")
    )
    reps = list(
        TrackedLegislator.objects.filter(user_id=user_id)
        .order_by("representative_id")
        .values("representative_id", "representative__name", "created_at")
    )
    seeds = list(
        TrackedBill.objects.filter(user_id=user_id)
        .order_by("bill_id")
        .values(
            "bill_id",
            "bill__bill_number",
            "bill__session",
            "bill__sponsor_id",
            "created_at",
        )
    )
    edges = list(
        BillTopic.objects.filter(USABLE_TOPIC, bill__tracked_by_users__user_id=user_id)
        .order_by("bill_id", "topic_id")
        .values("bill_id", "topic_id", "topic__name", "topic__slug", "confidence_score")
    )
    signature = hashlib.sha256(
        json.dumps(
            [topics, reps, seeds, edges], default=str, allow_nan=False, sort_keys=True
        ).encode()
    ).hexdigest()
    affinities = {
        item["topic_id"]: 100
        for item in topics
        if item["topic__slug"] != FALLBACK_TOPIC
    }
    topic_seeds = {}
    for edge in edges:
        affinities.setdefault(edge["topic_id"], 35)
        topic_seeds.setdefault(edge["topic_id"], edge["bill_id"])
    sponsor_seeds = {}
    for seed in seeds:
        if seed["bill__sponsor_id"] is not None:
            sponsor_seeds.setdefault(seed["bill__sponsor_id"], seed["bill_id"])
    return InterestProfile(
        user_id,
        signature,
        affinities,
        {item["representative_id"]: item["representative__name"] for item in reps},
        {item["bill_id"]: item for item in seeds},
        topic_seeds,
        sponsor_seeds,
        len(topics) + len(reps) + len(seeds),
        (
            ["general_legislation"]
            if any(item["topic__slug"] == FALLBACK_TOPIC for item in topics)
            else []
        ),
    )


def candidate_query(profile):
    user_id = profile.user_id
    followed_reps = TrackedLegislator.objects.filter(user_id=user_id).values(
        "representative_id"
    )
    seed_bills = TrackedBill.objects.filter(user_id=user_id)
    usable = BillTopic.objects.filter(USABLE_TOPIC, bill_id=OuterRef("pk"))
    seed_topics = BillTopic.objects.filter(
        USABLE_TOPIC, bill__tracked_by_users__user_id=user_id
    ).values("topic_id")
    direct_topic = Exists(usable.filter(topic__tracked_by_users__user_id=user_id))
    seed_topic = Exists(usable.filter(topic_id__in=seed_topics))
    active_cosponsor = Exists(
        BillCosponsor.objects.filter(
            bill_id=OuterRef("pk"),
            representative_id__in=followed_reps,
            withdrawn_at__isnull=True,
        )
    )
    query = (
        Bill.objects.filter(jurisdiction__in=("federal", "state"), session__gt=0)
        .exclude(Q(title__regex=r"^\s*$") | Q(bill_number__regex=r"^\s*$"))
        .exclude(pk__in=seed_bills.values("bill_id"))
        .annotate(
            recommendation_t=Case(
                When(direct_topic, then=Value(100)),
                When(seed_topic, then=Value(35)),
                default=Value(0),
                output_field=IntegerField(),
            ),
            recommendation_r=Case(
                When(sponsor_id__in=followed_reps, then=Value(100)),
                When(active_cosponsor, then=Value(75)),
                When(
                    sponsor_id__in=seed_bills.filter(
                        bill__sponsor_id__isnull=False
                    ).values("bill__sponsor_id"),
                    then=Value(35),
                ),
                default=Value(0),
                output_field=IntegerField(),
            ),
        )
    )
    crossover = (
        Case(
            When(
                recommendation_t__lte=F("recommendation_r"), then=F("recommendation_t")
            ),
            default=F("recommendation_r"),
            output_field=IntegerField(),
        )
        if profile.topics and (profile.representatives or profile.sponsor_seeds)
        else Value(0)
    )
    return (
        query.filter(Q(recommendation_t__gt=0) | Q(recommendation_r__gt=0))
        .annotate(
            recommendation_n=4
            * (60 * F("recommendation_t") + 40 * F("recommendation_r"))
            + profile.denominator * crossover
        )
        .order_by(
            "-recommendation_n",
            F("last_action_at").desc(nulls_last=True),
            F("introduced_at").desc(nulls_last=True),
            "id",
        )
    )


def metadata_similarity(left, right):
    union = left["topics"] | right["topics"]
    overlap = (
        Fraction(len(left["topics"] & right["topics"]), len(union))
        if union
        else Fraction(0)
    )
    same_sponsor = left["sponsor"] is not None and left["sponsor"] == right["sponsor"]
    return Fraction(7, 10) * overlap + Fraction(3, 10) * same_sponsor


def diverse_order(candidates, limit=RANKING_LIMIT):
    remaining = list(range(len(candidates)))
    redundancy = [Fraction(0) for _ in candidates]
    ordered = []
    while remaining and len(ordered) < limit:
        chosen = max(
            remaining,
            key=lambda i: (
                Fraction(9, 10) * candidates[i]["score"]
                - Fraction(1, 10) * redundancy[i],
                -i,
            ),
        )
        ordered.append(candidates[chosen])
        remaining.remove(chosen)
        for index in remaining:
            redundancy[index] = max(
                redundancy[index],
                metadata_similarity(candidates[index], candidates[chosen]),
            )
    return ordered


def reasons_for(bill, profile, cosponsors):
    reasons = []
    matching = sorted(
        (
            edge
            for edge in bill.recommendation_topics
            if edge.topic_id in profile.topics
        ),
        key=lambda edge: (-profile.topics[edge.topic_id], edge.topic_id),
    )
    if matching:
        edge = matching[0]
        reason = {
            "kind": "followed_topic",
            "topic_id": edge.topic_id,
            "name": edge.topic.name,
        }
        if profile.topics[edge.topic_id] == 35:
            seed = profile.seeds[profile.topic_seeds[edge.topic_id]]
            reason.update(
                kind="followed_bill_topic",
                seed_bill_id=seed["bill_id"],
                seed_bill_number=seed["bill__bill_number"],
                seed_session=seed["bill__session"],
            )
        reasons.append(reason)
    rep_matches = []
    if bill.sponsor_id in profile.representatives:
        rep_matches.append((100, bill.sponsor_id, "sponsor", None))
    for rep_id in cosponsors.get(bill.id, ()):
        rep_matches.append((75, rep_id, "cosponsor", None))
    if bill.sponsor_id in profile.sponsor_seeds:
        rep_matches.append(
            (35, bill.sponsor_id, "sponsor", profile.sponsor_seeds[bill.sponsor_id])
        )
    if rep_matches:
        strength, rep_id, relation, seed_id = min(
            rep_matches,
            key=lambda item: (-item[0], item[1], item[2] != "sponsor", item[3] or 0),
        )
        name = (
            profile.representatives.get(
                rep_id, bill.sponsor.name if bill.sponsor else ""
            )
            or "Name not recorded"
        )
        reason = {
            "kind": "followed_representative",
            "representative_id": rep_id,
            "name": name,
            "relation": relation,
        }
        if seed_id is not None:
            seed = profile.seeds[seed_id]
            reason.update(
                kind="followed_bill_sponsor",
                seed_bill_id=seed_id,
                seed_bill_number=seed["bill__bill_number"],
                seed_session=seed["bill__session"],
            )
        reasons.append(reason)
    return reasons


def build_ranking(profile):
    result = {
        "algorithm": ALGORITHM,
        "unsupported_follow_types": profile.unsupported,
        "candidate_pool_truncated": False,
        "ranking_limit_reached": False,
        "empty_reason": None,
        "results": [],
    }
    if not profile.denominator:
        result["empty_reason"] = (
            "no_follows"
            if not profile.follow_count
            else (
                "unsupported_follows_only"
                if profile.unsupported
                and not profile.seeds
                and not profile.representatives
                else "insufficient_metadata"
            )
        )
        return result
    rows = list(candidate_query(profile).select_related("sponsor")[: POOL_LIMIT + 1])
    result["candidate_pool_truncated"] = len(rows) > POOL_LIMIT
    rows = rows[:POOL_LIMIT]
    prefetch_related_objects(
        rows,
        Prefetch(
            "bill_topics",
            queryset=BillTopic.objects.filter(USABLE_TOPIC).select_related("topic"),
            to_attr="recommendation_topics",
        ),
    )
    cosponsors = {}
    for bill_id, rep_id in BillCosponsor.objects.filter(
        bill_id__in=[row.id for row in rows],
        withdrawn_at__isnull=True,
        representative__tracked_by_users__user_id=profile.user_id,
    ).values_list("bill_id", "representative_id"):
        cosponsors.setdefault(bill_id, set()).add(rep_id)
    candidates = []
    for row in rows:
        payload = {
            "id": row.id,
            "jurisdiction": row.jurisdiction,
            "session": row.session,
            "bill_number": row.bill_number,
            "title": row.title,
            "status": row.status,
            "sponsor_name": row.sponsor.name if row.sponsor else None,
            "introduced_at": (
                row.introduced_at.isoformat() if row.introduced_at else None
            ),
            "last_action_at": (
                row.last_action_at.isoformat() if row.last_action_at else None
            ),
            "topics": [
                {
                    "topic_id": edge.topic_id,
                    "name": edge.topic.name,
                    "slug": edge.topic.slug,
                    "confidence_score": edge.confidence_score,
                }
                for edge in row.recommendation_topics
            ],
            "search_rank": None,
            "highlights": [],
        }
        candidates.append(
            {
                "topics": {edge.topic_id for edge in row.recommendation_topics},
                "sponsor": row.sponsor_id,
                "score": Fraction(row.recommendation_n, 500 * profile.denominator),
                "bill": payload,
                "reasons": reasons_for(row, profile, cosponsors),
            }
        )
    result["results"] = [
        {
            "bill": item["bill"],
            "score": round(float(item["score"]), 6),
            "reasons": item["reasons"],
        }
        for item in diverse_order(candidates)
    ]
    result["ranking_limit_reached"] = len(candidates) > RANKING_LIMIT
    if not result["results"]:
        result["empty_reason"] = "no_matches"
    return result
