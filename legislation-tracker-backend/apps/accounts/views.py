"""
Auth API, user preferences, and private tracking APIs.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.db.models import Q
from django.middleware.csrf import get_token
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from apps.changelog.models import ChangeLog
from apps.congress.models import Representative
from apps.legislation.models import Bill, Topic
from apps.legislation.serializers import BillListSerializer

from .authentication import enforce_csrf
from .models import (
    SavedBillSearch,
    TrackedBill,
    TrackedLegislator,
    TrackedTopic,
    UserPreference,
)
from .saved_searches import (
    count_saved_search_new_results,
    create_saved_search,
    open_saved_search,
    saved_search_result_page,
)
from .serializers import (
    RegistrationSerializer,
    SavedBillSearchSerializer,
    SavedBillSearchWriteSerializer,
    SessionTokenObtainPairSerializer,
    TrackedBillSerializer,
    TrackedLegislatorSerializer,
    TrackedTopicSerializer,
    TrackingFeedEntrySerializer,
    UserPreferenceSerializer,
)
from .throttles import LoginThrottle, RefreshThrottle, RegistrationThrottle

User = get_user_model()


def parse_required_int_param(raw_value, field_name):
    if raw_value in (None, ""):
        return None, Response(
            {"error": f"{field_name} is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        return int(raw_value), None
    except (TypeError, ValueError):
        return None, Response(
            {"error": f"{field_name} must be an integer"},
            status=status.HTTP_400_BAD_REQUEST,
        )


class RegisterView(APIView):
    """Accept a valid registration without disclosing account existence."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [RegistrationThrottle]

    def post(self, request: Request) -> Response:
        enforce_csrf(request)
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.register()
        return Response(
            {
                "detail": (
                    "If the address can be registered, the account is ready to sign in."
                )
            },
            status=status.HTTP_202_ACCEPTED,
        )


def _set_auth_cookie(response, name, value, *, max_age, path="/"):
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path=path,
    )


def _set_token_cookies(response, *, access, refresh=None):
    _set_auth_cookie(
        response,
        settings.AUTH_ACCESS_COOKIE_NAME,
        access,
        max_age=int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds()),
    )
    if refresh is not None:
        _set_auth_cookie(
            response,
            settings.AUTH_REFRESH_COOKIE_NAME,
            refresh,
            max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
            path=settings.AUTH_REFRESH_COOKIE_PATH,
        )


def _clear_token_cookies(response):
    response.delete_cookie(
        settings.AUTH_ACCESS_COOKIE_NAME,
        path="/",
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )
    response.delete_cookie(
        settings.AUTH_REFRESH_COOKIE_NAME,
        path=settings.AUTH_REFRESH_COOKIE_PATH,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )


class SessionLoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [LoginThrottle]

    def post(self, request: Request) -> Response:
        enforce_csrf(request)
        serializer = SessionTokenObtainPairSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        get_token(request._request)
        response = Response(
            {
                "authenticated": True,
                "user": {"email": serializer.user.email},
            }
        )
        _set_token_cookies(
            response,
            access=serializer.validated_data["access"],
            refresh=serializer.validated_data["refresh"],
        )
        return response


class CSRFTokenView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request: Request) -> Response:
        return Response({"csrf_token": get_token(request._request)})


class SessionStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(
            {
                "authenticated": True,
                "user": {"email": request.user.email},
            }
        )


class SessionRefreshView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [RefreshThrottle]

    def post(self, request: Request) -> Response:
        enforce_csrf(request)
        refresh = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE_NAME)
        if not refresh:
            return Response(
                {"detail": "No refresh session is available."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        serializer = TokenRefreshSerializer(data={"refresh": refresh})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError:
            return Response(
                {"detail": "The refresh session is invalid."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        get_token(request._request)
        response = Response({"authenticated": True})
        _set_token_cookies(
            response,
            access=serializer.validated_data["access"],
            refresh=serializer.validated_data.get("refresh"),
        )
        return response


class SessionLogoutView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request: Request) -> Response:
        enforce_csrf(request)
        refresh = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE_NAME)
        if refresh:
            try:
                RefreshToken(refresh).blacklist()
            except (AttributeError, TokenError):
                pass
        response = Response(status=status.HTTP_204_NO_CONTENT)
        _clear_token_cookies(response)
        return response


class UserPreferenceViewSet(viewsets.ModelViewSet):
    """CRUD for the current user's preferences."""

    permission_classes = [IsAuthenticated]
    serializer_class = UserPreferenceSerializer

    def get_queryset(self):
        return UserPreference.objects.filter(user=self.request.user).order_by("id")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def _topic_payload_error(self, request):
        if "topic" in request.data:
            return Response(
                {"error": "Use the topic tracking endpoints to follow topics."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return None

    def create(self, request, *args, **kwargs):
        if error_response := self._topic_payload_error(request):
            return error_response
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if error_response := self._topic_payload_error(request):
            return error_response
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if error_response := self._topic_payload_error(request):
            return error_response
        return super().partial_update(request, *args, **kwargs)


class SavedBillSearchViewSet(viewsets.ModelViewSet):
    """Owner-scoped saved discovery queries and explicit result acknowledgement."""

    permission_classes = [IsAuthenticated]
    queryset = SavedBillSearch.objects.all()

    def get_queryset(self):
        return SavedBillSearch.objects.filter(user=self.request.user).order_by(
            "-updated_at", "-id"
        )

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return SavedBillSearchWriteSerializer
        return SavedBillSearchSerializer

    def list(self, request, *args, **kwargs):
        searches = list(self.get_queryset())
        counts = count_saved_search_new_results(searches)
        for search in searches:
            search.new_result_count = counts[search.id]
        return Response({"count": len(searches), "results": SavedBillSearchSerializer(searches, many=True).data})

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            search = create_saved_search(
                user=request.user,
                name=serializer.validated_data["name"],
                query_json=serializer.validated_data["query"],
                normalized_hash=serializer._normalized_hash,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(SavedBillSearchSerializer(search).data, status=status.HTTP_201_CREATED)

    def _update(self, request, partial):
        search = self.get_object()
        serializer = self.get_serializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        if "name" in values:
            search.name = values["name"]
        if "query" in values:
            search.query_json = values["query"]
            search.normalized_hash = serializer._normalized_hash
            search.last_opened_at = None
            search.last_opened_activity_sequence = None
        try:
            search.save()
        except IntegrityError:
            return Response(
                {"detail": "A saved search already uses that name or query."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(SavedBillSearchSerializer(search).data)

    def update(self, request, *args, **kwargs):
        return self._update(request, partial=False)

    def partial_update(self, request, *args, **kwargs):
        return self._update(request, partial=True)

    @action(detail=True, methods=["get"])
    def results(self, request, pk=None):
        from config.api import PaginatedQuerySerializer

        query = PaginatedQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        page = query.validated_data.get("page", 1)
        page_size = query.validated_data.get("page_size", 20)
        search = self.get_object()
        result, watermark = saved_search_result_page(
            user=request.user,
            search=search,
            page=page,
            page_size=page_size,
        )
        hits = {hit.bill_id: hit for hit in result.hits}
        bill_ids = list(hits)
        bills = list(
            Bill.objects.select_related("sponsor", "latest_contract")
            .prefetch_related("bill_topics__topic")
            .filter(pk__in=bill_ids)
        )
        bills.sort(key=lambda bill: bill_ids.index(bill.id))
        payload = BillListSerializer(
            bills,
            many=True,
            context={
                "search_ranks": {bill_id: hit.rank for bill_id, hit in hits.items()},
                "search_highlights": {
                    bill_id: [
                        {
                            "kind": highlight.kind,
                            "segments": [
                                {"text": segment.text, "matched": segment.matched}
                                for segment in highlight.segments
                            ],
                        }
                        for highlight in hit.highlights
                    ]
                    for bill_id, hit in hits.items()
                },
            },
        ).data
        return Response(
            {
                "count": result.count,
                "results": payload,
                "result_watermark": watermark,
            }
        )

    @action(detail=True, methods=["post"])
    def open(self, request, pk=None):
        watermark = request.data.get("result_watermark")
        if not isinstance(watermark, str):
            return Response(
                {"result_watermark": ["This field is required."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            search, prior_sequence = open_saved_search(
                user=request.user,
                search=self.get_object(),
                watermark_value=watermark,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "previous_activity_sequence": prior_sequence,
                "last_opened_activity_sequence": search.last_opened_activity_sequence,
                "last_opened_at": search.last_opened_at,
            }
        )


class TrackingSummaryView(APIView):
    """Current user's tracked bills, topics, and legislators."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        bills = TrackedBill.objects.filter(user=request.user).select_related(
            "bill",
            "bill__sponsor",
        )
        topics = TrackedTopic.objects.filter(user=request.user).select_related("topic")
        legislators = TrackedLegislator.objects.filter(
            user=request.user
        ).select_related("representative")
        return Response(
            {
                "bills": TrackedBillSerializer(bills, many=True).data,
                "topics": TrackedTopicSerializer(topics, many=True).data,
                "legislators": TrackedLegislatorSerializer(legislators, many=True).data,
                "is_staff": request.user.is_staff,
            }
        )


class TrackingFeedView(APIView):
    """Recent changelog entries matching the current user's tracked objects."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        direct_bill_ids = TrackedBill.objects.filter(user=request.user).values_list(
            "bill_id",
            flat=True,
        )
        topic_ids = TrackedTopic.objects.filter(user=request.user).values_list(
            "topic_id",
            flat=True,
        )
        representative_ids = TrackedLegislator.objects.filter(
            user=request.user
        ).values_list(
            "representative_id",
            flat=True,
        )
        try:
            limit = int(request.query_params.get("limit") or 50)
        except ValueError:
            limit = 50
        limit = max(1, min(limit, 100))

        entries = (
            ChangeLog.objects.filter(
                Q(bill_id__in=direct_bill_ids)
                | Q(bill__bill_topics__topic_id__in=topic_ids)
                | Q(bill__sponsor_id__in=representative_ids)
            )
            .select_related("bill", "bill__sponsor")
            .order_by("-created_at")
            .distinct()[:limit]
        )
        return Response(
            {"entries": TrackingFeedEntrySerializer(entries, many=True).data}
        )


class TrackedBillView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        bill_id, error_response = parse_required_int_param(
            request.data.get("bill"),
            "bill",
        )
        if error_response is not None:
            return error_response
        bill = get_object_or_404(Bill, pk=bill_id)
        tracked, created = TrackedBill.objects.get_or_create(
            user=request.user,
            bill=bill,
        )
        return Response(
            TrackedBillSerializer(tracked).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class TrackedBillDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request: Request, bill_id: int) -> Response:
        TrackedBill.objects.filter(user=request.user, bill_id=bill_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TrackedTopicView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        tracked_topics = (
            TrackedTopic.objects.filter(user=request.user)
            .select_related("topic")
            .order_by("-created_at", "-id")
        )
        return Response(TrackedTopicSerializer(tracked_topics, many=True).data)

    def post(self, request: Request) -> Response:
        topic_id, error_response = parse_required_int_param(
            request.data.get("topic"),
            "topic",
        )
        if error_response is not None:
            return error_response
        topic = get_object_or_404(Topic, pk=topic_id)
        tracked, created = TrackedTopic.objects.get_or_create(
            user=request.user,
            topic=topic,
        )
        return Response(
            TrackedTopicSerializer(tracked).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class TrackedTopicDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request: Request, topic_id: int) -> Response:
        TrackedTopic.objects.filter(user=request.user, topic_id=topic_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TrackedLegislatorView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        representative_id, error_response = parse_required_int_param(
            request.data.get("representative"),
            "representative",
        )
        if error_response is not None:
            return error_response
        representative = get_object_or_404(Representative, pk=representative_id)
        tracked, created = TrackedLegislator.objects.get_or_create(
            user=request.user,
            representative=representative,
        )
        return Response(
            TrackedLegislatorSerializer(tracked).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class TrackedLegislatorDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request: Request, representative_id: int) -> Response:
        TrackedLegislator.objects.filter(
            user=request.user,
            representative_id=representative_id,
        ).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
