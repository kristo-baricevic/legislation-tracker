import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.accounts.llm_credentials import decrypt_credential
from apps.accounts.models import LLMCredential

from .test_llm_credentials import FERNET_KEY, SECOND_FERNET_KEY


@pytest.mark.django_db
def test_rotation_requires_execute_and_preserves_revision_and_validation(capsys):
    user = get_user_model().objects.create_user(
        username="rotation@example.com",
        email="rotation@example.com",
        password="password123",
    )
    with override_settings(
        LLM_CREDENTIAL_ENCRYPTION_KEYS=f"old:{FERNET_KEY}",
        LLM_CREDENTIAL_ACTIVE_KEY_ID="old",
    ):
        credential = LLMCredential.objects.create_for_key(
            user=user,
            provider="openai",
            api_key="sk-test-rotation-secret",
        )
        credential.validation_status = LLMCredential.ValidationStatus.VALID
        credential.validated_revision = 1
        credential.validated_provider = "openai"
        credential.validated_model = "gpt-5.6-luna"
        credential.save()

    key_ring = f"new:{SECOND_FERNET_KEY},old:{FERNET_KEY}"
    with override_settings(
        LLM_CREDENTIAL_ENCRYPTION_KEYS=key_ring,
        LLM_CREDENTIAL_ACTIVE_KEY_ID="new",
    ):
        with pytest.raises(CommandError, match="--execute"):
            call_command("rotate_llm_credentials")
        call_command("rotate_llm_credentials", execute=True, batch_size=1)

    credential.refresh_from_db()
    assert credential.encryption_key_id == "new"
    assert credential.revision == 1
    assert credential.validation_status == LLMCredential.ValidationStatus.VALID

    with override_settings(
        LLM_CREDENTIAL_ENCRYPTION_KEYS=f"new:{SECOND_FERNET_KEY}",
        LLM_CREDENTIAL_ACTIVE_KEY_ID="new",
    ):
        assert decrypt_credential(credential) == "sk-test-rotation-secret"

    assert "sk-test-rotation-secret" not in capsys.readouterr().out
