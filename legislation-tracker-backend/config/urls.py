"""
URL configuration for config project.
"""

from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.accounts.llm_views import (
    LLMSettingsValidateView,
    LLMSettingsView,
    PublicCapabilitiesView,
)
from apps.accounts.views import RegisterView, UserPreferenceViewSet
from apps.congress.views import RepresentativeViewSet, VoteViewSet
from apps.legislation.enhancements.views import (
    BillEnhancementDetailView,
    BillEnhancementEstimateView,
    BillEnhancementLatestView,
    BillEnhancementListCreateView,
    BillEnhancementRetryView,
)
from apps.legislation.views import (
    BillContractViewSet,
    BillDocumentViewSet,
    BillViewSet,
    TopicViewSet,
)
from config import health

router = DefaultRouter()
router.register(r"bills", BillViewSet, basename="bill")
router.register(r"documents", BillDocumentViewSet, basename="document")
router.register(r"contracts", BillContractViewSet, basename="contract")
router.register(r"topics", TopicViewSet, basename="topic")
router.register(r"representatives", RepresentativeViewSet, basename="representative")
router.register(r"votes", VoteViewSet, basename="vote")
router.register(r"preferences", UserPreferenceViewSet, basename="preference")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/live/", health.live, name="health-live"),
    path("health/", health.ready, name="health-ready"),
    # Auth: JWT (use "username" = email, "password"); refresh with "refresh" token
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/register/", RegisterView.as_view(), name="register"),
    path("api/capabilities/", PublicCapabilitiesView.as_view(), name="capabilities"),
    path("api/settings/llm/", LLMSettingsView.as_view(), name="llm-settings"),
    path(
        "api/settings/llm/validate/",
        LLMSettingsValidateView.as_view(),
        name="llm-settings-validate",
    ),
    path("api/ingestion/", include("apps.ingestion.urls")),
    path(
        "api/bills/<int:bill_id>/enhancements/estimate/",
        BillEnhancementEstimateView.as_view(),
        name="bill-enhancement-estimate",
    ),
    path(
        "api/bills/<int:bill_id>/enhancements/latest/",
        BillEnhancementLatestView.as_view(),
        name="bill-enhancement-latest",
    ),
    path(
        "api/bills/<int:bill_id>/enhancements/<int:enhancement_id>/retry/",
        BillEnhancementRetryView.as_view(),
        name="bill-enhancement-retry",
    ),
    path(
        "api/bills/<int:bill_id>/enhancements/<int:enhancement_id>/",
        BillEnhancementDetailView.as_view(),
        name="bill-enhancement-detail",
    ),
    path(
        "api/bills/<int:bill_id>/enhancements/",
        BillEnhancementListCreateView.as_view(),
        name="bill-enhancement-list",
    ),
    path("api/tracking/", include("apps.accounts.urls")),
    path("api/", include(router.urls)),
]
