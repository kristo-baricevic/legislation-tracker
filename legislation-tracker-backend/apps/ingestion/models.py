from django.db import models


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


class IngestionTaskFailure(models.Model):
    """Dead-letter: record of a task that failed after all retries."""

    task_id = models.CharField(max_length=255, db_index=True)
    bill_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    task_name = models.CharField(max_length=255)
    args_json = models.JSONField(default=dict, blank=True)
    error_message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "ingestion_ingestiontaskfailure"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.task_name} {self.task_id}"
