from django.db import models


class BillActivityClock(models.Model):
    """Singleton commit-serialized clock for bill activity snapshots."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    committed_sequence = models.BigIntegerField(default=0)

    class Meta:
        db_table = "changelog_billactivityclock"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(id=1),
                name="changelog_activity_clock_singleton",
            ),
            models.CheckConstraint(
                condition=models.Q(committed_sequence__gte=0),
                name="changelog_activity_clock_nonnegative",
            ),
        ]


class ChangeLog(models.Model):
    """
    Event backbone: one row per meaningful change (status, new version, contract, topic, vote).
    Append-only. PostgreSQL storage is monthly UTC-partitioned by ``created_at``;
    SQLite keeps the normal table for local development and tests.
    """

    bill = models.ForeignKey(
        "legislation.Bill",
        on_delete=models.CASCADE,
        related_name="changelog_entries",
    )
    document = models.ForeignKey(
        "legislation.BillDocument",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="changelog_entries",
    )
    contract = models.ForeignKey(
        "legislation.BillContract",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="changelog_entries",
    )
    change_type = models.CharField(
        max_length=50,
        db_index=True,
    )  # status_update, new_version, contract_update, topic_update, vote
    event_key = models.CharField(max_length=255, null=True, blank=True)
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "changelog_changelog"
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["bill"]),
            models.Index(fields=["change_type"]),
            models.Index(fields=["bill", "event_key"], name="changelog_bill_event_key_idx"),
            models.Index(
                fields=["-created_at", "bill"], name="changelog_created_bill_idx"
            ),
        ]
        ordering = ["-created_at"]
