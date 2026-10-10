"""Short-lived, user-bound pagination for explicit-follow bill discovery."""

import secrets
from datetime import timedelta

from django.core import signing
from django.utils import timezone
from rest_framework.response import Response

from .recommendation_support import (
    PrivateRecommendationView,
    RecommendationError,
    bounded_json,
    cache_call,
    read_snapshot,
    strict_parameters,
)
from .recommendations import ALGORITHM, build_ranking, candidate_query, load_profile

CURSOR_SALT = "accounts.bill-recommendations.v1"
SNAPSHOT_SECONDS = 300
SNAPSHOT_BYTES = 1024 * 1024


def snapshot_key(user_id):
    return f"bill-recommendations:v1:user:{user_id}"


def decode_cursor(token, user_id):
    if len(token) > 2048:
        raise RecommendationError("invalid_recommendation_cursor", 400)
    try:
        value = signing.loads(token, salt=CURSOR_SALT)
    except (signing.BadSignature, ValueError, TypeError) as exc:
        raise RecommendationError("invalid_recommendation_cursor", 400) from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "user_id", "nonce", "offset", "page_size"}
        or value["version"] != ALGORITHM
        or type(value["user_id"]) is not int
        or value["user_id"] != user_id
        or not isinstance(value["nonce"], str)
        or len(value["nonce"]) != 32
        or type(value["offset"]) is not int
        or type(value["page_size"]) is not int
        or not 1 <= value["page_size"] <= 12
        or value["offset"] <= 0
        or value["offset"] % value["page_size"]
    ):
        raise RecommendationError("invalid_recommendation_cursor", 400)
    try:
        signing.loads(token, salt=CURSOR_SALT, max_age=SNAPSHOT_SECONDS)
    except signing.SignatureExpired as exc:
        raise RecommendationError("recommendations_expired", 410) from exc
    return value


def page_size(params, cursor):
    if "page_size" not in params:
        return cursor["page_size"] if cursor else 6
    value = params["page_size"]
    if not value.isascii() or not value.isdecimal() or len(value) > 2:
        raise RecommendationError("invalid_recommendation_page_size", 400)
    size = int(value)
    if not 1 <= size <= 12 or (cursor and size != cursor["page_size"]):
        raise RecommendationError("invalid_recommendation_page_size", 400)
    return size


class BillRecommendationView(PrivateRecommendationView):
    def get(self, request):
        params = request.query_params
        strict_parameters(params, {"page_size", "cursor"})
        cursor = (
            decode_cursor(params["cursor"], request.user.pk)
            if "cursor" in params
            else None
        )
        size = page_size(params, cursor)
        key = snapshot_key(request.user.pk)
        now = timezone.now()
        offset = cursor["offset"] if cursor else 0
        with read_snapshot():
            profile = load_profile(request.user.pk)
            if cursor:
                snapshot = cache_call("get", key)
                if snapshot is None or snapshot["expires_at"] <= now.timestamp():
                    raise RecommendationError("recommendations_expired", 410)
                if (
                    snapshot["nonce"] != cursor["nonce"]
                    or snapshot["fingerprint"] != profile.fingerprint
                ):
                    raise RecommendationError("recommendations_changed", 409)
                if size != snapshot["page_size"] or offset >= len(snapshot["results"]):
                    raise RecommendationError("invalid_recommendation_cursor", 400)
                ids = [
                    item["bill"]["id"]
                    for item in snapshot["results"][offset : offset + size]
                ]
                eligible = set(
                    candidate_query(profile)
                    .filter(pk__in=ids)
                    .values_list("id", flat=True)
                )
                if eligible != set(ids):
                    raise RecommendationError("recommendations_changed", 409)
            else:
                ranking = build_ranking(profile)
                snapshot = bounded_json(
                    {
                        **ranking,
                        "generated_at": now.isoformat(),
                        "expires_at": (
                            now + timedelta(seconds=SNAPSHOT_SECONDS)
                        ).timestamp(),
                        "nonce": secrets.token_hex(16),
                        "fingerprint": profile.fingerprint,
                        "page_size": size,
                    },
                    SNAPSHOT_BYTES,
                )
        if not cursor:
            remaining = int(snapshot["expires_at"] - timezone.now().timestamp())
            if remaining <= 0:
                raise RecommendationError()
            cache_call("set", key, snapshot, timeout=remaining)
        else:
            current = cache_call("get", key)
            if current is None:
                raise RecommendationError("recommendations_expired", 410)
            if current["nonce"] != snapshot["nonce"]:
                raise RecommendationError("recommendations_changed", 409)
        next_offset = offset + size
        token = (
            signing.dumps(
                {
                    "version": ALGORITHM,
                    "user_id": request.user.pk,
                    "nonce": snapshot["nonce"],
                    "offset": next_offset,
                    "page_size": size,
                },
                salt=CURSOR_SALT,
            )
            if next_offset < len(snapshot["results"])
            else None
        )
        return Response(
            {
                **{
                    key: snapshot[key]
                    for key in (
                        "algorithm",
                        "generated_at",
                        "candidate_pool_truncated",
                        "ranking_limit_reached",
                        "empty_reason",
                        "unsupported_follow_types",
                    )
                },
                "count": len(snapshot["results"]),
                "next_cursor": token,
                "results": snapshot["results"][offset:next_offset],
            }
        )
