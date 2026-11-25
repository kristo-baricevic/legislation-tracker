import pytest

from apps.ingestion.models import IngestionRun, IngestionWorkItem
from apps.ingestion.tests.test_views import authenticated_client


@pytest.mark.django_db
@pytest.mark.parametrize("is_staff", [False, True])
@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "telemetry"),
        ("get", "source-readiness"),
        ("post", "poll-congress"),
    ],
)
def test_dashboard_denies_non_superusers(is_staff, method, path):
    client = authenticated_client(is_staff=is_staff)
    response = getattr(client, method)(f"/api/ingestion/{path}/")
    assert response.status_code == 403
    assert not IngestionRun.objects.exists()
    assert not IngestionWorkItem.objects.exists()
