import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import override_settings

from apps.accounts.llm_credentials import decrypt_credential, encrypt_credential

from .test_llm_credentials import FERNET_KEY


@pytest.mark.django_db(transaction=True)
def test_forward_and_single_key_rollback_preserve_envelope_and_selection():
    old = ("accounts", "0009_selected_enhancement_model")
    new = ("accounts", "0010_provider_credentials")
    executor = MigrationExecutor(connection)
    executor.migrate([old])
    try:
        state = executor.loader.project_state([old]).apps
        owner = state.get_model("accounts", "User").objects.create(
            username="migration", email="migration@example.test"
        )
        with override_settings(
            LLM_CREDENTIAL_ENCRYPTION_KEYS=f"test:{FERNET_KEY}",
            LLM_CREDENTIAL_ACTIVE_KEY_ID="test",
        ):
            envelope, key_id = encrypt_credential(
                user_id=owner.pk, provider="openai", revision=3, api_key="testing-1111"
            )
            row = state.get_model("accounts", "LLMCredential").objects.create(
                user_id=owner.pk,
                provider="openai",
                revision=3,
                encrypted_envelope=envelope,
                key_suffix="1111",
                encryption_key_id=key_id,
                selected_model="saved-model",
            )
            MigrationExecutor(connection).migrate([new])
            from apps.accounts.models import LLMCredential, LLMPreference

            migrated = LLMCredential.objects.get(pk=row.pk)
            assert decrypt_credential(migrated) == "testing-1111"
            assert (
                migrated.encrypted_envelope == envelope
                and migrated.selected_model == "saved-model"
            )
            assert (
                LLMPreference.objects.get(user_id=owner.pk).active_credential_id
                == row.pk
            )
            MigrationExecutor(connection).migrate([old])
            assert (
                state.get_model("accounts", "LLMCredential")
                .objects.get(pk=row.pk)
                .encrypted_envelope
                == envelope
            )
    finally:
        MigrationExecutor(connection).migrate([new])
