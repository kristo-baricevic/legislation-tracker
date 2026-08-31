from django.contrib import admin

from .models import (
    BillCommittee,
    BillCosponsor,
    Committee,
    CommitteeMembership,
    CommitteeRosterSnapshot,
    Representative,
    Vote,
    VoteRecord,
)

admin.site.register(Representative)
admin.site.register(Vote)
admin.site.register(VoteRecord)


@admin.register(Committee)
class CommitteeAdmin(admin.ModelAdmin):
    list_display = ("system_code", "name", "chamber", "is_current", "source_updated_at")
    search_fields = ("system_code", "name")
    list_filter = ("chamber", "is_current")


@admin.register(CommitteeMembership)
class CommitteeMembershipAdmin(admin.ModelAdmin):
    list_display = (
        "committee",
        "representative",
        "congress",
        "role",
        "is_current",
        "source_updated_at",
    )
    list_filter = ("congress", "role", "is_current", "source_name")
    search_fields = ("committee__system_code", "representative__bioguide_id")


@admin.register(CommitteeRosterSnapshot)
class CommitteeRosterSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "congress",
        "chamber",
        "published_at",
        "assignment_count",
        "representative_count",
        "source_hash",
    )
    list_filter = ("congress", "chamber")


admin.site.register(BillCommittee)
admin.site.register(BillCosponsor)
