from django.urls import path

from apps.ingestion.views import (
    BackfillDocumentsView,
    BackfillTopicsView,
    IngestBillView,
    IngestionFailureListView,
    PollCongressView,
    ReplayIngestionFailureView,
    SyncRepresentativesView,
)


urlpatterns = [
    path("bills/", IngestBillView.as_view(), name="ingest-bill"),
    path("poll-congress/", PollCongressView.as_view(), name="poll-congress"),
    path(
        "sync-representatives/",
        SyncRepresentativesView.as_view(),
        name="sync-representatives",
    ),
    path("failures/", IngestionFailureListView.as_view(), name="ingestion-failures"),
    path(
        "failures/<int:failure_id>/replay/",
        ReplayIngestionFailureView.as_view(),
        name="replay-ingestion-failure",
    ),
    path(
        "backfill-documents/",
        BackfillDocumentsView.as_view(),
        name="backfill-documents",
    ),
    path(
        "backfill-topics/",
        BackfillTopicsView.as_view(),
        name="backfill-topics",
    ),
]
