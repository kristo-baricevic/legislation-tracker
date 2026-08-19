"""
Auth API, user preferences, and private tracking APIs.
"""
from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.changelog.models import ChangeLog
from apps.congress.models import Representative
from apps.legislation.models import Bill, Topic

from .models import TrackedBill, TrackedLegislator, TrackedTopic, UserPreference
from .serializers import (
    TrackingFeedEntrySerializer,
    TrackedBillSerializer,
    TrackedLegislatorSerializer,
    TrackedTopicSerializer,
    UserPreferenceSerializer,
)

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
    """POST email, password -> create user. No auth required."""

    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        email = request.data.get("email")
        password = request.data.get("password")
        if not email or not password:
            return Response(
                {"error": "email and password required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        email = email.strip().lower()
        if User.objects.filter(email=email).exists():
            return Response(
                {"error": "A user with this email already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(password) < 8:
            return Response(
                {"error": "Password must be at least 8 characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
        )
        return Response(
            {"id": user.pk, "email": user.email},
            status=status.HTTP_201_CREATED,
        )


class UserPreferenceViewSet(viewsets.ModelViewSet):
    """CRUD for the current user's preferences."""

    permission_classes = [IsAuthenticated]
    serializer_class = UserPreferenceSerializer

    def get_queryset(self):
        return (
            UserPreference.objects.filter(user=self.request.user)
            .select_related("topic")
            .order_by("id")
        )

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

    @action(detail=False, methods=["get"], url_path="followed-topics")
    def followed_topics(self, request):
        """List topic IDs the current user follows."""
        topic_ids = list(
            TrackedTopic.objects.filter(
                user=request.user,
            ).values_list("topic_id", flat=True)
        )
        return Response({"topic_ids": topic_ids})

    @action(detail=False, methods=["post"], url_path="follow-topic")
    def follow_topic(self, request):
        """Follow a topic. Body: { "topic_id": 5 }"""
        topic_id, error_response = parse_required_int_param(
            request.data.get("topic_id"),
            "topic_id",
        )
        if error_response is not None:
            return error_response
        get_object_or_404(Topic, pk=topic_id)
        _, created = TrackedTopic.objects.get_or_create(
            user=request.user,
            topic_id=topic_id,
        )
        return Response(
            {"followed": True, "topic_id": topic_id, "already": not created},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="unfollow-topic")
    def unfollow_topic(self, request):
        """Unfollow a topic. Body: { "topic_id": 5 }"""
        topic_id, error_response = parse_required_int_param(
            request.data.get("topic_id"),
            "topic_id",
        )
        if error_response is not None:
            return error_response
        deleted, _ = TrackedTopic.objects.filter(
            user=request.user,
            topic_id=topic_id,
        ).delete()
        return Response(
            {"unfollowed": True, "topic_id": topic_id, "deleted": deleted > 0}
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
        legislators = TrackedLegislator.objects.filter(user=request.user).select_related(
            "representative"
        )
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
