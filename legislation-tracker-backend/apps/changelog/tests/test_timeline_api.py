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
