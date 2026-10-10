"""Shared privacy, consistency and usable-metadata policy for discovery."""

import json
from contextlib import contextmanager

from django.core.cache import cache
from django.db import DatabaseError, connection, transaction
from django.db.models import Q
from django.utils.cache import patch_vary_headers
from rest_framework.exceptions import APIException
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

FALLBACK_TOPIC = "general-legislation"
USABLE_TOPIC = ~Q(topic__slug=FALLBACK_TOPIC) & (
    Q(confidence_score__isnull=True)
    | (Q(confidence_score__gt=0) & Q(confidence_score__lt=float("inf")))
)


class RecommendationError(APIException):
    def __init__(self, detail="recommendations_unavailable", status=503):
        self.status_code = status
        self.wait = 5 if status == 503 else None
        super().__init__(detail)


def cache_call(method, *args, **kwargs):
    try:
        return getattr(cache, method)(*args, **kwargs)
    except Exception as exc:
        raise RecommendationError() from exc


def bounded_json(value, ceiling):
    try:
        encoded = json.dumps(value, allow_nan=False, separators=(",", ":"))
    except (ValueError, TypeError) as exc:
        raise RecommendationError("recommendations_metadata_invalid") from exc
    if len(encoded.encode("utf-8")) > ceiling:
        raise RecommendationError("recommendations_metadata_too_large")
    return json.loads(encoded)


@contextmanager
def read_snapshot():
    # The request must own its PostgreSQL transaction. Auth executes before it.
    if connection.vendor == "postgresql" and connection.in_atomic_block:
        raise RecommendationError("recommendations_transaction_unavailable")
    with transaction.atomic():
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
        yield


class RecommendationThrottle(UserRateThrottle):
    scope = "bill_recommendations"
    rate = "30/min"

    def allow_request(self, request, view):
        try:
            return super().allow_request(request, view)
        except Exception as exc:
            raise RecommendationError() from exc


class PrivateRecommendationView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [RecommendationThrottle]

    def handle_exception(self, exc):
        if isinstance(exc, DatabaseError):
            exc = RecommendationError()
        return super().handle_exception(exc)

    def finalize_response(self, request, response, *args, **kwargs):
        result = super().finalize_response(request, response, *args, **kwargs)
        result["Cache-Control"] = "private, no-store"
        patch_vary_headers(result, ["Cookie", "Authorization"])
        return result


def strict_parameters(params, allowed):
    if any(key not in allowed or len(params.getlist(key)) != 1 for key in params):
        raise RecommendationError("invalid_recommendation_parameters", 400)
