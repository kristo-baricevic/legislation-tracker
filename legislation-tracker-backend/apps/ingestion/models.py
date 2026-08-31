from django.db import models
from django.utils import timezone


class IngestionWorkStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    DISPATCHED = "dispatched", "Dispatched"
    PROCESSING = "processing", "Processing"
    BLOCKED = "blocked", "Blocked"
    SUCCEEDED = "succeeded", "Succeeded"
    DEAD = "dead", "Dead"


class BillTrackingRequestStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    FULFILLED = "fulfilled", "Fulfilled"


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
    # Exact external identities required before this work can be processed.
    # A blocked row is intentionally not retried or dead-lettered: the detail
    # worker that satisfies its identities wakes it explicitly.
    dependency_keys = models.JSONField(default=list, blank=True)
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


class RollCallIngestionState(models.Model):
    """Durable discovery cursor for one official chamber/session roll-call feed."""

    congress = models.PositiveSmallIntegerField()
    chamber = models.CharField(max_length=16)
    session_number = models.PositiveSmallIntegerField()
    next_page_or_roll = models.CharField(max_length=255, blank=True, default="")
    discovered_roll_count = models.PositiveIntegerField(default=0)
    source_exhausted_at = models.DateTimeField(null=True, blank=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    last_polled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ingestion_rollcallingestionstate"
        constraints = [
            models.UniqueConstraint(
                fields=["congress", "chamber", "session_number"],
                name="ingest_roll_state_scope_uniq",
            )
        ]
        indexes = [
            models.Index(
                fields=["congress", "chamber", "session_number"],
                name="ingest_roll_state_scope_idx",
            )
        ]


class BillTrackingRequest(models.Model):
    """Durable user intent to track a bill created by manual ingestion."""

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="bill_tracking_requests",
    )
    work_item = models.ForeignKey(
        IngestionWorkItem,
        on_delete=models.PROTECT,
        related_name="tracking_requests",
    )
    bill = models.ForeignKey(
        "legislation.Bill",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tracking_requests",
    )
    jurisdiction = models.CharField(max_length=20, default="federal")
    congress = models.PositiveIntegerField()
    bill_type = models.CharField(max_length=10)
    bill_number = models.CharField(max_length=32)
    status = models.CharField(
        max_length=20,
        choices=BillTrackingRequestStatus.choices,
        default=BillTrackingRequestStatus.PENDING,
        db_index=True,
    )
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ingestion_billtrackingrequest"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "user",
                    "jurisdiction",
                    "congress",
                    "bill_type",
                    "bill_number",
                ],
                name="ingest_tracking_request_user_bill_uniq",
            )
        ]
        indexes = [
            models.Index(
                fields=[
                    "status",
                    "jurisdiction",
                    "congress",
                    "bill_type",
                    "bill_number",
                ],
                name="ingest_track_pending_bill_idx",
            )
        ]

    def __str__(self):
        return (
            f"user={self.user_id} {self.congress}-{self.bill_type}-{self.bill_number} "
            f"({self.status})"
        )


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
    replay_claim_token = models.CharField(max_length=32, blank=True, default="")
    replay_claim_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "ingestion_ingestiontaskfailure"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.task_name} {self.task_id}"
