from django.contrib.auth.models import AbstractUser
from django.db import models, transaction


class User(AbstractUser):
    """Custom user with email as the primary identifier."""

    email = models.EmailField("email address", unique=True)
    # Remove username from required; we use email
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]  # username still exists but not for login

    class Meta:
        db_table = "accounts_user"

    def __str__(self):
        return self.email


class LLMCredentialManager(models.Manager):
    def create_for_key(self, *, user, provider, api_key, enabled=True):
        from .llm_credentials import encrypt_credential

        normalized_key = (api_key or "").strip()
        if not normalized_key:
            raise ValueError("API key is required")
        normalized_provider = (provider or "").strip().lower()
        if not normalized_provider:
            raise ValueError("Provider is required")

        with transaction.atomic():
            # A credential row does not exist for a user's first write, so it
            # cannot serve as the serialization lock. The user row is stable
            # across both initial creation and later replacement.
            locked_user = type(user).objects.select_for_update().get(pk=user.pk)
            credential = self.select_for_update().filter(user=locked_user).first()
            revision = (credential.revision + 1) if credential else 1
            encrypted_envelope, key_id = encrypt_credential(
                user_id=locked_user.pk,
                provider=normalized_provider,
                revision=revision,
                api_key=normalized_key,
            )
            values = {
                "provider": normalized_provider,
                "encrypted_envelope": encrypted_envelope,
                "key_suffix": normalized_key[-4:],
                "encryption_key_id": key_id,
                "revision": revision,
                "enabled": enabled if credential is None else credential.enabled,
                "validation_status": LLMCredential.ValidationStatus.UNVERIFIED,
                "validated_revision": None,
                "validated_provider": "",
                "validated_model": "",
                "validated_at": None,
            }
            if credential is None:
                credential = self.create(user=locked_user, **values)
            else:
                for field, value in values.items():
                    setattr(credential, field, value)
                credential.save(update_fields=[*values, "updated_at"])
            return credential


class LLMCredential(models.Model):
    class ValidationStatus(models.TextChoices):
        UNVERIFIED = "unverified", "Unverified"
        VALID = "valid", "Valid"
        INVALID = "invalid", "Invalid"

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="llm_credential",
    )
    provider = models.CharField(max_length=32, default="openai")
    encrypted_envelope = models.TextField()
    key_suffix = models.CharField(max_length=4)
    encryption_key_id = models.CharField(max_length=64)
    revision = models.PositiveIntegerField(default=1)
    enabled = models.BooleanField(default=True)
    validation_status = models.CharField(
        max_length=16,
        choices=ValidationStatus.choices,
        default=ValidationStatus.UNVERIFIED,
    )
    validated_revision = models.PositiveIntegerField(null=True, blank=True)
    validated_provider = models.CharField(max_length=32, blank=True, default="")
    validated_model = models.CharField(max_length=128, blank=True, default="")
    validated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = LLMCredentialManager()

    class Meta:
        db_table = "accounts_llmcredential"

    def replace_key(self, api_key, *, provider=None):
        fresh = type(self).objects.create_for_key(
            user=self.user,
            provider=provider or self.provider,
            api_key=api_key,
            enabled=self.enabled,
        )
        self.refresh_from_db()
        return fresh

    def __str__(self):
        return f"{self.provider} credential for user {self.user_id}"


class UserPreference(models.Model):
    """Non-tracking user preferences such as state and chamber."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="preferences",
    )
    state = models.CharField(max_length=2, null=True, blank=True)
    chamber = models.CharField(max_length=20, null=True, blank=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "accounts_userpreference"

    def __str__(self):
        parts = [f"User {self.user_id}"]
        if self.state:
            parts.append(f"state={self.state}")
        if self.chamber:
            parts.append(f"chamber={self.chamber}")
        return " ".join(parts)


class SavedBillSearch(models.Model):
    """A private normalized bill query and its acknowledged activity watermark."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="saved_bill_searches",
    )
    name = models.CharField(max_length=120)
    query_json = models.JSONField(default=dict)
    normalized_hash = models.CharField(max_length=64)
    last_opened_at = models.DateTimeField(null=True, blank=True)
    last_opened_activity_sequence = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounts_savedbillsearch"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"],
                name="accounts_saved_search_user_name_uniq",
            ),
            models.UniqueConstraint(
                fields=["user", "normalized_hash"],
                name="accounts_saved_search_user_query_uniq",
            ),
        ]
        indexes = [models.Index(fields=["user", "updated_at"])]

    def __str__(self):
        return f"{self.user_id}:{self.name}"


class TrackedBill(models.Model):
    """A bill a user is personally tracking."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="tracked_bills",
    )
    bill = models.ForeignKey(
        "legislation.Bill",
        on_delete=models.CASCADE,
        related_name="tracked_by_users",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_trackedbill"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "bill"],
                name="accounts_trackedbill_user_bill_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["bill"]),
        ]

    def __str__(self):
        return f"User {self.user_id} tracks bill {self.bill_id}"


class TrackedTopic(models.Model):
    """A policy topic a user is personally tracking."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="tracked_topics",
    )
    topic = models.ForeignKey(
        "legislation.Topic",
        on_delete=models.CASCADE,
        related_name="tracked_by_users",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_trackedtopic"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "topic"],
                name="accounts_trackedtopic_user_topic_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["topic"]),
        ]

    def __str__(self):
        return f"User {self.user_id} tracks topic {self.topic_id}"


class TrackedLegislator(models.Model):
    """A legislator a user is personally tracking."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="tracked_legislators",
    )
    representative = models.ForeignKey(
        "congress.Representative",
        on_delete=models.CASCADE,
        related_name="tracked_by_users",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_trackedlegislator"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "representative"],
                name="accounts_trackedlegislator_user_rep_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["representative"]),
        ]

    def __str__(self):
        return f"User {self.user_id} tracks representative {self.representative_id}"
