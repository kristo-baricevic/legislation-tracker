from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.llm_credentials import (
    CredentialDecryptionError,
    decrypt_credential,
    encrypt_credential,
    parse_encryption_key_ring,
)
from apps.accounts.models import LLMCredential


class Command(BaseCommand):
    help = "Re-encrypt stored LLM credentials with the active key without changing revision."

    def add_arguments(self, parser):
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--batch-size", type=int, default=100)

    def handle(self, *args, **options):
        if not options["execute"]:
            raise CommandError("Pass --execute to rotate stored credentials.")
        batch_size = options["batch_size"]
        if batch_size <= 0 or batch_size > 1000:
            raise CommandError("--batch-size must be between 1 and 1000.")
        active_key_id = settings.LLM_CREDENTIAL_ACTIVE_KEY_ID
        key_ring = parse_encryption_key_ring()
        if not active_key_id or active_key_id not in key_ring:
            raise CommandError("The active credential encryption key is unavailable.")

        rotated = 0
        while True:
            ids = list(
                LLMCredential.objects.exclude(encryption_key_id=active_key_id)
                .order_by("id")
                .values_list("id", flat=True)[:batch_size]
            )
            if not ids:
                break
            with transaction.atomic():
                credentials = list(
                    LLMCredential.objects.select_for_update()
                    .filter(pk__in=ids)
                    .order_by("id")
                )
                for credential in credentials:
                    try:
                        api_key = decrypt_credential(credential)
                    except CredentialDecryptionError as exc:
                        raise CommandError(
                            f"Could not decrypt credential id={credential.id}; no batch changes were committed."
                        ) from exc
                    encrypted_envelope, key_id = encrypt_credential(
                        user_id=credential.user_id,
                        provider=credential.provider,
                        revision=credential.revision,
                        api_key=api_key,
                    )
                    credential.encrypted_envelope = encrypted_envelope
                    credential.encryption_key_id = key_id
                    credential.save(
                        update_fields=[
                            "encrypted_envelope",
                            "encryption_key_id",
                            "updated_at",
                        ]
                    )
                    rotated += 1
            self.stdout.write(f"rotated={rotated}")
        self.stdout.write(f"complete rotated={rotated} active_key_id={active_key_id}")
