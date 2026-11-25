import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.accounts.models import TrackedLegislator
from apps.congress.models import Representative

pytestmark = pytest.mark.django_db


def test_tracking_filter_is_user_scoped_and_applied_before_pagination():
    user = get_user_model().objects.create_user(
        username="reader", email="reader@example.test"
    )
    other = get_user_model().objects.create_user(
        username="other", email="other@example.test"
    )
    reps = [
        Representative.objects.create(
            bioguide_id=f"T{i:06d}",
            name=f"Member {i}",
            state="NY",
            chamber="house",
            party="D",
            is_current=True,
        )
        for i in range(4)
    ]
    TrackedLegislator.objects.create(user=user, representative=reps[2])
    TrackedLegislator.objects.create(user=other, representative=reps[0])
    from rest_framework_simplejwt.tokens import AccessToken

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")
    response = client.get("/api/representatives/?tracking=tracked&page_size=1&state=NY")
    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["id"] == reps[2].pk
    assert "private" in response["Cache-Control"]
    response = client.get("/api/representatives/?tracking=untracked&page_size=1")
    assert response.data["count"] == 3
    assert response.data["results"][0]["id"] == reps[0].pk
    assert response.data["next"] is not None


@pytest.mark.parametrize("tracking", ["tracked", "untracked"])
def test_personal_tracking_filter_requires_login(tracking):
    response = APIClient().get(f"/api/representatives/?tracking={tracking}")
    assert response.status_code in (401, 403)


def test_public_directory_still_ignores_invalid_credentials():
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer expired")
    assert client.get("/api/representatives/").status_code == 200
