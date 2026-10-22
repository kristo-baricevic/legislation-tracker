"""Durable research state; cache eviction never removes accepted research."""
import uuid
from django.conf import settings
from django.db import models


class ResearchRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    representative = models.ForeignKey("congress.Representative", on_delete=models.CASCADE)
    period = models.PositiveSmallIntegerField()
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=24, default="queued")
    sections = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)
    work_item = models.OneToOneField("ingestion.IngestionWorkItem", null=True, on_delete=models.SET_NULL)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["representative", "period"], condition=models.Q(status__in=["queued", "running"]), name="research_active_scope_unique")]
        indexes = [models.Index(fields=["representative", "period", "created_at"])]


class ResearchSource(models.Model):
    provider = models.CharField(max_length=40)
    url = models.URLField(max_length=2048)
    revision = models.CharField(max_length=128, blank=True)
    content_hash = models.CharField(max_length=64)
    fetched_at = models.DateTimeField(auto_now_add=True)
    attribution = models.TextField(blank=True)
    license = models.CharField(max_length=255, blank=True)
    parser_version = models.CharField(max_length=32, default="research-1")


class RepresentativeBiography(models.Model):
    representative = models.ForeignKey("congress.Representative", on_delete=models.CASCADE)
    source = models.ForeignKey(ResearchSource, on_delete=models.PROTECT)
    text = models.TextField()
    evidence = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class RepresentativePortrait(models.Model):
    representative = models.ForeignKey("congress.Representative", on_delete=models.CASCADE)
    source = models.ForeignKey(ResearchSource, on_delete=models.PROTECT)
    image_url = models.URLField(max_length=2048)
    object_key = models.CharField(max_length=512, blank=True)
    content_hash = models.CharField(max_length=64, blank=True)
    mime_type = models.CharField(max_length=32, blank=True)
    width = models.PositiveIntegerField(null=True)
    height = models.PositiveIntegerField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ResearchSourcePolicy(models.Model):
    """Staff-reviewed per-source identity, extraction and reuse permission."""
    representative = models.ForeignKey("congress.Representative", on_delete=models.CASCADE)
    kind = models.CharField(max_length=16, choices=[("biography", "Biography"), ("portrait", "Portrait")])
    url = models.URLField(max_length=2048)
    approved = models.BooleanField(default=False)
    attribution = models.TextField(blank=True)
    license = models.TextField(blank=True)
    element_id = models.CharField(max_length=128, blank=True)
    identity_text = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["representative", "kind", "url"], name="research_source_policy_unique")]

    def clean(self):
        from urllib.parse import urlsplit
        from django.core.exceptions import ValidationError
        from .portraits import official_portrait_url
        url = urlsplit(self.url)
        official = urlsplit(self.representative.official_website_url or "").hostname
        if self.kind == "portrait":
            valid = official_portrait_url(self.url) and self.url.split("/member/")[1][:7] == self.representative.bioguide_id.lower()
        else:
            valid = (url.scheme == "https" and url.hostname == official and official
                     and (official.endswith(".house.gov") or official.endswith(".senate.gov"))
                     and not url.username and not url.password and url.port in (None, 443)
                     and not url.fragment and self.element_id and self.identity_text)
        if not valid:
            raise ValidationError("Use this member's verified official source and identity/extraction markers.")
        if self.approved and (not self.license or not self.attribution):
            raise ValidationError("Approval requires attribution and recorded reuse permission.")
