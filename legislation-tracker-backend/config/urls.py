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
from apps.accounts.throttles import LoginThrottle, RefreshThrottle
from apps.accounts.views import (
    CSRFTokenView,
    RegisterView,
    SavedBillSearchViewSet,
    SessionLoginView,
    SessionLogoutView,
    SessionRefreshView,
    SessionStatusView,
    UserPreferenceViewSet,
)
from apps.changelog.views import BillChangeAcknowledgeView, BillChangeTimelineView
from apps.congress.views import CommitteeViewSet, RepresentativeViewSet, VoteViewSet
from apps.legislation.comparison_views import (
    BillContractComparisonView,
    BillDocumentComparisonView,
    BillDocumentSectionComparisonView,
)
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
router.register(r"committees", CommitteeViewSet, basename="committee")
router.register(r"preferences", UserPreferenceViewSet, basename="preference")
router.register(r"saved-searches", SavedBillSearchViewSet, basename="saved-search")


class ExtensionTokenObtainPairView(TokenObtainPairView):
    throttle_classes = [LoginThrottle]


class ExtensionTokenRefreshView(TokenRefreshView):
    throttle_classes = [RefreshThrottle]


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/live/", health.live, name="health-live"),
    path("health/", health.ready, name="health-ready"),
    # Auth: JWT (use "username" = email, "password"); refresh with "refresh" token
    path(
        "api/auth/token/",
        ExtensionTokenObtainPairView.as_view(),
        name="token_obtain_pair",
    ),
    path(
        "api/auth/token/refresh/",
        ExtensionTokenRefreshView.as_view(),
        name="token_refresh",
    ),
    path("api/auth/register/", RegisterView.as_view(), name="register"),
    path("api/auth/csrf/", CSRFTokenView.as_view(), name="csrf_token"),
    path("api/auth/session/", SessionLoginView.as_view(), name="session_login"),
    path(
        "api/auth/session/current/", SessionStatusView.as_view(), name="session_status"
    ),
    path(
        "api/auth/session/refresh/",
        SessionRefreshView.as_view(),
        name="session_refresh",
    ),
    path(
        "api/auth/session/logout/",
        SessionLogoutView.as_view(),
        name="session_logout",
    ),
    path("api/capabilities/", PublicCapabilitiesView.as_view(), name="capabilities"),
    path("api/settings/llm/", LLMSettingsView.as_view(), name="llm-settings"),
    path(
        "api/settings/llm/validate/",
        LLMSettingsValidateView.as_view(),
        name="llm-settings-validate",
    ),
    path("api/ingestion/", include("apps.ingestion.urls")),
    path(
        "api/bills/<int:bill_id>/changes/",
        BillChangeTimelineView.as_view(),
        name="bill-change-timeline",
    ),
    path(
        "api/bills/<int:bill_id>/changes/acknowledge/",
        BillChangeAcknowledgeView.as_view(),
        name="bill-change-acknowledge",
    ),
    path(
        "api/bills/<int:bill_id>/comparisons/contracts/",
        BillContractComparisonView.as_view(),
        name="bill-contract-comparison",
    ),
    path(
        "api/bills/<int:bill_id>/comparisons/documents/",
        BillDocumentComparisonView.as_view(),
        name="bill-document-comparison",
    ),
    path(
        "api/bills/<int:bill_id>/comparisons/documents/section/",
        BillDocumentSectionComparisonView.as_view(),
        name="bill-document-section-comparison",
    ),
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
