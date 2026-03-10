"""
URL configuration for config project.
"""
from django.contrib import admin
from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.accounts.views import RegisterView

urlpatterns = [
    path("admin/", admin.site.urls),
    # Auth: JWT (use "username" = email, "password"); refresh with "refresh" token
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/register/", RegisterView.as_view(), name="register"),
]
