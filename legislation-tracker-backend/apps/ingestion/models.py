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
