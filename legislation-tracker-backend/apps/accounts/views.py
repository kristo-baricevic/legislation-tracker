"""
Auth API: register, JWT token (handled by Simple JWT).
User preferences: follow/unfollow topics.
"""
from django.contrib.auth import get_user_model
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.legislation.models import Topic

from .models import UserPreference
from .serializers import UserPreferenceSerializer

User = get_user_model()


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
    """CRUD for the current user's preferences (followed topics, state, chamber)."""

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

    @action(detail=False, methods=["get"], url_path="followed-topics")
    def followed_topics(self, request):
        """List topic IDs the current user follows."""
        topic_ids = list(
            UserPreference.objects.filter(
                user=request.user, topic__isnull=False
            ).values_list("topic_id", flat=True)
        )
        return Response({"topic_ids": topic_ids})

    @action(detail=False, methods=["post"], url_path="follow-topic")
    def follow_topic(self, request):
        """Follow a topic. Body: { "topic_id": 5 }"""
        topic_id = request.data.get("topic_id")
        if not topic_id:
            return Response(
                {"error": "topic_id required"}, status=status.HTTP_400_BAD_REQUEST
            )
        if not Topic.objects.filter(pk=topic_id).exists():
            return Response(
                {"error": "Topic not found"}, status=status.HTTP_404_NOT_FOUND
            )
        _, created = UserPreference.objects.get_or_create(
            user=request.user, topic_id=topic_id
        )
        if created:
            return Response({"followed": True, "topic_id": topic_id}, status=status.HTTP_201_CREATED)
        return Response({"followed": True, "topic_id": topic_id, "already": True})

    @action(detail=False, methods=["post"], url_path="unfollow-topic")
    def unfollow_topic(self, request):
        """Unfollow a topic. Body: { "topic_id": 5 }"""
        topic_id = request.data.get("topic_id")
        if not topic_id:
            return Response(
                {"error": "topic_id required"}, status=status.HTTP_400_BAD_REQUEST
            )
        deleted, _ = UserPreference.objects.filter(
            user=request.user, topic_id=topic_id
        ).delete()
        return Response({"unfollowed": True, "topic_id": topic_id, "deleted": deleted > 0})
