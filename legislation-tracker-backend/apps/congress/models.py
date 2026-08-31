from django.db import models

from .current import current_congress


class Representative(models.Model):
    """Member of Congress (House or Senate). Stable identity via bioguide_id from Congress API."""

    bioguide_id = models.CharField(max_length=20, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    chamber = models.CharField(max_length=20)  # house, senate
    party = models.CharField(max_length=50)
    state = models.CharField(max_length=2)
    district = models.CharField(max_length=10, null=True, blank=True)  # House only
    first_name = models.CharField(max_length=255, blank=True, default="")
    last_name = models.CharField(max_length=255, blank=True, default="")
    official_website_url = models.URLField(max_length=1024, null=True, blank=True)
    image_url = models.URLField(max_length=1024, null=True, blank=True)
    source_api_url = models.URLField(max_length=1024, null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
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


class RepresentativeTerm(models.Model):
    """One continuous chamber service interval from the Congress member API."""

    representative = models.ForeignKey(
        Representative,
        on_delete=models.CASCADE,
        related_name="service_terms",
    )
    chamber = models.CharField(max_length=20)
    state = models.CharField(max_length=2, blank=True, default="")
    district = models.CharField(max_length=10, null=True, blank=True)
    member_type = models.CharField(max_length=50, blank=True, default="")
    start_date = models.DateField()
    # Congress.gov terms use an exclusive January 3 end boundary.
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "congress_representativeterm"
        constraints = [
            models.UniqueConstraint(
                fields=["representative", "chamber", "start_date"],
                name="congress_rep_term_identity_uniq",
            )
        ]
        indexes = [
            models.Index(
                fields=["representative", "start_date", "end_date"],
                name="congress_rep_term_dates_idx",
            )
        ]


class Vote(models.Model):
    """Roll-call vote on a bill."""

    bill = models.ForeignKey(
        "legislation.Bill",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="votes",
    )
    congress = models.PositiveSmallIntegerField(
        default=current_congress,
        db_index=True,
    )
    chamber = models.CharField(max_length=20)
    # Legacy rows predate authoritative Congress API session references.
    session_number = models.PositiveSmallIntegerField(
        null=True, blank=True, default=None
    )
    roll_number = models.PositiveIntegerField()
    vote_date = models.DateTimeField()
    result = models.CharField(max_length=50)  # passed, failed, etc.
    yeas = models.PositiveIntegerField(default=0)
    nays = models.PositiveIntegerField(default=0)
    question = models.TextField(blank=True, default="")
    source_url = models.URLField(max_length=1024, blank=True, default="")
    source_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "congress_vote"
        constraints = [
            models.UniqueConstraint(
                fields=["congress", "chamber", "session_number", "roll_number"],
                name="congress_vote_identity_session_uniq",
            ),
            models.UniqueConstraint(
                fields=["congress", "chamber", "roll_number"],
                condition=models.Q(session_number__isnull=True),
                name="congress_vote_identity_unknown_session_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["congress", "chamber", "vote_date"],
                name="congress_vote_scope_date_idx",
            ),
            models.Index(
                fields=["congress", "chamber", "source_updated_at"],
                name="congress_vote_source_idx",
            ),
        ]

    def __str__(self):
        return f"Vote {self.session_number}/{self.roll_number} on Bill {self.bill_id}"


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

    class Position(models.TextChoices):
        YES = "yes", "Yes"
        NO = "no", "No"
        PRESENT = "present", "Present"
        NOT_VOTING = "not_voting", "Not voting"
        OTHER = "other", "Other"

    position = models.CharField(max_length=20, choices=Position.choices)
    raw_position = models.CharField(max_length=100, blank=True, default="")

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
            models.Index(
                fields=["representative", "vote"],
                name="congress_record_rep_vote_idx",
            ),
        ]


class Committee(models.Model):
    class Chamber(models.TextChoices):
        HOUSE = "house", "House"
        SENATE = "senate", "Senate"
        JOINT = "joint", "Joint"

    system_code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    chamber = models.CharField(max_length=16, choices=Chamber.choices)
    committee_type = models.CharField(max_length=32, blank=True, default="")
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="subcommittees",
    )
    website_url = models.URLField(max_length=1024, blank=True, default="")
    is_current = models.BooleanField(default=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "congress_committee"
        indexes = [models.Index(fields=["chamber", "is_current"])]


class CommitteeMembership(models.Model):
    class Role(models.TextChoices):
        MEMBER = "member", "Member"
        CHAIR = "chair", "Chair"
        RANKING_MEMBER = "ranking_member", "Ranking member"
        VICE_CHAIR = "vice_chair", "Vice chair"
        OTHER = "other", "Other"

    committee = models.ForeignKey(
        Committee,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    representative = models.ForeignKey(
        Representative,
        on_delete=models.CASCADE,
        related_name="committee_memberships",
    )
    congress = models.PositiveSmallIntegerField()
    rank = models.PositiveSmallIntegerField(null=True, blank=True)
    role = models.CharField(max_length=24, choices=Role.choices, default=Role.MEMBER)
    party_side = models.CharField(max_length=32, blank=True, default="")
    source_name = models.CharField(max_length=32)
    source_code = models.CharField(max_length=32)
    source_hash = models.CharField(max_length=64, blank=True, default="")
    is_current = models.BooleanField(default=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "congress_committeemembership"
        constraints = [
            models.UniqueConstraint(
                fields=["committee", "representative", "congress"],
                name="congress_committee_member_congress_uniq",
            )
        ]
        indexes = [
            models.Index(
                fields=["representative", "congress", "is_current"],
                name="cong_mem_rep_scope_idx",
            ),
            models.Index(
                fields=["committee", "congress", "is_current"],
                name="cong_mem_comm_scope_idx",
            ),
        ]


class CommitteeRosterSnapshot(models.Model):
    """Last accepted complete official roster for a chamber/Congress scope."""

    congress = models.PositiveSmallIntegerField()
    chamber = models.CharField(max_length=16, choices=Committee.Chamber.choices)
    source_url = models.URLField(max_length=1024)
    source_hash = models.CharField(max_length=64)
    published_at = models.DateTimeField()
    assignment_count = models.PositiveIntegerField()
    representative_count = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "congress_committeerostersnapshot"
        constraints = [
            models.UniqueConstraint(
                fields=["congress", "chamber"],
                name="congress_committee_roster_scope_uniq",
            )
        ]


class BillCommittee(models.Model):
    bill = models.ForeignKey(
        "legislation.Bill",
        on_delete=models.CASCADE,
        related_name="committee_relationships",
    )
    committee = models.ForeignKey(
        Committee,
        on_delete=models.CASCADE,
        related_name="bill_relationships",
    )
    relationship_type = models.CharField(max_length=32, default="referred")
    activity_name = models.CharField(max_length=255, blank=True, default="")
    source_name = models.CharField(max_length=32, blank=True, default="congress")
    source_code = models.CharField(max_length=32, blank=True, default="")
    source_updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "congress_billcommittee"
        constraints = [
            models.UniqueConstraint(
                fields=["bill", "committee", "relationship_type"],
                name="congress_bill_committee_relationship_uniq",
            )
        ]
        indexes = [models.Index(fields=["bill", "relationship_type"])]


class BillCosponsor(models.Model):
    bill = models.ForeignKey(
        "legislation.Bill",
        on_delete=models.CASCADE,
        related_name="cosponsors",
    )
    representative = models.ForeignKey(
        Representative,
        on_delete=models.CASCADE,
        related_name="cosponsored_bills",
    )
    sponsorship_date = models.DateField(null=True, blank=True)
    is_original_cosponsor = models.BooleanField(default=False)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "congress_billcosponsor"
        constraints = [
            models.UniqueConstraint(
                fields=["bill", "representative"],
                name="congress_bill_cosponsor_uniq",
            )
        ]
        indexes = [
            models.Index(
                fields=["representative", "withdrawn_at"],
                name="cong_cosponsor_rep_idx",
            )
        ]
