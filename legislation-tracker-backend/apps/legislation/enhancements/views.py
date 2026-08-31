from __future__ import annotations

from django.conf import settings
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.accounts.llm_credentials import llm_feature_available
from apps.accounts.models import LLMCredential
from apps.legislation.models import Bill, BillEnhancement, BillEnhancementAttempt

from .prompts import TRUNCATED_COVERAGE_NOTICE
from .serializers import EnhancementConfirmationSerializer, enhancement_payload
from .service import (
    EnhancementServiceError,
    create_enhancement_attempt,
    credential_is_current,
    retry_enhancement_attempt,
)
from .source_packet import PreflightUnavailable, build_enhancement_preflight


class PrivateEnhancementMixin:
    permission_classes = (IsAuthenticated,)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response

    def bill(self, bill_id):
        return get_object_or_404(Bill, pk=bill_id)


class LLMEnhancementThrottle(UserRateThrottle):
    scope = "llm_enhancement"


class EnhancementHistoryPagination(PageNumberPagination):
    page_size = 20
    max_page_size = 100
    page_size_query_param = "page_size"


ATTEMPT_PREFETCH = Prefetch(
    "attempts",
    queryset=BillEnhancementAttempt.objects.select_related("credential").order_by(
        "sequence"
    ),
    to_attr="ordered_attempts_cache",
)


def _service_error(exc: EnhancementServiceError):
    return Response({"error": exc.code}, status=exc.http_status)


def _is_stale(enhancement, bill) -> bool:
    try:
        current = build_enhancement_preflight(bill)
    except PreflightUnavailable:
        return True
    return current.request_fingerprint != enhancement.request_fingerprint


class BillEnhancementEstimateView(PrivateEnhancementMixin, APIView):
    def get(self, request, bill_id):
        bill = self.bill(bill_id)
        base = {
            "feature_available": llm_feature_available(),
            "can_enhance": False,
            "unavailable_reason": None,
            "credential_revision": None,
            "requested_model": settings.LLM_ENHANCEMENT_MODEL,
        }
        if not base["feature_available"]:
            return Response({**base, "unavailable_reason": "feature_unavailable"})
        if str(bill.jurisdiction or "").strip().lower() != "federal":
            return Response({**base, "unavailable_reason": "unsupported_jurisdiction"})
        credential = LLMCredential.objects.filter(user=request.user).first()
        base["credential_revision"] = credential.revision if credential else None
        if not credential_is_current(credential):
            if credential is None:
                reason = "credential_not_configured"
            elif not credential.enabled:
                reason = "credential_disabled"
            else:
                reason = "credential_unverified"
            return Response({**base, "unavailable_reason": reason})
        try:
            preflight = build_enhancement_preflight(bill)
        except PreflightUnavailable as exc:
            return Response({**base, "unavailable_reason": exc.reason})
        matching = (
            BillEnhancement.objects.filter(
                user=request.user,
                bill=bill,
                request_fingerprint=preflight.request_fingerprint,
            )
            .order_by("-created_at")
            .first()
        )
        return Response(
            {
                **base,
                "can_enhance": True,
                "provider": preflight.provider,
                "requested_model": preflight.requested_model,
                "reasoning_effort": preflight.reasoning_effort,
                "prompt_version": preflight.prompt_version,
                "output_schema_version": preflight.output_schema_version,
                "source_packet_version": preflight.source_packet_version,
                "source_fingerprint": preflight.source_fingerprint,
                "request_fingerprint": preflight.request_fingerprint,
                "serialized_request_bytes": len(preflight.request_bytes),
                "estimated_input_tokens": preflight.estimated_input_tokens,
                "max_output_tokens": settings.LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS,
                "max_output_includes_reasoning": True,
                "truncated": preflight.truncated,
                "coverage_notice": (
                    TRUNCATED_COVERAGE_NOTICE if preflight.truncated else None
                ),
                "source_description": preflight.source_manifest.get("source_kind"),
                "matching_enhancement": (
                    enhancement_payload(matching, detail=False) if matching else None
                ),
            }
        )


class BillEnhancementListCreateView(PrivateEnhancementMixin, APIView):
    def get(self, request, bill_id):
        bill = self.bill(bill_id)
        enhancements = (
            BillEnhancement.objects.filter(user=request.user, bill=bill)
            .prefetch_related(ATTEMPT_PREFETCH)
            .order_by("-created_at", "-id")
        )
        paginator = EnhancementHistoryPagination()
        page = paginator.paginate_queryset(enhancements, request, view=self)
        return paginator.get_paginated_response(
            [enhancement_payload(item, detail=False) for item in page]
        )

    def get_throttles(self):
        return [LLMEnhancementThrottle()] if self.request.method == "POST" else []

    def post(self, request, bill_id):
        bill = self.bill(bill_id)
        serializer = EnhancementConfirmationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = create_enhancement_attempt(
                user=request.user,
                bill=bill,
                confirmed=serializer.validated_data,
            )
        except EnhancementServiceError as exc:
            return _service_error(exc)
        return Response(
            enhancement_payload(result.enhancement, detail=True),
            status=status.HTTP_202_ACCEPTED if result.created else status.HTTP_200_OK,
        )


class BillEnhancementLatestView(PrivateEnhancementMixin, APIView):
    def get(self, request, bill_id):
        bill = self.bill(bill_id)
        enhancement = (
            BillEnhancement.objects.filter(user=request.user, bill=bill)
            .prefetch_related(ATTEMPT_PREFETCH)
            .order_by("-created_at", "-id")
            .first()
        )
        if enhancement is None:
            return Response({"error": "not_found"}, status=status.HTTP_404_NOT_FOUND)
        payload = enhancement_payload(enhancement, detail=True)
        payload["stale"] = _is_stale(enhancement, bill)
        return Response(payload)


class BillEnhancementDetailView(PrivateEnhancementMixin, APIView):
    def get(self, request, bill_id, enhancement_id):
        bill = self.bill(bill_id)
        enhancement = get_object_or_404(
            BillEnhancement.objects.prefetch_related(ATTEMPT_PREFETCH),
            pk=enhancement_id,
            user=request.user,
            bill=bill,
        )
        payload = enhancement_payload(enhancement, detail=True)
        payload["stale"] = _is_stale(enhancement, bill)
        return Response(payload)


class BillEnhancementRetryView(PrivateEnhancementMixin, APIView):
    throttle_classes = (LLMEnhancementThrottle,)

    def post(self, request, bill_id, enhancement_id):
        bill = self.bill(bill_id)
        serializer = EnhancementConfirmationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = retry_enhancement_attempt(
                user=request.user,
                bill=bill,
                enhancement_id=enhancement_id,
                confirmed=serializer.validated_data,
            )
        except EnhancementServiceError as exc:
            return _service_error(exc)
        return Response(
            enhancement_payload(result.enhancement, detail=True),
            status=status.HTTP_202_ACCEPTED if result.created else status.HTTP_200_OK,
        )
