from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.throttles import LoginThrottle, RefreshThrottle, RegistrationThrottle

GENERIC_REGISTRATION_RESPONSE = {
    "detail": "If the address can be registered, the account is ready to sign in."
}


@pytest.fixture(autouse=True)
def isolated_auth_throttle_cache():
    with override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "auth-api-tests",
            }
        }
    ):
        cache.clear()
        yield
        cache.clear()


def create_user(email="user@example.com", password="correct-horse-battery-staple"):
    return get_user_model().objects.create_user(
        username=email,
        email=email,
        password=password,
    )


def bootstrap_csrf(client):
    response = client.get("/api/auth/csrf/")
    assert response.status_code == 200
    assert response.json()["csrf_token"]
    return client.cookies["csrftoken"].value


def login_session(
    client, email="user@example.com", password="correct-horse-battery-staple"
):
    return client.post(
        "/api/auth/session/",
        {"email": email, "password": password},
        format="json",
        HTTP_X_CSRFTOKEN=bootstrap_csrf(client),
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("payload", "field"),
    [
        (
            {"email": "not-an-email", "password": "correct-horse-battery-staple"},
            "email",
        ),
        (
            {
                "email": f"{'a' * 140}@example.com",
                "password": "correct-horse-battery-staple",
            },
            "email",
        ),
        ({"email": "person@example.com", "password": "x" * 129}, "password"),
        ({"email": "person@example.com", "password": "password"}, "password"),
        (
            {"email": "person@example.com", "password": "1234567890123456"},
            "password",
        ),
    ],
)
def test_register_rejects_malformed_oversized_and_weak_values(payload, field):
    response = APIClient().post("/api/auth/register/", payload, format="json")

    assert response.status_code == 400
    assert field in response.json()
    assert get_user_model().objects.count() == 0


@pytest.mark.django_db
def test_register_normalizes_email_and_returns_the_same_response_for_duplicates():
    client = APIClient()
    payload = {
        "email": " PERSON@Example.COM ",
        "password": "correct-horse-battery-staple",
    }

    created = client.post("/api/auth/register/", payload, format="json")
    duplicate = client.post("/api/auth/register/", payload, format="json")

    assert created.status_code == duplicate.status_code == 202
    assert created.json() == duplicate.json() == GENERIC_REGISTRATION_RESPONSE
    assert (
        get_user_model().objects.values_list("email", flat=True).get()
        == "person@example.com"
    )


@pytest.mark.django_db
def test_register_treats_a_database_uniqueness_race_as_a_generic_duplicate():
    with patch.object(
        get_user_model().objects,
        "create_user",
        side_effect=IntegrityError("concurrent unique constraint"),
    ):
        response = APIClient().post(
            "/api/auth/register/",
            {
                "email": "person@example.com",
                "password": "correct-horse-battery-staple",
            },
            format="json",
        )

    assert response.status_code == 202
    assert response.json() == GENERIC_REGISTRATION_RESPONSE


@pytest.mark.django_db
@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "auth-throttle-tests",
        }
    },
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "apps.accounts.authentication.CookieJWTAuthentication",
            "rest_framework_simplejwt.authentication.JWTAuthentication",
        ],
        "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
        "DEFAULT_THROTTLE_RATES": {
            "auth_register": "1/minute",
            "auth_login": "1/minute",
            "auth_refresh": "1/minute",
        },
    },
)
def test_registration_login_and_refresh_have_separate_anonymous_throttle_scopes(
    monkeypatch,
):
    cache.clear()
    monkeypatch.setattr(RegistrationThrottle, "rate", "1/minute", raising=False)
    monkeypatch.setattr(LoginThrottle, "rate", "1/minute", raising=False)
    monkeypatch.setattr(RefreshThrottle, "rate", "1/minute", raising=False)
    create_user()
    client = APIClient()

    first_registration = client.post(
        "/api/auth/register/",
        {"email": "new@example.com", "password": "another-secure-password"},
        format="json",
        HTTP_X_CSRFTOKEN=bootstrap_csrf(client),
    )
    throttled_registration = client.post(
        "/api/auth/register/",
        {"email": "other@example.com", "password": "another-secure-password"},
        format="json",
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )
    first_login = login_session(client)
    throttled_login = APIClient().post(
        "/api/auth/token/",
        {"email": "user@example.com", "password": "wrong-password"},
        format="json",
        REMOTE_ADDR="127.0.0.1",
    )

    assert first_registration.status_code == 202
    assert throttled_registration.status_code == 429
    assert first_login.status_code == 200
    assert throttled_login.status_code == 429
    assert first_login.status_code != throttled_registration.status_code


@pytest.mark.django_db
@override_settings(AUTH_COOKIE_SECURE=True)
def test_session_login_issues_httponly_tokens_and_a_readable_csrf_cookie():
    create_user()
    client = APIClient(enforce_csrf_checks=True)
    response = login_session(
        client,
        email=" USER@example.com ",
    )

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": True,
        "user": {"email": "user@example.com"},
    }
    assert "access" not in response.json()
    assert "refresh" not in response.json()
    assert response.cookies["auth_access"]["httponly"] is True
    assert response.cookies["auth_access"]["secure"] is True
    assert response.cookies["auth_access"]["samesite"] == "Lax"
    assert response.cookies["auth_refresh"]["httponly"] is True
    assert response.cookies["auth_refresh"]["secure"] is True
    assert response.cookies["csrftoken"]["httponly"] == ""


@pytest.mark.django_db
def test_cookie_authenticated_unsafe_requests_require_csrf():
    create_user()
    client = APIClient(enforce_csrf_checks=True)
    login_response = login_session(client)
    assert login_response.status_code == 200

    rejected = client.post("/api/tracking/topics/", {"topic": 1}, format="json")
    accepted_by_csrf = client.post(
        "/api/tracking/topics/",
        {"topic": "invalid"},
        format="json",
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )

    assert rejected.status_code == 403
    assert accepted_by_csrf.status_code == 400


@pytest.mark.django_db
def test_session_status_uses_the_httponly_access_cookie():
    create_user()
    client = APIClient()
    login_session(client)

    response = client.get("/api/auth/session/current/")

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": True,
        "user": {"email": "user@example.com"},
    }


@pytest.mark.django_db
def test_session_refresh_rotates_and_blacklists_the_previous_refresh_token():
    create_user()
    client = APIClient(enforce_csrf_checks=True)
    login_response = login_session(client)
    old_refresh = login_response.cookies["auth_refresh"].value

    response = client.post(
        "/api/auth/session/refresh/",
        format="json",
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )

    new_refresh = response.cookies["auth_refresh"].value
    assert response.status_code == 200
    assert response.json() == {"authenticated": True}
    assert new_refresh != old_refresh
    old_jti = RefreshToken(old_refresh, verify=False)["jti"]
    assert BlacklistedToken.objects.filter(token__jti=old_jti).exists()


@pytest.mark.django_db
def test_session_refresh_rejects_a_missing_or_blacklisted_cookie_without_a_500():
    create_user()
    client = APIClient(enforce_csrf_checks=True)
    csrf_token = bootstrap_csrf(client)

    missing = client.post(
        "/api/auth/session/refresh/",
        format="json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    login_response = login_session(client)
    refresh = RefreshToken(login_response.cookies["auth_refresh"].value)
    refresh.blacklist()
    blacklisted = client.post(
        "/api/auth/session/refresh/",
        format="json",
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )

    assert missing.status_code == 401
    assert blacklisted.status_code == 401
    assert blacklisted.json() == {"detail": "The refresh session is invalid."}
    assert "auth_access" not in missing.cookies
    assert "auth_refresh" not in missing.cookies
    assert "auth_access" not in blacklisted.cookies
    assert "auth_refresh" not in blacklisted.cookies


@pytest.mark.django_db
def test_session_logout_revokes_refresh_and_clears_auth_cookies():
    create_user()
    client = APIClient(enforce_csrf_checks=True)
    login_response = login_session(client)
    refresh = login_response.cookies["auth_refresh"].value

    response = client.post(
        "/api/auth/session/logout/",
        format="json",
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )

    assert response.status_code == 204
    assert response.cookies["auth_access"]["max-age"] == 0
    assert response.cookies["auth_refresh"]["max-age"] == 0
    refresh_jti = RefreshToken(refresh, verify=False)["jti"]
    assert BlacklistedToken.objects.filter(token__jti=refresh_jti).exists()


@pytest.mark.django_db
def test_extension_bearer_token_endpoints_and_authentication_remain_available():
    create_user()
    client = APIClient()
    token_response = client.post(
        "/api/auth/token/",
        {"email": "user@example.com", "password": "correct-horse-battery-staple"},
        format="json",
    )

    assert token_response.status_code == 200
    assert set(token_response.json()) == {"access", "refresh"}

    bearer_response = client.get(
        "/api/tracking/",
        HTTP_AUTHORIZATION=f"Bearer {token_response.json()['access']}",
    )
    refresh_response = client.post(
        "/api/auth/token/refresh/",
        {"refresh": token_response.json()["refresh"]},
        format="json",
    )

    assert bearer_response.status_code == 200
    assert refresh_response.status_code == 200
    assert "access" in refresh_response.json()


@pytest.mark.django_db
def test_session_login_and_registration_require_csrf_after_bootstrap():
    create_user()
    client = APIClient(enforce_csrf_checks=True)

    rejected_login = client.post(
        "/api/auth/session/",
        {"email": "user@example.com", "password": "correct-horse-battery-staple"},
        format="json",
    )
    rejected_registration = client.post(
        "/api/auth/register/",
        {"email": "new@example.com", "password": "another-secure-password"},
        format="json",
    )
    csrf_token = bootstrap_csrf(client)
    accepted_login = client.post(
        "/api/auth/session/",
        {"email": "user@example.com", "password": "correct-horse-battery-staple"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert rejected_login.status_code == 403
    assert rejected_registration.status_code == 403
    assert accepted_login.status_code == 200
    assert client.cookies["csrftoken"]["httponly"] == ""


def test_auth_security_defaults_match_the_approved_deployment_contract(settings):
    assert settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] == {
        **settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
        "auth_register": "5/hour",
        "auth_login": "10/minute",
        "auth_refresh": "30/hour",
    }
    assert settings.AUTH_COOKIE_SAMESITE == "Lax"
