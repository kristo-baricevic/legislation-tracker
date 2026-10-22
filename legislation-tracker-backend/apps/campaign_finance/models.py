import uuid
from django.db import models, transaction


class CandidateIdentity(models.Model):
    fec_id = models.CharField(max_length=9, primary_key=True)
    name = models.CharField(max_length=255)
    office = models.CharField(max_length=1)
    state = models.CharField(max_length=2)


class RepresentativeCandidate(models.Model):
    representative = models.ForeignKey("congress.Representative", on_delete=models.CASCADE)
    candidate = models.ForeignKey(CandidateIdentity, on_delete=models.PROTECT)
    periods = models.JSONField(default=list)
    verified = models.BooleanField(default=False)
    evidence_url = models.URLField(max_length=2048, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["representative", "candidate"], name="finance_rep_candidate_unique")]

    def save(self, *args, **kwargs):
        # Lock the same representative as publication: a revoked identity must
        # never race with a worker publishing a snapshot under that identity.
        from apps.congress.models import Representative
        with transaction.atomic():
            Representative.objects.select_for_update().get(pk=self.representative_id)
            old = type(self).objects.filter(pk=self.pk).values("verified", "periods", "candidate_id", "evidence_url").first() if self.pk else None
            super().save(*args, **kwargs)
            if old and old != {k: getattr(self, k) for k in old}:
                FinanceSnapshot.objects.filter(representative_id=self.representative_id).update(active=False, invalidated=True)


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
        constraints = [models.UniqueConstraint(fields=["candidate", "committee", "period"], name="finance_candidate_committee_unique")]


class Contributor(models.Model):
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=24)


class ContributorIdentity(models.Model):
    contributor = models.ForeignKey(Contributor, on_delete=models.PROTECT)
    provider_key = models.CharField(max_length=255, unique=True)
    verified = models.BooleanField(default=False)


class FinanceSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    representative = models.ForeignKey("congress.Representative", on_delete=models.CASCADE)
    run = models.OneToOneField("research.ResearchRun", on_delete=models.PROTECT)
    period = models.PositiveSmallIntegerField()
    active = models.BooleanField(default=False)
    invalidated = models.BooleanField(default=False)
    coverage = models.CharField(max_length=32, default="partial")
    totals = models.JSONField(default=dict)
    candidate_ids = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True)
    normalization_version = models.CharField(max_length=24, default="fec-1")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["representative", "period"], condition=models.Q(active=True), name="finance_active_snapshot_unique")]


class FinanceTransaction(models.Model):
    snapshot = models.ForeignKey(FinanceSnapshot, on_delete=models.CASCADE, related_name="transactions")
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

    class Meta:
        constraints = [models.UniqueConstraint(fields=["snapshot", "source_key"], name="finance_snapshot_record_unique")]
        indexes = [models.Index(fields=["contributor", "date"])]


class FinanceResearchCheckpoint(models.Model):
    snapshot = models.ForeignKey(FinanceSnapshot, on_delete=models.CASCADE, related_name="checkpoints")
    committee = models.ForeignKey(CampaignCommittee, on_delete=models.PROTECT)
    schedule = models.CharField(max_length=8, default="a")
    cursor = models.JSONField(default=dict)
    page_hashes = models.JSONField(default=list)
    complete = models.BooleanField(default=False)
    source_totals = models.JSONField(default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["snapshot", "committee", "schedule"], name="finance_checkpoint_schedule_uniq")]
