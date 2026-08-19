from django.db import models


class Representative(models.Model):
    """Member of Congress (House or Senate). Stable identity via bioguide_id from Congress API."""

    bioguide_id = models.CharField(max_length=20, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    chamber = models.CharField(max_length=20)  # house, senate
    party = models.CharField(max_length=50)
    state = models.CharField(max_length=2)
    district = models.CharField(max_length=10, null=True, blank=True)  # House only
    is_current = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "congress_representative"
        indexes = [
            models.Index(fields=["chamber"]),
            models.Index(fields=["state"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.state}-{self.chamber})"


class Vote(models.Model):
    """Roll-call vote on a bill."""

    bill = models.ForeignKey(
        "legislation.Bill",
        on_delete=models.CASCADE,
        related_name="votes",
    )
    chamber = models.CharField(max_length=20)
    roll_number = models.PositiveIntegerField()
    vote_date = models.DateTimeField()
    result = models.CharField(max_length=50)  # passed, failed, etc.
    yeas = models.PositiveIntegerField(default=0)
    nays = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "congress_vote"
        constraints = [
            models.UniqueConstraint(
                fields=["bill", "chamber", "roll_number"],
                name="congress_vote_bill_chamber_roll_uniq",
            )
        ]

    def __str__(self):
        return f"Vote {self.roll_number} on Bill {self.bill_id}"


class VoteRecord(models.Model):
    """One representative's position on a vote."""

    vote = models.ForeignKey(
        Vote,
        on_delete=models.CASCADE,
        related_name="records",
    )
    representative = models.ForeignKey(
        Representative,
        on_delete=models.CASCADE,
        related_name="vote_records",
    )
    position = models.CharField(max_length=20)  # yes, no, abstain, present

    class Meta:
        db_table = "congress_voterecord"
        constraints = [
            models.UniqueConstraint(
                fields=["vote", "representative"],
                name="congress_voterecord_vote_representative_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["vote"]),
            models.Index(fields=["representative"]),
        ]
