from django.contrib.auth.models import AbstractUser
from django.db import models


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


class UserPreference(models.Model):
    """User preferences: followed topic, state, chamber. Multiple rows per user."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="preferences",
    )
    topic = models.ForeignKey(
        "legislation.Topic",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="user_preferences",
    )
    state = models.CharField(max_length=2, null=True, blank=True)
    chamber = models.CharField(max_length=20, null=True, blank=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "accounts_userpreference"

    def __str__(self):
        parts = [f"User {self.user_id}"]
        if self.topic_id:
            parts.append(f"topic={self.topic_id}")
        if self.state:
            parts.append(f"state={self.state}")
        if self.chamber:
            parts.append(f"chamber={self.chamber}")
        return " ".join(parts)
