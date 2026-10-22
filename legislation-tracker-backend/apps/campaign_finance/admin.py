from django.contrib import admin
from .models import CandidateIdentity, RepresentativeCandidate, CampaignCommittee, CandidateCommittee, FinanceSnapshot


@admin.register(RepresentativeCandidate)
class RepresentativeCandidateAdmin(admin.ModelAdmin):
    list_display = ["representative", "candidate", "periods", "verified", "evidence_url"]
    list_filter = ["verified"]
    search_fields = ["representative__name", "candidate__fec_id"]

    def has_delete_permission(self, request, obj=None):
        # Revoke verification instead: preserve the audit trail and invalidate
        # snapshots through the model's locked save path.
        return False


admin.site.register(CandidateIdentity)
admin.site.register(CampaignCommittee)
admin.site.register(CandidateCommittee)


@admin.register(FinanceSnapshot)
class FinanceSnapshotAdmin(admin.ModelAdmin):
    list_display = ["representative", "period", "coverage", "active", "published_at"]
    def has_change_permission(self, request, obj=None):
        return False
    def has_add_permission(self, request):
        return False
    def has_delete_permission(self, request, obj=None):
        return False
