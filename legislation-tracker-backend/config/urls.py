"""
URL configuration for config project.
"""
from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.accounts.views import RegisterView, UserPreferenceViewSet
from apps.legislation.views import BillViewSet, TopicViewSet
from apps.congress.views import RepresentativeViewSet

router = DefaultRouter()
router.register(r"bills", BillViewSet, basename="bill")
router.register(r"topics", TopicViewSet, basename="topic")
router.register(r"representatives", RepresentativeViewSet, basename="representative")
router.register(r"preferences", UserPreferenceViewSet, basename="preference")

urlpatterns = [
    path("admin/", admin.site.urls),
    # Auth: JWT (use "username" = email, "password"); refresh with "refresh" token
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/register/", RegisterView.as_view(), name="register"),
    path("api/ingestion/", include("apps.ingestion.urls")),
    path("api/tracking/", include("apps.accounts.urls")),
    path("api/", include(router.urls)),
]
