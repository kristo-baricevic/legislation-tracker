import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.llm_credentials import decrypt_credential
from apps.accounts.models import LLMCredential
from apps.legislation.enhancements.providers.base import CredentialCheck, ProviderError

from .test_llm_credentials import FERNET_KEY


@pytest.fixture(autouse=True)
def clear_throttle_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def llm_settings():
    return override_settings(
        LLM_ENHANCEMENTS_ENABLED=True,
        LLM_CREDENTIAL_ENCRYPTION_KEYS=f"primary:{FERNET_KEY}",
        LLM_CREDENTIAL_ACTIVE_KEY_ID="primary",
        LLM_ENHANCEMENT_PROVIDER="openai",
        LLM_ENHANCEMENT_MODEL="gpt-5.6-luna",
        LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS=90,
        LLM_ENHANCEMENT_ALLOW_INSECURE_HTTP_IN_DEBUG=True,
    )


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        username="settings@example.com",
        email="settings@example.com",
        password="password123",
    )


@pytest.fixture
def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def _assert_private(response):
    assert response["Cache-Control"] == "private, no-store"


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["get", "put", "post", "delete"])
def test_settings_endpoints_require_authentication(method, llm_settings):
    client = APIClient()
    path = "/api/settings/llm/validate/" if method == "post" else "/api/settings/llm/"

    response = getattr(client, method)(path, {}, format="json")

    assert response.status_code == 401
    _assert_private(response)


@pytest.mark.django_db
def test_get_unconfigured_settings_is_redacted_and_does_not_call_provider(
    authenticated_client,
    llm_settings,
):
    with llm_settings:
        response = authenticated_client.get("/api/settings/llm/")

    assert response.status_code == 200
    assert response.json() == {
        "feature_available": True,
        "configured": False,
        "provider": "openai",
        "key_suffix": None,
        "revision": None,
        "enabled": False,
        "validation_status": "unverified",
        "validated_revision": None,
        "validated_at": None,
        "requested_model": "gpt-5.6-luna",
    }
    _assert_private(response)


@pytest.mark.django_db
def test_put_saves_and_replaces_key_without_echoing_it(
    authenticated_client,
    user,
    llm_settings,
):
    with llm_settings:
        created = authenticated_client.put(
            "/api/settings/llm/",
            {"api_key": "sk-test-first", "enabled": True},
            format="json",
        )
        replaced = authenticated_client.put(
            "/api/settings/llm/",
            {"api_key": "sk-test-second"},
            format="json",
        )
        credential = LLMCredential.objects.get(user=user)

        assert decrypt_credential(credential) == "sk-test-second"

    assert created.status_code == 200
    assert created.json()["key_suffix"] == "irst"
    assert replaced.status_code == 200
    assert replaced.json()["revision"] == 2
    assert replaced.json()["validation_status"] == "unverified"
    assert "api_key" not in created.json()
    assert "encrypted_envelope" not in created.json()
    assert "sk-test" not in str(created.content)
    _assert_private(created)


@pytest.mark.django_db
def test_disabled_deployment_allows_inspection_disable_and_delete_but_not_key_write(
    authenticated_client,
    user,
):
    enabled = override_settings(
        LLM_ENHANCEMENTS_ENABLED=True,
        LLM_CREDENTIAL_ENCRYPTION_KEYS=f"primary:{FERNET_KEY}",
        LLM_CREDENTIAL_ACTIVE_KEY_ID="primary",
    )
    with enabled:
        LLMCredential.objects.create_for_key(
            user=user,
            provider="openai",
            api_key="sk-test-existing",
        )

    with override_settings(LLM_ENHANCEMENTS_ENABLED=False):
        read = authenticated_client.get("/api/settings/llm/")
        rejected = authenticated_client.put(
            "/api/settings/llm/",
            {"api_key": "sk-test-new"},
            format="json",
        )
        disabled = authenticated_client.put(
            "/api/settings/llm/",
            {"enabled": False},
            format="json",
        )
        deleted = authenticated_client.delete("/api/settings/llm/")

    assert read.status_code == 200
    assert read.json()["feature_available"] is False
    assert rejected.status_code == 503
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert deleted.status_code == 204
    assert not LLMCredential.objects.filter(user=user).exists()
    for response in (read, rejected, disabled, deleted):
        _assert_private(response)


@pytest.mark.django_db
def test_unsafe_runtime_configuration_cannot_accept_a_key(
    authenticated_client,
    user,
):
    with override_settings(
        DEBUG=True,
        LLM_ENHANCEMENTS_ENABLED=True,
        LLM_CREDENTIAL_ENCRYPTION_KEYS=f"primary:{FERNET_KEY}",
        LLM_CREDENTIAL_ACTIVE_KEY_ID="primary",
        LLM_ENHANCEMENT_PROVIDER="openai",
        LLM_ENHANCEMENT_MODEL="gpt-5.6-luna",
        LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS=90,
        LLM_ENHANCEMENT_RUN_LEASE_SECONDS=180,
        LLM_ENHANCEMENT_ALLOW_INSECURE_HTTP_IN_DEBUG=False,
    ):
        read = authenticated_client.get("/api/settings/llm/")
        write = authenticated_client.put(
            "/api/settings/llm/",
            {"api_key": "sk-test-must-not-be-stored"},
            format="json",
        )

    assert read.json()["feature_available"] is False
    assert write.status_code == 503
    assert not LLMCredential.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_validation_updates_only_the_snapshotted_credential_revision(
    authenticated_client,
    user,
    llm_settings,
    monkeypatch,
):
    class ReplacingProvider:
        def validate_credential(self, **kwargs):
            LLMCredential.objects.get(user=user).replace_key("sk-test-replacement")
            return CredentialCheck(valid=True)

    with llm_settings:
        LLMCredential.objects.create_for_key(
            user=user,
            provider="openai",
            api_key="sk-test-original",
        )
        monkeypatch.setattr(
            "apps.accounts.llm_views.get_provider",
            lambda name: ReplacingProvider(),
        )

        response = authenticated_client.post("/api/settings/llm/validate/")
        credential = LLMCredential.objects.get(user=user)

    assert response.status_code == 409
    assert response.json()["error"] == "credential_changed"
    assert credential.revision == 2
    assert credential.validation_status == LLMCredential.ValidationStatus.UNVERIFIED
    _assert_private(response)


@pytest.mark.django_db
def test_validation_records_sanitized_success_and_provider_failure(
    authenticated_client,
    user,
    llm_settings,
    monkeypatch,
):
    calls = []

    class SuccessfulProvider:
        def validate_credential(self, **kwargs):
            calls.append(kwargs)
            return CredentialCheck(valid=True)

    with llm_settings:
        LLMCredential.objects.create_for_key(
            user=user,
            provider="openai",
            api_key="sk-test-secret",
        )
        monkeypatch.setattr(
            "apps.accounts.llm_views.get_provider",
            lambda name: SuccessfulProvider(),
        )
        success = authenticated_client.post("/api/settings/llm/validate/")

        assert len(calls) == 1
        assert calls[0]["api_key"] == "sk-test-secret"
        assert success.status_code == 200
        assert success.json()["validation_status"] == "valid"

        class FailingProvider:
            def validate_credential(self, **kwargs):
                raise ProviderError("provider_unavailable", retry_allowed=True)

        monkeypatch.setattr(
            "apps.accounts.llm_views.get_provider",
            lambda name: FailingProvider(),
        )
        failure = authenticated_client.post("/api/settings/llm/validate/")

    assert failure.status_code == 503
    assert failure.json() == {
        "validation_status": "unverified",
        "error": "provider_unavailable",
    }
    assert "sk-test-secret" not in str(failure.content)
    _assert_private(success)
    _assert_private(failure)


@pytest.mark.django_db
def test_users_cannot_read_or_mutate_another_users_credential(
    authenticated_client,
    llm_settings,
):
    other = get_user_model().objects.create_user(
        username="other-settings@example.com",
        email="other-settings@example.com",
        password="password123",
    )
    with llm_settings:
        LLMCredential.objects.create_for_key(
            user=other,
            provider="openai",
            api_key="sk-test-other",
        )
        response = authenticated_client.get("/api/settings/llm/")

    assert response.status_code == 200
    assert response.json()["configured"] is False
