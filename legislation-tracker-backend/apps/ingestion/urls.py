from django.urls import path

from apps.ingestion.views import (
    BackfillDocumentsView,
    BackfillTopicsView,
    IngestBillView,
    PollCongressView,
)


urlpatterns = [
    path("bills/", IngestBillView.as_view(), name="ingest-bill"),
    path("poll-congress/", PollCongressView.as_view(), name="poll-congress"),
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
