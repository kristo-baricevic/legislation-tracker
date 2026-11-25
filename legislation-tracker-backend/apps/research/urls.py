from django.urls import path

from .views import (
    ConfirmCandidateView,
    ConnectionsView,
    ContributorsView,
    OutsideSpendingView,
    PortraitView,
    ResearchRunView,
    ResearchView,
    SnapshotsView,
)

urlpatterns = [
    path("<int:representative_id>/research/", ResearchView.as_view()),
    path(
        "<int:representative_id>/portraits/<int:portrait_id>/", PortraitView.as_view()
    ),
    path("<int:representative_id>/research-snapshots/", SnapshotsView.as_view()),
    path(
        "<int:representative_id>/research-runs/<uuid:run_id>/confirm-candidate/",
        ConfirmCandidateView.as_view(),
    ),
    path(
        "<int:representative_id>/research-runs/<uuid:run_id>/",
        ResearchRunView.as_view(),
    ),
    path("<int:representative_id>/contributors/", ContributorsView.as_view()),
    path("<int:representative_id>/outside-spending/", OutsideSpendingView.as_view()),
    path("<int:representative_id>/connections/", ConnectionsView.as_view()),
]
