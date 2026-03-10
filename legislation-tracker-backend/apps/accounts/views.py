"""
Auth API: register, JWT token (handled by Simple JWT).
"""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

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
        # username required by AbstractUser; use email for consistency
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
        )
        return Response(
            {"id": user.pk, "email": user.email},
            status=status.HTTP_201_CREATED,
        )
