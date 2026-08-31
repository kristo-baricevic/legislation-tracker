import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.changelog.models import ChangeLog
from apps.legislation.models import Bill


@pytest.mark.django_db
def test_bill_timeline_is_public_and_acknowledges_only_an_explicit_cursor():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 907",
        title="Timeline bill",
        status="Introduced",
    )
    ChangeLog.objects.create(
        bill=bill,
        change_type="status_update",
        old_value={"status": "Introduced"},
        new_value={"status": "Reported"},
    )
    user = User.objects.create_user(
        username="timeline@example.test",
        email="timeline@example.test",
        password="safe-password-123",
    )
    anonymous = APIClient()
    signed_in = APIClient()
    signed_in.force_authenticate(user)

    public = anonymous.get(f"/api/bills/{bill.id}/changes/")
    personalized = signed_in.get(f"/api/bills/{bill.id}/changes/")
    acknowledged = signed_in.post(
        f"/api/bills/{bill.id}/changes/acknowledge/",
        {"cursor": personalized.json()["page_end_cursor"]},
        format="json",
    )

    assert public.status_code == 200
    assert public.json()["personalized"] is False
    assert public.json()["unread_count"] is None
    assert personalized.json()["personalized"] is True
    assert acknowledged.status_code == 200
    assert acknowledged.json()["unread_count"] == 0


@pytest.mark.django_db
def test_initial_truncated_timeline_does_not_issue_an_acknowledgement_cursor():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 908",
        title="Long timeline bill",
        status="Introduced",
    )
    for index in range(21):
        ChangeLog.objects.create(
            bill=bill,
            change_type="status_update",
            old_value={"status": f"Before {index}"},
            new_value={"status": f"After {index}"},
        )
    user = User.objects.create_user(
        username="truncated-timeline@example.test",
        email="truncated-timeline@example.test",
        password="safe-password-123",
    )
    client = APIClient()
    client.force_authenticate(user)

    response = client.get(f"/api/bills/{bill.id}/changes/?page_size=20")

    assert response.status_code == 200
    assert len(response.json()["results"]) == 20
    assert response.json()["initial_window_truncated"] is True
    assert response.json()["page_end_cursor"] is None
    assert response.json()["unread_count"] == 21


@pytest.mark.django_db
def test_timeline_can_acknowledge_a_signed_stream_head_after_browsing_history():
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 909",
        title="Browsable timeline bill",
        status="Introduced",
    )
    for index in range(2):
        ChangeLog.objects.create(
            bill=bill,
            change_type="status_update",
            new_value={"status": f"After {index}"},
        )
    user = User.objects.create_user(
        username="browse-timeline@example.test",
        email="browse-timeline@example.test",
        password="safe-password-123",
    )
    client = APIClient()
    client.force_authenticate(user)

    timeline = client.get(f"/api/bills/{bill.id}/changes/")
    response = client.post(
        f"/api/bills/{bill.id}/changes/acknowledge/",
        {"cursor": timeline.json()["stream_head_cursor"]},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["unread_count"] == 0
