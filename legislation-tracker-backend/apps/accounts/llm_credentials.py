"""Context-bound encryption and fail-closed configuration for user LLM keys."""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class CredentialConfigurationError(RuntimeError):
    pass


class CredentialDecryptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class EncryptionKeyRing:
    active_key_id: str
    keys: dict[str, Fernet]


def parse_encryption_key_ring(raw_value: str | None = None) -> dict[str, Fernet]:
    raw = settings.LLM_CREDENTIAL_ENCRYPTION_KEYS if raw_value is None else raw_value
    keys: dict[str, Fernet] = {}
    if not raw:
        return keys
    for entry in raw.split(","):
        if ":" not in entry:
            raise CredentialConfigurationError(
                "Malformed credential encryption key entry"
            )
        key_id, encoded_key = (part.strip() for part in entry.split(":", 1))
        if not key_id or not encoded_key or key_id in keys:
            raise CredentialConfigurationError(
                "Invalid or duplicate credential encryption key id"
            )
        try:
            keys[key_id] = Fernet(encoded_key.encode("ascii"))
        except (TypeError, ValueError) as exc:
            raise CredentialConfigurationError(
                "Malformed Fernet credential encryption key"
            ) from exc
    return keys


def _configured_key_ring() -> EncryptionKeyRing:
    keys = parse_encryption_key_ring()
    active_key_id = settings.LLM_CREDENTIAL_ACTIVE_KEY_ID
    if not active_key_id or active_key_id not in keys:
        raise CredentialConfigurationError(
            "Unknown active credential encryption key id"
        )
    return EncryptionKeyRing(active_key_id=active_key_id, keys=keys)


def encrypt_credential(
    *, user_id, provider: str, revision: int, api_key: str
) -> tuple[str, str]:
    ring = _configured_key_ring()
    envelope = {
        "version": 1,
        "user_id": str(user_id),
        "provider": provider,
        "revision": revision,
        "api_key": api_key,
    }
    payload = json.dumps(
        envelope,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    ciphertext = ring.keys[ring.active_key_id].encrypt(payload).decode("ascii")
    return ciphertext, ring.active_key_id


def decrypt_credential(credential) -> str:
    try:
        keys = parse_encryption_key_ring()
    except CredentialConfigurationError as exc:
        raise CredentialDecryptionError(
            "Could not configure credential decryption"
        ) from exc
    fernet = keys.get(credential.encryption_key_id)
    if fernet is None:
        raise CredentialDecryptionError("Credential encryption key id is unavailable")
    try:
        payload = fernet.decrypt(credential.encrypted_envelope.encode("ascii"))
        envelope = json.loads(payload.decode("utf-8"))
    except (InvalidToken, UnicodeDecodeError, ValueError, TypeError) as exc:
        raise CredentialDecryptionError("Could not decrypt credential") from exc

    expected_context = {
        "version": 1,
        "user_id": str(credential.user_id),
        "provider": credential.provider,
        "revision": credential.revision,
    }
    if any(envelope.get(key) != value for key, value in expected_context.items()):
        raise CredentialDecryptionError("Credential encryption context does not match")
    api_key = envelope.get("api_key")
    if not isinstance(api_key, str) or not api_key:
        raise CredentialDecryptionError("Credential payload is invalid")
    if not hmac.compare_digest(api_key[-4:], credential.key_suffix):
        raise CredentialDecryptionError("Credential suffix does not match")
    return api_key


def llm_feature_configuration_errors(*, production: bool) -> list[str]:
    if not getattr(settings, "LLM_ENHANCEMENTS_ENABLED", False):
        return []

    errors: list[str] = []
    try:
        keys = parse_encryption_key_ring()
    except CredentialConfigurationError:
        keys = {}
        errors.append("malformed_encryption_keys")
    if not keys:
        errors.append("missing_encryption_keys")
    if getattr(settings, "LLM_CREDENTIAL_ACTIVE_KEY_ID", "") not in keys:
        errors.append("unknown_active_encryption_key")

    provider = getattr(settings, "LLM_ENHANCEMENT_PROVIDER", "")
    if not provider:
        errors.append("missing_provider")
    else:
        from apps.legislation.enhancements.provider_registry import (
            provider_is_registered,
        )

        if not provider_is_registered(provider):
            errors.append("unregistered_provider")
    if not getattr(settings, "LLM_ENHANCEMENT_MODEL", ""):
        errors.append("missing_model")
    if getattr(settings, "LLM_ENHANCEMENT_REASONING_EFFORT", "") not in {
        "none",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    }:
        errors.append("invalid_reasoning_effort")
    for name in (
        "LLM_ENHANCEMENT_MAX_REQUEST_BYTES",
        "LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS",
        "LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS",
        "LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS",
        "LLM_ENHANCEMENT_RUN_LEASE_SECONDS",
    ):
        if getattr(settings, name, 0) <= 0:
            errors.append(f"invalid_{name.lower()}")
    if getattr(settings, "LLM_ENHANCEMENT_RUN_LEASE_SECONDS", 0) <= getattr(
        settings, "LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS", 0
    ):
        errors.append("run_lease_not_longer_than_timeout")

    if production:
        if not getattr(settings, "SECURE_SSL_REDIRECT", False):
            errors.append("secure_ssl_redirect_required")
        if getattr(settings, "SECURE_HSTS_SECONDS", 0) <= 0:
            errors.append("hsts_required")
        if not (
            getattr(settings, "SESSION_COOKIE_SECURE", False)
            and getattr(settings, "CSRF_COOKIE_SECURE", False)
        ):
            errors.append("secure_cookies_required")
        if not getattr(settings, "LLM_ENHANCEMENT_PRODUCTION_TLS_CONFIRMED", False):
            errors.append("production_tls_confirmation_required")
        if not getattr(
            settings,
            "LLM_ENHANCEMENT_SECRET_LOG_REDACTION_CONFIRMED",
            False,
        ):
            errors.append("secret_log_redaction_confirmation_required")
    elif getattr(settings, "DEBUG", False) and not getattr(
        settings,
        "LLM_ENHANCEMENT_ALLOW_INSECURE_HTTP_IN_DEBUG",
        False,
    ):
        errors.append("debug_http_not_confirmed")
    return errors


def llm_feature_available() -> bool:
    return bool(
        getattr(settings, "LLM_ENHANCEMENTS_ENABLED", False)
        and not llm_feature_configuration_errors(
            production=getattr(
                settings,
                "LLM_ENHANCEMENT_PRODUCTION_SECURITY_REQUIRED",
                False,
            )
        )
    )
