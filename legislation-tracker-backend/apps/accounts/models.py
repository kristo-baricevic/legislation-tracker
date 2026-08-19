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
