import uuid

from django.conf import settings
from django.db import models, transaction


class CandidateIdentity(models.Model):
    fec_id = models.CharField(max_length=9, primary_key=True)
    name = models.CharField(max_length=255)
    office = models.CharField(max_length=1)
    state = models.CharField(max_length=2)
    reporting_periods = models.JSONField(default=dict)


class RepresentativeCandidate(models.Model):
    representative = models.ForeignKey(
        "congress.Representative", on_delete=models.CASCADE
    )
    candidate = models.ForeignKey(CandidateIdentity, on_delete=models.PROTECT)
    periods = models.JSONField(default=list)
    verified = models.BooleanField(default=False)
    rejected_periods = models.JSONField(default=list, editable=False)
    revoked = models.BooleanField(default=False, editable=False)
    evidence_url = models.URLField(max_length=2048, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["representative", "candidate"],
                name="finance_rep_candidate_unique",
            )
        ]

    def save(self, *args, **kwargs):
        # Lock the same representative as publication: a revoked identity must
        # never race with a worker publishing a snapshot under that identity.
        from apps.congress.models import Representative

        with transaction.atomic():
            old = (
                type(self)
                .objects.filter(pk=self.pk)
                .values(
                    "representative_id",
                    "verified",
                    "periods",
                    "candidate_id",
                    "evidence_url",
                    "revoked",
                )
                .first()
                if self.pk
                else None
            )
            affected = {
                self.representative_id,
                old["representative_id"] if old else self.representative_id,
            }
            list(
                Representative.objects.select_for_update()
                .filter(pk__in=affected)
                .order_by("pk")
            )
            fields = kwargs.get("update_fields")
            if old and (fields is None or "periods" in fields):
                previous, rejected = (
                    type(self)
                    .objects.values_list("periods", "rejected_periods")
                    .get(pk=self.pk)
                )
                self.rejected_periods = sorted(
                    (set(rejected) | set(previous)) - set(self.periods)
                )
                if fields is not None:
                    kwargs["update_fields"] = set(fields) | {"rejected_periods"}
            if fields is None or {"verified", "evidence_url"}.intersection(fields):
                verified = (
                    self.verified
                    if fields is None or "verified" in fields
                    else old["verified"]
                )
                evidence = (
                    self.evidence_url
                    if fields is None or "evidence_url" in fields
                    else old["evidence_url"]
                )
                if verified and evidence:
                    self.revoked = False
                elif old and old["verified"] and old["evidence_url"]:
                    self.revoked = True
                if fields is not None:
                    kwargs["update_fields"] = set(kwargs["update_fields"]) | {"revoked"}
            super().save(*args, **kwargs)
            if old is None or old != {k: getattr(self, k) for k in old}:
                snapshots = FinanceSnapshot.objects.filter(
                    representative_id__in=affected
                )
                if (
                    old
                    and old["verified"]
                    and self.verified
                    and self.evidence_url
                    and all(
                        old[key] == getattr(self, key)
                        for key in ("representative_id", "candidate_id", "evidence_url")
                    )
                    and set(old["periods"]).issubset(self.periods)
                ):
                    # Adding a newly verified period does not revoke earlier proof.
                    snapshots = snapshots.exclude(period__in=old["periods"])
                snapshots.update(active=False, invalidated=True)


class CampaignCommittee(models.Model):
    fec_id = models.CharField(max_length=9, primary_key=True)
    name = models.CharField(max_length=255)


class CandidateCommittee(models.Model):
    candidate = models.ForeignKey(CandidateIdentity, on_delete=models.PROTECT)
    committee = models.ForeignKey(CampaignCommittee, on_delete=models.PROTECT)
    period = models.PositiveSmallIntegerField()
    designation = models.CharField(max_length=1)
    source_url = models.URLField(max_length=2048)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["candidate", "committee", "period"],
                name="finance_candidate_committee_unique",
            )
        ]


class Contributor(models.Model):
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=24)


class ContributorIdentity(models.Model):
    contributor = models.ForeignKey(Contributor, on_delete=models.PROTECT)
    provider_key = models.CharField(max_length=255, unique=True)
    verified = models.BooleanField(default=False)


class FinanceSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    representative = models.ForeignKey(
        "congress.Representative", on_delete=models.CASCADE
    )
    run = models.OneToOneField("research.ResearchRun", on_delete=models.PROTECT)
    period = models.PositiveSmallIntegerField()
    active = models.BooleanField(default=False)
    invalidated = models.BooleanField(default=False)
    coverage = models.CharField(max_length=32, default="partial")
    totals = models.JSONField(default=dict)
    candidate_ids = models.JSONField(default=list)
    committee_links = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True)
    normalization_version = models.CharField(max_length=24, default="fec-1")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["representative", "period"],
                condition=models.Q(active=True),
                name="finance_active_snapshot_unique",
            )
        ]


class FinanceTransaction(models.Model):
    snapshot = models.ForeignKey(
        FinanceSnapshot, on_delete=models.CASCADE, related_name="transactions"
    )
    source_key = models.CharField(max_length=255)
    committee = models.ForeignKey(CampaignCommittee, on_delete=models.PROTECT)
    contributor = models.ForeignKey(Contributor, null=True, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    date = models.DateField(null=True)
    kind = models.CharField(max_length=32)
    source_url = models.URLField(max_length=2048)
    effective = models.BooleanField(default=True)
    exclusion_reason = models.CharField(max_length=64, blank=True)
    filing_id = models.CharField(max_length=64, blank=True)
    source_metadata = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "source_key"], name="finance_snapshot_record_unique"
            )
        ]
        indexes = [models.Index(fields=["contributor", "date"])]


class FinanceResearchCheckpoint(models.Model):
    snapshot = models.ForeignKey(
        FinanceSnapshot, on_delete=models.CASCADE, related_name="checkpoints"
    )
    committee = models.ForeignKey(CampaignCommittee, on_delete=models.PROTECT)
    schedule = models.CharField(max_length=8, default="a")
    cursor = models.JSONField(default=dict)
    page_hashes = models.JSONField(default=list)
    complete = models.BooleanField(default=False)
    source_totals = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "committee", "schedule"],
                name="finance_checkpoint_schedule_uniq",
            )
        ]


class OutsideSpendingScan(models.Model):
    snapshot = models.ForeignKey(
        FinanceSnapshot, on_delete=models.CASCADE, related_name="outside_scans"
    )
    candidate_id = models.CharField(max_length=9)
    category = models.CharField(
        max_length=20,
        default="independent",
        choices=[
            ("independent", "Independent expenditures"),
            ("communication", "Communication costs"),
            ("electioneering", "Electioneering communications"),
        ],
    )
    page = models.PositiveIntegerField(default=1)
    complete = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "candidate_id", "category"],
                name="outside_scan_category_unique",
            )
        ]


class OutsideSpendingTotal(models.Model):
    scan = models.ForeignKey(
        OutsideSpendingScan, on_delete=models.CASCADE, related_name="totals"
    )
    spender_id = models.CharField(max_length=9)
    spender_name = models.CharField(max_length=255)
    position = models.CharField(
        max_length=3,
        choices=[
            ("S", "Supporting"),
            ("O", "Opposing"),
            ("M", "Mentioned"),
            ("24F", "Supporting communication"),
            ("24N", "Opposing communication"),
        ],
    )
    amount = models.DecimalField(max_digits=20, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["scan", "spender_id", "position"],
                name="outside_spender_position_unique",
            )
        ]


class ConnectionRevision(models.Model):
    """Database-triggered generation, including bulk ingestion mutations."""

    generation = models.PositiveBigIntegerField(default=0)
    epoch = models.UUIDField(default=uuid.uuid4)


class OutsideSpendingRevision(models.Model):
    """Per-representative revision; unrelated ingestion must not evict pages."""

    representative = models.OneToOneField(
        "congress.Representative", primary_key=True, on_delete=models.CASCADE
    )
    generation = models.PositiveBigIntegerField(default=0)
    epoch = models.UUIDField(default=uuid.uuid4)


class ConfirmedCandidate(models.Model):
    """A reader's explicit identity decision for one FEC reporting cycle."""

    representative = models.ForeignKey(
        "congress.Representative", on_delete=models.CASCADE
    )
    period = models.PositiveSmallIntegerField()
    candidate = models.ForeignKey(CandidateIdentity, on_delete=models.PROTECT)
    review_run = models.OneToOneField("research.ResearchRun", on_delete=models.PROTECT)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    confirmed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["representative", "period"],
                name="confirmed_candidate_per_cycle",
            )
        ]
