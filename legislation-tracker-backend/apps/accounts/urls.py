from django.urls import path

from .views import (
    TrackingFeedView,
    TrackedBillDetailView,
    TrackedBillView,
    TrackedLegislatorDetailView,
    TrackedLegislatorView,
    TrackedTopicDetailView,
    TrackedTopicView,
    TrackingSummaryView,
)

urlpatterns = [
    path("", TrackingSummaryView.as_view(), name="tracking-summary"),
    path("feed/", TrackingFeedView.as_view(), name="tracking-feed"),
    path("bills/", TrackedBillView.as_view(), name="track-bill"),
    path("bills/<int:bill_id>/", TrackedBillDetailView.as_view(), name="untrack-bill"),
    path("topics/", TrackedTopicView.as_view(), name="track-topic"),
    path("topics/<int:topic_id>/", TrackedTopicDetailView.as_view(), name="untrack-topic"),
    path("legislators/", TrackedLegislatorView.as_view(), name="track-legislator"),
    path(
        "legislators/<int:representative_id>/",
        TrackedLegislatorDetailView.as_view(),
        name="untrack-legislator",
    ),
]
