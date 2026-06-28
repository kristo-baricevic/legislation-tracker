import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_register_rejects_duplicate_email_after_normalization():
    get_user_model().objects.create_user(
        username="user@example.com",
        email="user@example.com",
        password="password123",
    )

    response = APIClient().post(
        "/api/auth/register/",
        {"email": " USER@example.com ", "password": "password123"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json() == {"error": "A user with this email already exists."}
