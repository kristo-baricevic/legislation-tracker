"""Neutral top-five discovery from explicit follows and public topic activity."""

from fractions import Fraction

from django.utils import timezone
from rest_framework.response import Response

from apps.congress.topic_activity import (
    cosine,
    quantize_fraction,
    representative_activity_catalog,
)

from .models import TrackedLegislator, TrackedTopic
from .recommendation_support import (
    FALLBACK_TOPIC,
    PrivateRecommendationView,
    RecommendationThrottle,
    read_snapshot,
    strict_parameters,
)


class RepresentativeRecommendationThrottle(RecommendationThrottle):
    scope = "representative_recommendations"


def vector_for(item):
    return {
        int(key): Fraction(int(value["numerator"]), int(value["denominator"]))
        for key, value in item["vector"].items()
    }


def ranking(catalog, followed_topics, followed_reps):
    records = catalog["representatives"]
    vectors = {int(key): vector_for(value) for key, value in records.items()}
    references = {
        rep_id: vectors[rep_id]
        for rep_id in followed_reps
        if rep_id in vectors
        and records[str(rep_id)]["union_tagged_count"] >= 5
        and vectors[rep_id]
    }
    mean = {}
    for vector in references.values():
        for key, value in vector.items():
            mean[key] = mean.get(key, Fraction(0)) + value / len(references)
    at, ar = bool(followed_topics), bool(mean)
    if not at and not ar:
        return [], "insufficient_metadata"
    matched_topics = set(followed_topics) | set(mean)
    candidates = []
    for key, item in records.items():
        rep_id, member = int(key), item["activity"]["representative"]
        vector = vectors[rep_id]
        matched_evidence = sum(
            bool(set(unit) & matched_topics & vector.keys())
            for unit in item["union_topic_sets"]
        )
        if (
            not member["is_current"]
            or rep_id in followed_reps
            or item["union_count"] < 5
            or matched_evidence < 3
        ):
            continue
        topic_score = sum(
            (vector.get(topic_id, Fraction(0)) for topic_id in followed_topics),
            Fraction(0),
        )
        reference_score = cosine(vector, mean) if ar else Fraction(0)
        if not topic_score and not reference_score:
            continue
        cross = min(topic_score, reference_score) if at and ar else Fraction(0)
        base = (
            Fraction(4, 5) * (7 * topic_score + 3 * reference_score) / (7 * at + 3 * ar)
            + Fraction(1, 5) * cross
        )
        evidence_discount = Fraction(
            item["union_tagged_count"], item["union_count"] + 20
        )
        score = quantize_fraction(base * evidence_discount)
        reasons = []
        explicit = sorted(
            (topic_id for topic_id in followed_topics if vector.get(topic_id, 0) > 0),
            key=lambda topic_id: (-vector[topic_id], topic_id),
        )[:2]
        for topic_id in explicit:
            reasons.append(
                {
                    "kind": "followed_topic",
                    "topic_id": topic_id,
                    "name": followed_topics[topic_id],
                    "shared_topics": [catalog["topics"][str(topic_id)]],
                    "channel_evidence": _topic_evidence(item["activity"], topic_id),
                }
            )
        if references and reference_score:
            reference_id = min(
                references,
                key=lambda identifier: (
                    -cosine(vector, references[identifier]),
                    records[str(identifier)]["activity"]["representative"][
                        "bioguide_id"
                    ],
                    identifier,
                ),
            )
            shared = sorted(
                vector.keys() & references[reference_id].keys(),
                key=lambda topic_id: (
                    -min(vector[topic_id], references[reference_id][topic_id]),
                    topic_id,
                ),
            )[:2]
            if shared:
                reasons.append(
                    {
                        "kind": "followed_representative_activity",
                        "representative_id": reference_id,
                        "name": followed_reps[reference_id],
                        "shared_topics": [
                            catalog["topics"][str(topic_id)] for topic_id in shared
                        ],
                        "channel_evidence": {
                            str(topic_id): _topic_evidence(item["activity"], topic_id)
                            for topic_id in shared
                        },
                    }
                )
        candidates.append(
            {
                "id": rep_id,
                "vector": vector,
                "score": score,
                "tie": (
                    -score,
                    -len(set(followed_topics) & vector.keys()),
                    -item["union_tagged_count"],
                    member["bioguide_id"],
                    rep_id,
                ),
                "payload": {
                    "representative_id": rep_id,
                    "bioguide_id": member["bioguide_id"],
                    "name": member["name"],
                    "score": float(score),
                    "reasons": reasons,
                    "topic_activity_evidence": item["activity"],
                },
            }
        )
    candidates.sort(key=lambda item: item["tie"])
    selected, redundancy = [], {}
    while candidates and len(selected) < 5:
        chosen = min(
            candidates,
            key=lambda item: (
                -(
                    Fraction(9, 10) * item["score"]
                    - Fraction(1, 10) * redundancy.get(item["id"], Fraction(0))
                ),
                item["tie"],
            ),
        )
        selected.append(chosen["payload"])
        candidates.remove(chosen)
        for item in candidates:
            redundancy[item["id"]] = max(
                redundancy.get(item["id"], Fraction(0)),
                cosine(item["vector"], chosen["vector"]),
            )
    return selected, None if selected else "no_matches"


def _topic_evidence(activity, topic_id):
    result = {}
    for name, channel in activity["channels"].items():
        metric = next(
            (value for value in channel["topics"] if value["topic"]["id"] == topic_id),
            None,
        )
        result[name] = {
            "status": channel["status"],
            "raw_observation_count": channel["raw_observation_count"],
            "grouped_observation_count": channel["grouped_observation_count"],
            "raw_tag_coverage": channel["raw_tag_coverage"],
            "grouped_tag_coverage": channel["grouped_tag_coverage"],
            "topic": metric,
        }
    return result


class RepresentativeRecommendationView(PrivateRecommendationView):
    throttle_classes = [RepresentativeRecommendationThrottle]

    def get(self, request):
        strict_parameters(request.query_params, set())
        with read_snapshot():
            topics = list(
                TrackedTopic.objects.filter(user=request.user)
                .order_by("topic_id")
                .values("topic_id", "topic__slug", "topic__name")
            )
            reps = dict(
                TrackedLegislator.objects.filter(user=request.user)
                .order_by("representative_id")
                .values_list("representative_id", "representative__name")
            )
        followed_topics = {
            item["topic_id"]: item["topic__name"]
            for item in topics
            if item["topic__slug"] != FALLBACK_TOPIC
        }
        unsupported = (
            ["general_legislation"]
            if any(item["topic__slug"] == FALLBACK_TOPIC for item in topics)
            else []
        )
        if not topics and not reps:
            results, empty, catalog = [], "no_follows", None
        elif not followed_topics and not reps:
            results, empty, catalog = [], "unsupported_follows_only", None
        else:
            catalog = representative_activity_catalog()
            results, empty = ranking(catalog, followed_topics, reps)
        return Response(
            {
                "algorithm": "explicit-representative-topics-mmr-v1",
                "policy_version": catalog["policy_version"] if catalog else None,
                "generated_at": timezone.now().isoformat(),
                "activity_as_of": catalog["captured_at"] if catalog else None,
                "count": len(results),
                "empty_reason": empty,
                "unsupported_follow_types": unsupported,
                "coverage": {
                    "status": "ingested_subset",
                    "service_exposure": "unknown",
                    "bill_families": "unavailable",
                    "votes_used_for_ranking": False,
                },
                "results": results,
            }
        )
