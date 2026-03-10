from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, UserPreference


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("email", "is_staff", "is_active")
    list_filter = ("is_staff", "is_active")
    search_fields = ("email",)
    ordering = ("email",)
    filter_horizontal = ()

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Permissions", {"fields": ("is_staff", "is_active")}),
    )
    add_fieldsets = (
        (None, {"fields": ("email", "password1", "password2")}),
        ("Permissions", {"fields": ("is_staff", "is_active")}),
    )


admin.site.register(UserPreference)
