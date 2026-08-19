from django.db import models
from django.utils import timezone


class IngestionWorkStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    DISPATCHED = "dispatched", "Dispatched"
    PROCESSING = "processing", "Processing"
    SUCCEEDED = "succeeded", "Succeeded"
    DEAD = "dead", "Dead"


class IngestionState(models.Model):
    """Tracks polling cursors so we only fetch bills updated since last run."""

    jurisdiction = models.CharField(max_length=20, default="federal")
    congress = models.PositiveIntegerField()  # e.g. 119
    last_polled_at = models.DateTimeField(null=True, blank=True)
    last_bill_update_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ingestion_ingestionstate"
        constraints = [
            models.UniqueConstraint(
                fields=["jurisdiction", "congress"],
                name="ingestion_state_jurisdiction_congress_uniq",
            )
        ]

    def __str__(self):
        return f"{self.jurisdiction} congress {self.congress}"


class IngestionWorkItem(models.Model):
    """Durable, deduplicated ingestion work discovered from upstream sources."""

    kind = models.CharField(max_length=64)
    dedupe_key = models.CharField(max_length=255)
    jurisdiction = models.CharField(max_length=20, default="federal")
    congress = models.PositiveIntegerField(null=True, blank=True)
    source_updated_at = models.DateTimeField()
    payload_json = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20,
        choices=IngestionWorkStatus.choices,
        default=IngestionWorkStatus.PENDING,
        db_index=True,
    )
    attempt_count = models.PositiveIntegerField(default=0)
    available_at = models.DateTimeField(default=timezone.now, db_index=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    celery_task_id = models.CharField(max_length=255, blank=True, default="")
    dispatch_token = models.CharField(max_length=32, blank=True, default="")
    last_error = models.TextField(blank=True, default="")
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ingestion_ingestionworkitem"
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "dedupe_key", "source_updated_at"],
                name="ingestion_work_item_source_version_uniq",
            )
        ]
        indexes = [
            models.Index(
                fields=["status", "available_at"],
                name="ingest_work_status_avail_idx",
            ),
        ]
        ordering = ["available_at", "id"]

    def __str__(self):
        return f"{self.kind}:{self.dedupe_key} ({self.status})"


class IngestionTaskFailure(models.Model):
    """Dead-letter: record of a task that failed after all retries."""

    task_id = models.CharField(max_length=255, db_index=True)
    work_item = models.ForeignKey(
        IngestionWorkItem,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="failures",
    )
    bill_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    task_name = models.CharField(max_length=255)
    args_json = models.JSONField(default=dict, blank=True)
    error_message = models.TextField()
    replay_count = models.PositiveIntegerField(default=0)
    last_replayed_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "ingestion_ingestiontaskfailure"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.task_name} {self.task_id}"
