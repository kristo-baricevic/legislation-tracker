import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.changelog.models import ChangeLog
from apps.congress.models import Representative
from apps.accounts.models import TrackedTopic
from apps.legislation.models import Bill, BillTopic, Topic


def make_user(email="user@example.com"):
    return get_user_model().objects.create_user(
        username=email,
        email=email,
        password="password",
    )


def authenticated_client(user=None):
    client = APIClient()
    client.force_authenticate(user=user or make_user())
    return client


def make_bill(**overrides):
    defaults = {
        "jurisdiction": "federal",
        "session": 119,
        "bill_number": "HR 100",
        "title": "A test bill",
        "status": "introduced",
    }
    defaults.update(overrides)
    return Bill.objects.create(**defaults)


def make_representative(**overrides):
    defaults = {
        "bioguide_id": "A000001",
        "name": "Test Representative",
        "chamber": "house",
        "party": "Independent",
        "state": "NY",
    }
    defaults.update(overrides)
    return Representative.objects.create(**defaults)


@pytest.mark.django_db
def test_tracking_summary_requires_authentication():
    response = APIClient().get("/api/tracking/")

    assert response.status_code in (401, 403)


@pytest.mark.django_db
def test_user_can_track_and_untrack_bill_idempotently():
    bill = make_bill()
    client = authenticated_client()

    created = client.post("/api/tracking/bills/", {"bill": bill.id}, format="json")
    duplicate = client.post("/api/tracking/bills/", {"bill": bill.id}, format="json")
    summary = client.get("/api/tracking/")
    deleted = client.delete(f"/api/tracking/bills/{bill.id}/")
    after_delete = client.get("/api/tracking/")

    assert created.status_code == 201
    assert duplicate.status_code == 200
    assert created.json()["bill"]["id"] == bill.id
    assert duplicate.json()["bill"]["id"] == bill.id
    assert [item["bill"]["id"] for item in summary.json()["bills"]] == [bill.id]
    assert deleted.status_code == 204
    assert after_delete.json()["bills"] == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("path", "payload", "field"),
    [
        ("/api/tracking/bills/", {}, "bill"),
        ("/api/tracking/topics/", {}, "topic"),
        ("/api/tracking/legislators/", {}, "representative"),
    ],
)
def test_tracking_create_requires_target_id(path, payload, field):
    response = authenticated_client().post(path, payload, format="json")

    assert response.status_code == 400
    assert response.json() == {"error": f"{field} is required"}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("path", "payload", "field"),
    [
        ("/api/tracking/bills/", {"bill": "bad"}, "bill"),
        ("/api/tracking/topics/", {"topic": "bad"}, "topic"),
        ("/api/tracking/legislators/", {"representative": "bad"}, "representative"),
    ],
)
def test_tracking_create_validates_target_id_type(path, payload, field):
    response = authenticated_client().post(path, payload, format="json")

    assert response.status_code == 400
    assert response.json() == {"error": f"{field} must be an integer"}


@pytest.mark.django_db
def test_tracking_summary_includes_topics_and_legislators_for_current_user_only():
    user = make_user("owner@example.com")
    other_user = make_user("other@example.com")
    topic = Topic.objects.create(name="Health", slug="health")
    other_topic = Topic.objects.create(name="Tax", slug="tax")
    representative = make_representative()
    other_representative = make_representative(
        bioguide_id="B000002",
        name="Other Representative",
        state="CA",
    )

    client = authenticated_client(user)
    other_client = authenticated_client(other_user)

    assert client.post("/api/tracking/topics/", {"topic": topic.id}, format="json").status_code == 201
    assert client.post(
        "/api/tracking/legislators/",
        {"representative": representative.id},
        format="json",
    ).status_code == 201
    assert other_client.post(
        "/api/tracking/topics/",
        {"topic": other_topic.id},
        format="json",
    ).status_code == 201
    assert other_client.post(
        "/api/tracking/legislators/",
        {"representative": other_representative.id},
        format="json",
    ).status_code == 201

    summary = client.get("/api/tracking/")

    assert summary.status_code == 200
    assert [item["topic"]["id"] for item in summary.json()["topics"]] == [topic.id]
    assert [item["representative"]["id"] for item in summary.json()["legislators"]] == [
        representative.id
    ]
    assert summary.json()["is_staff"] is False


@pytest.mark.django_db
def test_tracking_topics_collection_lists_the_current_users_followed_topics():
    user = make_user("follower@example.com")
    client = authenticated_client(user)
    topic = Topic.objects.create(name="Health", slug="health")

    created = client.post(
        "/api/tracking/topics/", {"topic": topic.id}, format="json"
    )
    listed = client.get("/api/tracking/topics/")

    assert created.status_code == 201
    assert listed.status_code == 200
    assert [item["topic"]["id"] for item in listed.json()] == [topic.id]
    assert TrackedTopic.objects.filter(user=user, topic=topic).exists()


@pytest.mark.django_db
def test_legacy_preference_topic_endpoints_cannot_change_topic_tracking():
    user = make_user("legacy-topic@example.com")
    client = authenticated_client(user)
    topic = Topic.objects.create(name="Education", slug="education")

    assert client.get("/api/preferences/followed-topics/").status_code in (404, 405)
    assert client.post(
        "/api/preferences/follow-topic/", {"topic_id": topic.id}, format="json"
    ).status_code in (404, 405)
    assert client.post(
        "/api/preferences/unfollow-topic/", {"topic_id": topic.id}, format="json"
    ).status_code in (404, 405)
    assert not TrackedTopic.objects.filter(user=user, topic=topic).exists()


@pytest.mark.django_db
def test_generic_preferences_endpoint_rejects_topic_rows():
    user = make_user("preferences@example.com")
    client = authenticated_client(user)
    topic = Topic.objects.create(name="Education", slug="education")

    response = client.post("/api/preferences/", {"topic": topic.id}, format="json")

    assert response.status_code == 400
    assert response.json() == {
        "error": "Use the topic tracking endpoints to follow topics."
    }
    assert not TrackedTopic.objects.filter(user=user, topic=topic).exists()


@pytest.mark.django_db
def test_tracking_feed_includes_direct_topic_and_legislator_matches_for_current_user_only():
    user = make_user("owner@example.com")
    other_user = make_user("other@example.com")
    topic = Topic.objects.create(name="Health", slug="health")
    other_topic = Topic.objects.create(name="Tax", slug="tax")
    representative = make_representative()
    other_representative = make_representative(
        bioguide_id="B000002",
        name="Other Representative",
        state="CA",
    )
    direct_bill = make_bill(bill_number="HR 101", title="Direct tracked bill")
    topic_bill = make_bill(bill_number="HR 102", title="Topic matched bill")
    legislator_bill = make_bill(
        bill_number="HR 103",
        title="Legislator matched bill",
        sponsor=representative,
    )
    other_user_bill = make_bill(
        bill_number="HR 104",
        title="Other user's tracked bill",
        sponsor=other_representative,
    )
    unrelated_bill = make_bill(bill_number="HR 105", title="Unrelated bill")
    BillTopic.objects.create(bill=topic_bill, topic=topic)
    BillTopic.objects.create(bill=other_user_bill, topic=other_topic)

    client = authenticated_client(user)
    other_client = authenticated_client(other_user)

    assert client.post("/api/tracking/bills/", {"bill": direct_bill.id}, format="json").status_code == 201
    assert client.post("/api/tracking/topics/", {"topic": topic.id}, format="json").status_code == 201
    assert client.post(
        "/api/tracking/legislators/",
        {"representative": representative.id},
        format="json",
    ).status_code == 201
    assert other_client.post(
        "/api/tracking/bills/",
        {"bill": other_user_bill.id},
        format="json",
    ).status_code == 201
    assert other_client.post(
        "/api/tracking/topics/",
        {"topic": other_topic.id},
        format="json",
    ).status_code == 201
    assert other_client.post(
        "/api/tracking/legislators/",
        {"representative": other_representative.id},
        format="json",
    ).status_code == 201

    for bill in [
        direct_bill,
        topic_bill,
        legislator_bill,
        other_user_bill,
        unrelated_bill,
    ]:
        ChangeLog.objects.create(
            bill=bill,
            change_type="status_update",
            old_value={"status": "introduced"},
            new_value={"status": "reported"},
        )

    response = client.get("/api/tracking/feed/")

    assert response.status_code == 200
    entries = response.json()["entries"]
    assert {entry["bill"]["id"] for entry in entries} == {
        direct_bill.id,
        topic_bill.id,
        legislator_bill.id,
    }
    assert all(entry["change_type"] == "status_update" for entry in entries)
    assert all("created_at" in entry for entry in entries)
