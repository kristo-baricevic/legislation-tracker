from django.test import override_settings

from apps.accounts.llm_credentials import (
    llm_feature_available,
    llm_feature_configuration_errors,
)
from apps.legislation.enhancements.provider_registry import (
    get_provider,
    provider_is_registered,
)

from .test_llm_credentials import FERNET_KEY


def test_disabled_feature_does_not_require_llm_secrets_or_transport_configuration():
    with override_settings(
        LLM_ENHANCEMENTS_ENABLED=False,
        LLM_CREDENTIAL_ENCRYPTION_KEYS="",
        LLM_CREDENTIAL_ACTIVE_KEY_ID="",
    ):
        assert llm_feature_configuration_errors(production=True) == []


def test_enabled_feature_reports_missing_key_ring_and_invalid_lease():
    with override_settings(
        LLM_ENHANCEMENTS_ENABLED=True,
        LLM_CREDENTIAL_ENCRYPTION_KEYS="",
        LLM_CREDENTIAL_ACTIVE_KEY_ID="missing",
        LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS=90,
        LLM_ENHANCEMENT_RUN_LEASE_SECONDS=60,
        LLM_ENHANCEMENT_PROVIDER="openai",
        LLM_ENHANCEMENT_MODEL="gpt-5.6-luna",
        LLM_ENHANCEMENT_REASONING_EFFORT="none",
    ):
        errors = set(llm_feature_configuration_errors(production=False))

    assert "missing_encryption_keys" in errors
    assert "unknown_active_encryption_key" in errors
    assert "run_lease_not_longer_than_timeout" in errors


def test_enabled_feature_requires_persistence_headroom_after_provider_timeout():
    with override_settings(
        DEBUG=False,
        LLM_ENHANCEMENTS_ENABLED=True,
        LLM_CREDENTIAL_ENCRYPTION_KEYS=f"primary:{FERNET_KEY}",
        LLM_CREDENTIAL_ACTIVE_KEY_ID="primary",
        LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS=90,
        LLM_ENHANCEMENT_RUN_LEASE_SECONDS=91,
        LLM_ENHANCEMENT_PROVIDER="openai",
        LLM_ENHANCEMENT_MODEL="gpt-5.6-luna",
        LLM_ENHANCEMENT_REASONING_EFFORT="none",
    ):
        errors = set(llm_feature_configuration_errors(production=False))

    assert "run_lease_insufficient_headroom" in errors


def test_enabled_feature_rejects_an_unregistered_provider_and_implicit_debug_http():
    with override_settings(
        DEBUG=True,
        LLM_ENHANCEMENTS_ENABLED=True,
        LLM_CREDENTIAL_ENCRYPTION_KEYS=f"primary:{FERNET_KEY}",
        LLM_CREDENTIAL_ACTIVE_KEY_ID="primary",
        LLM_ENHANCEMENT_PROVIDER="unknown",
        LLM_ENHANCEMENT_MODEL="model",
        LLM_ENHANCEMENT_REASONING_EFFORT="none",
        LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS=90,
        LLM_ENHANCEMENT_RUN_LEASE_SECONDS=180,
        LLM_ENHANCEMENT_ALLOW_INSECURE_HTTP_IN_DEBUG=False,
    ):
        errors = set(llm_feature_configuration_errors(production=False))

    assert "unregistered_provider" in errors
    assert "debug_http_not_confirmed" in errors


def test_e2e_fake_provider_requires_an_explicit_nonproduction_gate():
    with override_settings(LLM_ENHANCEMENT_E2E_FAKE_PROVIDER_ENABLED=False):
        assert provider_is_registered("e2e") is False

    with override_settings(LLM_ENHANCEMENT_E2E_FAKE_PROVIDER_ENABLED=True):
        assert provider_is_registered("e2e") is True
        assert get_provider("e2e").provider_name == "e2e"


def test_e2e_fake_provider_is_rejected_by_production_configuration():
    with override_settings(
        LLM_ENHANCEMENTS_ENABLED=True,
        LLM_CREDENTIAL_ENCRYPTION_KEYS=f"primary:{FERNET_KEY}",
        LLM_CREDENTIAL_ACTIVE_KEY_ID="primary",
        LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS=90,
        LLM_ENHANCEMENT_RUN_LEASE_SECONDS=180,
        LLM_ENHANCEMENT_PROVIDER="e2e",
        LLM_ENHANCEMENT_E2E_FAKE_PROVIDER_ENABLED=True,
        LLM_ENHANCEMENT_MODEL="e2e-model",
        LLM_ENHANCEMENT_REASONING_EFFORT="none",
        LLM_ENHANCEMENT_MAX_REQUEST_BYTES=120000,
        LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS=60000,
        LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS=4000,
        SECURE_SSL_REDIRECT=True,
        SECURE_HSTS_SECONDS=31536000,
        SESSION_COOKIE_SECURE=True,
        CSRF_COOKIE_SECURE=True,
        LLM_ENHANCEMENT_PRODUCTION_TLS_CONFIRMED=True,
        LLM_ENHANCEMENT_SECRET_LOG_REDACTION_CONFIRMED=True,
    ):
        errors = set(llm_feature_configuration_errors(production=True))

    assert "e2e_fake_provider_forbidden" in errors


def test_production_feature_requires_secure_transport_and_log_redaction_assertions():
    with override_settings(
        LLM_ENHANCEMENTS_ENABLED=True,
        LLM_CREDENTIAL_ENCRYPTION_KEYS=f"primary:{FERNET_KEY}",
        LLM_CREDENTIAL_ACTIVE_KEY_ID="primary",
        LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS=90,
        LLM_ENHANCEMENT_RUN_LEASE_SECONDS=180,
        LLM_ENHANCEMENT_PROVIDER="openai",
        LLM_ENHANCEMENT_MODEL="gpt-5.6-luna",
        LLM_ENHANCEMENT_REASONING_EFFORT="none",
        SECURE_SSL_REDIRECT=False,
        SECURE_HSTS_SECONDS=0,
        SESSION_COOKIE_SECURE=False,
        CSRF_COOKIE_SECURE=False,
        LLM_ENHANCEMENT_PRODUCTION_TLS_CONFIRMED=False,
        LLM_ENHANCEMENT_SECRET_LOG_REDACTION_CONFIRMED=False,
    ):
        errors = set(llm_feature_configuration_errors(production=True))

    assert "secure_ssl_redirect_required" in errors
    assert "hsts_required" in errors
    assert "secure_cookies_required" in errors
    assert "production_tls_confirmation_required" in errors
    assert "secret_log_redaction_confirmation_required" in errors


def test_complete_production_configuration_is_accepted():
    with override_settings(
        LLM_ENHANCEMENTS_ENABLED=True,
        LLM_CREDENTIAL_ENCRYPTION_KEYS=f"primary:{FERNET_KEY}",
        LLM_CREDENTIAL_ACTIVE_KEY_ID="primary",
        LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS=90,
        LLM_ENHANCEMENT_RUN_LEASE_SECONDS=180,
        LLM_ENHANCEMENT_PROVIDER="openai",
        LLM_ENHANCEMENT_MODEL="gpt-5.6-luna",
        LLM_ENHANCEMENT_REASONING_EFFORT="none",
        LLM_ENHANCEMENT_MAX_REQUEST_BYTES=120000,
        LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS=60000,
        LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS=4000,
        SECURE_SSL_REDIRECT=True,
        SECURE_HSTS_SECONDS=31536000,
        SESSION_COOKIE_SECURE=True,
        CSRF_COOKIE_SECURE=True,
        LLM_ENHANCEMENT_PRODUCTION_TLS_CONFIRMED=True,
        LLM_ENHANCEMENT_SECRET_LOG_REDACTION_CONFIRMED=True,
    ):
        assert llm_feature_configuration_errors(production=True) == []


def test_enabled_feature_rejects_malformed_throttle_rates():
    with override_settings(
        LLM_ENHANCEMENTS_ENABLED=True,
        LLM_CREDENTIAL_ENCRYPTION_KEYS=f"primary:{FERNET_KEY}",
        LLM_CREDENTIAL_ACTIVE_KEY_ID="primary",
        LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS=90,
        LLM_ENHANCEMENT_RUN_LEASE_SECONDS=180,
        LLM_ENHANCEMENT_PROVIDER="openai",
        LLM_ENHANCEMENT_MODEL="gpt-5.6-luna",
        LLM_ENHANCEMENT_REASONING_EFFORT="none",
        LLM_ENHANCEMENT_CREATE_RATE="garbage",
        LLM_ENHANCEMENT_VALIDATION_RATE="10/fortnight",
        LLM_ENHANCEMENT_ALLOW_INSECURE_HTTP_IN_DEBUG=True,
    ):
        errors = set(llm_feature_configuration_errors(production=False))

    assert "invalid_llm_enhancement_create_rate" in errors
    assert "invalid_llm_enhancement_validation_rate" in errors


def test_runtime_availability_fails_closed_for_unsafe_debug_transport():
    with override_settings(
        DEBUG=True,
        LLM_ENHANCEMENTS_ENABLED=True,
        LLM_CREDENTIAL_ENCRYPTION_KEYS=f"primary:{FERNET_KEY}",
        LLM_CREDENTIAL_ACTIVE_KEY_ID="primary",
        LLM_ENHANCEMENT_PROVIDER="openai",
        LLM_ENHANCEMENT_MODEL="gpt-5.6-luna",
        LLM_ENHANCEMENT_REASONING_EFFORT="none",
        LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS=90,
        LLM_ENHANCEMENT_RUN_LEASE_SECONDS=180,
        LLM_ENHANCEMENT_ALLOW_INSECURE_HTTP_IN_DEBUG=False,
    ):
        assert llm_feature_available() is False
