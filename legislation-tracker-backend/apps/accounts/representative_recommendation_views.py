"""Neutral top-five discovery from explicit follows and public topic activity."""

import hashlib
import json
import re
from fractions import Fraction
from itertools import islice

from django.db.models import F, Value
from django.utils import timezone
from rest_framework.response import Response

from apps.congress.topic_activity import (
    cosine,
    cosine_vector,
    quantize_fraction,
    representative_activity_catalog,
)

from .models import TrackedLegislator, TrackedTopic
from .recommendation_filters import FILTER_NAMES, filter_bills, filter_key, read_filters
from .recommendation_support import (
    FALLBACK_TOPIC,
    PrivateRecommendationView,
    RecommendationError,
    RecommendationThrottle,
    activity_day,
    activity_revision,
    bounded_json,
    cache_call,
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


def ranking(catalog, followed_topics, followed_reps, eligible_ids=None, dismissed=()):
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
    directions = {key: cosine_vector(vector) for key, vector in vectors.items()}
    mean_direction = cosine_vector(mean)
    at, ar = bool(followed_topics), bool(mean)
    if not at and not ar:
        return [], "insufficient_metadata"
    matched_topics = set(followed_topics) | set(mean)
    candidates = []
    for key, item in records.items():
        rep_id, member = int(key), item["activity"]["representative"]
        if rep_id in dismissed or (
            eligible_ids is not None and rep_id not in eligible_ids
        ):
            continue
        vector = vectors[rep_id]
        matching = matched_topics.intersection(vector)
        matches = (
            unit for unit in item["union_topic_sets"] if not matching.isdisjoint(unit)
        )
        if (
            not member["is_current"]
            or rep_id in followed_reps
            or item["union_count"] < 5
            or next(islice(matches, 2, 3), None) is None
        ):
            continue
        topic_score = sum(
            (vector.get(topic_id, Fraction(0)) for topic_id in followed_topics),
            Fraction(0),
        )
        reference_score = (
            cosine(directions[rep_id], mean_direction) if ar else Fraction(0)
        )
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
                "reference_score": reference_score,
            }
        )
    candidates.sort(key=lambda item: item["tie"])
    selected, redundancy = [], {}
    while candidates and len(selected) < 6:
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
        rep_id = chosen["id"]
        item = records[str(rep_id)]
        vector = chosen["vector"]
        member = item["activity"]["representative"]
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
        if references and chosen["reference_score"]:
            reference_id = min(
                references,
                key=lambda identifier: (
                    -cosine(directions[rep_id], directions[identifier]),
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
        selected.append(
            {
                "representative_id": rep_id,
                "bioguide_id": member["bioguide_id"],
                "name": member["name"],
                "score": float(chosen["score"]),
                "reasons": reasons,
                "topic_activity_evidence": item["activity"],
            }
        )
        candidates.remove(chosen)
        for item in candidates:
            redundancy[item["id"]] = max(
                redundancy.get(item["id"], Fraction(0)),
                cosine(directions[item["id"]], directions[rep_id]),
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

    @staticmethod
    def with_cards(data):
        from .legislator_cards import cards_for_representatives

        results = data["results"]
        cards = cards_for_representatives(
            [item["representative_id"] for item in results],
            {
                item["representative_id"]: item["topic_activity_evidence"]
                for item in results
            },
        )
        # Research changes independently of the cached recommendation ranking.
        return {
            **data,
            "results": [
                {**item, "card": cards.get(item["representative_id"])}
                for item in results
            ],
        }

    def get(self, request):
        strict_parameters(request.query_params, FILTER_NAMES | {"shown"})
        shown = request.query_params.get("shown", "")
        if shown and (
            len(shown) > 8000
            or not re.fullmatch(r"[1-9][0-9]{0,9}(,[1-9][0-9]{0,9})*", shown)
        ):
            raise RecommendationError("invalid_recommendation_filter", 400)
        shown_ids = {int(value) for value in shown.split(",") if value}
        filters = read_filters(request.query_params)
        filters.pop("sort", None)  # Bill sort does not reorder people.

        # Fetch the three kinds of user preference in a single snapshot.
        def preferences(query, kind, identifier, name, slug):
            return query.order_by().values_list(Value(kind), F(identifier), name, slug)

        rows = preferences(
            TrackedTopic.objects.filter(user=request.user),
            "topic",
            "topic_id",
            F("topic__name"),
            F("topic__slug"),
        ).union(
            preferences(
                TrackedLegislator.objects.filter(user=request.user),
                "representative",
                "representative_id",
                F("representative__name"),
                Value(""),
            ),
            preferences(
                request.user.dismissed_representatives.all(),
                "dismissed",
                "pk",
                Value(""),
                Value(""),
            ),
            all=True,
        )
        topics, reps, dismissed = [], {}, set()
        with read_snapshot():
            revision = activity_revision()
            for kind, identifier, name, slug in rows:
                if kind == "topic":
                    topics.append(
                        {
                            "topic_id": identifier,
                            "topic__name": name,
                            "topic__slug": slug,
                        }
                    )
                elif kind == "representative":
                    reps[identifier] = name
                else:
                    dismissed.add(identifier)
        topics.sort(key=lambda item: item["topic_id"])
        followed_topics = {
            item["topic_id"]: item["topic__name"]
            for item in topics
            if item["topic__slug"] != FALLBACK_TOPIC
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                [
                    topics,
                    reps,
                    sorted(dismissed),
                    revision,
                    activity_day().isoformat(),
                ],
                sort_keys=True,
            ).encode()
        ).hexdigest()
        key = f"representative-recommendations:v3:user:{request.user.pk}" + (
            ":" + filter_key(filters) if filters else ""
        )
        if shown_ids:
            key += ":" + filter_key(sorted(shown_ids))
        cached = cache_call("get", key)
        if cached and cached["fingerprint"] == fingerprint:
            return Response(self.with_cards(cached["data"]))
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
            catalog = representative_activity_catalog(
                wait_for_build=True, revision=revision
            )
            if filters:
                from apps.congress.models import BillCosponsor
                from apps.legislation.models import Bill

                matching = filter_bills(Bill.objects.all(), filters).order_by()
                eligible = set(matching.values_list("sponsor_id", flat=True))
                eligible.update(
                    BillCosponsor.objects.filter(
                        bill__in=matching, withdrawn_at__isnull=True
                    ).values_list("representative_id", flat=True)
                )
                results, empty = ranking(
                    catalog, followed_topics, reps, eligible, dismissed | shown_ids
                )
            else:
                results, empty = ranking(
                    catalog, followed_topics, reps, dismissed=dismissed | shown_ids
                )
        response = Response(
            {
                "algorithm": "explicit-representative-topics-mmr-v1",
                "policy_version": catalog["policy_version"] if catalog else None,
                "generated_at": timezone.now().isoformat(),
                "activity_as_of": catalog["captured_at"] if catalog else None,
                "count": min(len(results), 5),
                "has_more": len(results) > 5,
                "empty_reason": empty,
                "unsupported_follow_types": unsupported,
                "coverage": {
                    "status": "ingested_subset",
                    "service_exposure": "unknown",
                    "bill_families": "unavailable",
                    "votes_used_for_ranking": False,
                },
                "results": results[:5],
            }
        )
        cache_call(
            "set",
            key,
            bounded_json(
                {"fingerprint": fingerprint, "data": response.data}, 3 * 1024 * 1024
            ),
            timeout=300,
        )
        return Response(self.with_cards(response.data))
