import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.accounts.llm_credentials import CredentialDecryptionError, decrypt_credential
from apps.accounts.models import LLMCredential

FERNET_KEY = "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE="
SECOND_FERNET_KEY = "YmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmI="


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        username="owner@example.com",
        email="owner@example.com",
        password="password123",
    )


@pytest.fixture
def encryption_settings():
    return override_settings(
        LLM_CREDENTIAL_ENCRYPTION_KEYS=f"primary:{FERNET_KEY},old:{SECOND_FERNET_KEY}",
        LLM_CREDENTIAL_ACTIVE_KEY_ID="primary",
    )


@pytest.mark.django_db
def test_create_and_replace_key_increments_revision_and_resets_validation(
    user,
    encryption_settings,
):
    with encryption_settings:
        credential = LLMCredential.objects.create_for_key(
            user=user,
            provider="openai",
            api_key="sk-test-first",
        )
        credential.validation_status = LLMCredential.ValidationStatus.VALID
        credential.validated_revision = credential.revision
        credential.validated_provider = credential.provider
        credential.validated_model = "gpt-5.6-luna"
        credential.save()

        credential.replace_key("sk-test-second")

        assert credential.revision == 2
        assert credential.validation_status == LLMCredential.ValidationStatus.UNVERIFIED
        assert credential.validated_revision is None
        assert credential.validated_provider == ""
        assert credential.validated_model == ""
        assert credential.key_suffix == "cond"
        assert decrypt_credential(credential) == "sk-test-second"


@pytest.mark.django_db
def test_contextual_envelope_rejects_ciphertext_copied_to_another_user(
    user,
    encryption_settings,
):
    other = get_user_model().objects.create_user(
        username="other@example.com",
        email="other@example.com",
        password="password123",
    )
    with encryption_settings:
        original = LLMCredential.objects.create_for_key(
            user=user,
            provider="openai",
            api_key="sk-test-secret",
        )
        copied = LLMCredential.objects.create(
            user=other,
            provider=original.provider,
            encrypted_envelope=original.encrypted_envelope,
            key_suffix=original.key_suffix,
            encryption_key_id=original.encryption_key_id,
            revision=original.revision,
        )

        with pytest.raises(CredentialDecryptionError, match="context"):
            decrypt_credential(copied)


@pytest.mark.django_db
def test_contextual_envelope_rejects_tampering_and_suffix_mismatch(
    user,
    encryption_settings,
):
    with encryption_settings:
        credential = LLMCredential.objects.create_for_key(
            user=user,
            provider="openai",
            api_key="sk-test-secret",
        )
        credential.key_suffix = "xxxx"
        credential.save(update_fields=["key_suffix"])
        with pytest.raises(CredentialDecryptionError, match="suffix"):
            decrypt_credential(credential)

        credential.key_suffix = "cret"
        credential.encrypted_envelope = credential.encrypted_envelope[:-1] + "A"
        credential.save(update_fields=["key_suffix", "encrypted_envelope"])
        with pytest.raises(CredentialDecryptionError, match="decrypt"):
            decrypt_credential(credential)


@pytest.mark.django_db
def test_decryption_uses_row_key_id_and_fails_when_key_was_removed(
    user,
    encryption_settings,
):
    with encryption_settings:
        credential = LLMCredential.objects.create_for_key(
            user=user,
            provider="openai",
            api_key="sk-test-secret",
        )

    with override_settings(
        LLM_CREDENTIAL_ENCRYPTION_KEYS=f"old:{SECOND_FERNET_KEY}",
        LLM_CREDENTIAL_ACTIVE_KEY_ID="old",
    ), pytest.raises(CredentialDecryptionError, match="key id"):
        decrypt_credential(credential)
