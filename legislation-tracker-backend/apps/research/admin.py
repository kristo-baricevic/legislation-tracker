from django.contrib import admin
from .models import ResearchRun, RepresentativeBiography, RepresentativePortrait, ResearchSource


class ResearchReadOnlyAdmin(admin.ModelAdmin):
    def has_change_permission(self, request, obj=None):
        return False
    def has_add_permission(self, request):
        return False
    def has_delete_permission(self, request, obj=None):
        return False


for model in (ResearchRun, RepresentativeBiography, RepresentativePortrait, ResearchSource):
    admin.site.register(model, ResearchReadOnlyAdmin)
