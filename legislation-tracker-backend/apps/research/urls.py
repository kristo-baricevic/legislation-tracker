from django.urls import path
from .views import ResearchView, ResearchRunView, ContributorsView, ConnectionsView

urlpatterns = [
    path("<int:representative_id>/research/", ResearchView.as_view()),
    path("<int:representative_id>/research-runs/<uuid:run_id>/", ResearchRunView.as_view()),
    path("<int:representative_id>/contributors/", ContributorsView.as_view()),
    path("<int:representative_id>/connections/", ConnectionsView.as_view()),
]
