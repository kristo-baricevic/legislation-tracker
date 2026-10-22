import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.congress.models import Representative

pytestmark = pytest.mark.django_db


@pytest.fixture
def rep():
    return Representative.objects.create(bioguide_id="T000004", name="Test", chamber="house", state="NY")


def test_public_research_read_is_empty_not_network_fetch(rep):
    response = APIClient().get(f"/api/representatives/{rep.pk}/research/")
    assert response.status_code == 200
    assert response.data["status"] == "not_started"
    assert response.data["biography"] is None


def test_research_write_requires_authentication(rep):
    assert APIClient().post(f"/api/representatives/{rep.pk}/research/", {"period": 2026}).status_code in (401, 403)


def test_signed_in_nonstaff_can_start_and_join_research(rep):
    client = APIClient()
    client.force_authenticate(get_user_model().objects.create_user(username="reader", password="test"))
    first = client.post(f"/api/representatives/{rep.pk}/research/", {"period": 2026}, format="json")
    assert first.status_code == 202
    second = client.post(f"/api/representatives/{rep.pk}/research/", {"period": 2026}, format="json")
    assert second.data["id"] == first.data["id"]
    assert client.get(f"/api/representatives/{rep.pk}/research-runs/{first.data['id']}/").status_code == 200


def test_unknown_parameters_are_rejected(rep):
    client = APIClient()
    client.force_authenticate(get_user_model().objects.create_user(username="reader", password="test"))
    assert client.post(f"/api/representatives/{rep.pk}/research/", {"period": 2026, "url": "http://localhost"}, format="json").status_code == 400
    assert client.get(f"/api/representatives/{rep.pk}/contributors/?period=2025").status_code == 400


def test_worker_without_fec_key_still_saves_biography(rep, settings):
    from apps.research.services import request_research
    from apps.research.tasks import process_research
    from apps.research.models import RepresentativeBiography
    settings.FEC_API_KEY = ""
    user = get_user_model().objects.create_user(username="reader")
    run = request_research(rep.pk, 2026, user.pk)
    work = run.work_item
    work.status = "processing"
    work.dispatch_token = "test-token"
    from django.utils import timezone
    from datetime import timedelta
    work.lease_expires_at = timezone.now() + timedelta(minutes=5)
    work.save()
    # Sources with no configured network access still produce official facts.
    settings.CONGRESS_API_KEY = ""
    settings.LEGISLATOR_WIKIPEDIA_ENABLED = False
    process_research(work)
    run.refresh_from_db()
    assert RepresentativeBiography.objects.filter(representative=rep).exists()
    assert run.status == "partial"
    assert run.sections["finance"]["reason"] == "missing_fec_key"


def test_expired_worker_cannot_publish(rep, settings):
    from apps.research.services import request_research
    from apps.research.tasks import process_research
    from apps.research.models import RepresentativeBiography
    user = get_user_model().objects.create_user(username="reader")
    run = request_research(rep.pk, 2026, user.pk)
    work = run.work_item
    work.status = "processing"
    work.dispatch_token = "old"
    work.save()
    type(work).objects.filter(pk=work.pk).update(dispatch_token="new")
    settings.CONGRESS_API_KEY = ""
    settings.LEGISLATOR_WIKIPEDIA_ENABLED = False
    process_research(work)
    assert not RepresentativeBiography.objects.filter(representative=rep).exists()


def test_legacy_biography_get_never_runs_research(rep, monkeypatch):
    monkeypatch.setattr("apps.congress.views.representative_biography", lambda *args: (_ for _ in ()).throw(AssertionError("unexpected network research")))
    response = APIClient().get(f"/api/representatives/{rep.pk}/biography/")
    assert response.status_code == 200
    assert response.data["reason"] == "not_researched"


def test_expired_lease_with_same_token_is_fenced(rep):
    from apps.research.services import request_research
    from apps.research.tasks import fenced_work
    from django.utils import timezone
    from datetime import timedelta
    run = request_research(rep.pk, 2026, get_user_model().objects.create_user(username="reader").pk)
    work = run.work_item
    work.status = "processing"
    work.dispatch_token = "unchanged"
    work.lease_expires_at = timezone.now() - timedelta(seconds=1)
    work.save()
    assert fenced_work(work) is None


def test_research_queue_cannot_exhaust_bill_dispatch_capacity(monkeypatch):
    from apps.ingestion import tasks
    from apps.ingestion.models import IngestionWorkItem
    from types import SimpleNamespace
    from django.utils import timezone
    IngestionWorkItem.objects.bulk_create([
        IngestionWorkItem(kind="representative_research", dedupe_key=str(i),
                          status="dispatched", source_updated_at=timezone.now())
        for i in range(tasks.MAX_DISPATCHED_INGESTION_WORK)
    ])
    bill = IngestionWorkItem.objects.create(kind="bill", dedupe_key="119-hr-1", source_updated_at=timezone.now())
    monkeypatch.setattr(tasks.process_ingestion_work_item, "apply_async", lambda **kwargs: SimpleNamespace(id="test"))
    assert tasks.dispatch_ingestion_work()["dispatched"] == 1
    bill.refresh_from_db()
    assert bill.status == "dispatched"
