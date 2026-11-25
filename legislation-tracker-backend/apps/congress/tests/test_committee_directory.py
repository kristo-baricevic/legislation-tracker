import pytest
from rest_framework.test import APIClient

from apps.congress.models import Committee, CommitteeMembership, Representative
from apps.legislation.models import Bill

pytestmark = pytest.mark.django_db


def test_same_named_committees_have_a_unique_pagination_order():
    from apps.congress.views import CommitteeViewSet

    # Subcommittees can share a name; the last ordering field must break ties.
    assert CommitteeViewSet.queryset.query.order_by == ("chamber", "name", "id")
    committees = [
        Committee.objects.create(
            system_code=f"same{i}", name="Oversight", chamber="house"
        )
        for i in range(3)
    ]
    client = APIClient()
    first = client.get("/api/committees/?page_size=2").data
    second = client.get("/api/committees/?page_size=2&page=2").data
    assert [row["id"] for row in first["results"] + second["results"]] == [
        committee.pk for committee in committees
    ]


def test_directory_scopes_members_and_bills():
    committee = Committee.objects.create(
        system_code="ssfi", name="Finance", chamber="senate"
    )
    Committee.objects.create(system_code="hsfi", name="House Finance", chamber="house")
    member = Representative.objects.create(
        bioguide_id="A000001", name="Jane Doe", chamber="senate"
    )
    old = Representative.objects.create(bioguide_id="A000002", name="Former Member")
    for rep, congress in [(member, 119), (old, 118)]:
        CommitteeMembership.objects.create(
            committee=committee,
            representative=rep,
            congress=congress,
            role="chair",
            source_name="test",
            source_code="test",
        )
    for num, rep, congress in [(1, member, 119), (2, member, 118), (3, old, 119)]:
        Bill.objects.create(
            jurisdiction="federal",
            session=congress,
            bill_number=f"S {num}",
            sponsor=rep,
            title=f"Bill {num}",
            summary="A short summary",
        )
    client = APIClient()
    response = client.get("/api/committees/?congress=119&chamber=senate")
    assert response.status_code == 200
    assert response.data["count"] == 1
    row = response.data["results"][0]
    assert row["members"][0]["representative"]["id"] == member.pk
    assert row["members"][0]["role"] == "chair"
    assert len(row["members"]) == 1
    bills = client.get(f"/api/committees/{committee.pk}/introduced-bills/?congress=119")
    assert bills.status_code == 200
    assert [b["bill_number"] for b in bills.data["results"]] == ["S 1"]
    assert bills.data["results"][0]["card_summary"] == "A short summary"


def test_committee_query_validation():
    assert APIClient().get("/api/committees/?chamber=invalid").status_code == 400


def test_topic_filters_committees_and_their_bill_rows_within_congress():
    from apps.legislation.models import BillTopic, Topic

    topic, _ = Topic.objects.get_or_create(
        slug="education", defaults={"name": "Education"}
    )
    rep = Representative.objects.create(bioguide_id="T000001", name="Test Member")
    committee = Committee.objects.create(
        system_code="topic", name="Education committee", chamber="house"
    )
    Committee.objects.create(system_code="empty", name="Empty", chamber="house")
    CommitteeMembership.objects.create(
        committee=committee,
        representative=rep,
        congress=119,
        source_name="test",
        source_code="test",
    )
    bill = Bill.objects.create(
        jurisdiction="federal", session=119, bill_number="HR 10", sponsor=rep
    )
    Bill.objects.create(
        jurisdiction="federal", session=119, bill_number="HR 11", sponsor=rep
    )
    BillTopic.objects.create(bill=bill, topic=topic)
    client = APIClient()
    query = f"?congress=119&topic_id={topic.pk}"
    response = client.get("/api/committees/" + query)
    assert response.status_code == 200
    assert [r["id"] for r in response.data["results"]] == [committee.pk]
    response = client.get(f"/api/committees/{committee.pk}/introduced-bills/" + query)
    assert [r["id"] for r in response.data["results"]] == [bill.pk]
    bill.session = 118
    bill.save()
    assert client.get("/api/committees/" + query).data["count"] == 0


def test_directory_searches_all_records_and_preserves_full_roster():
    parent = Committee.objects.create(
        system_code="finance", name="Finance", chamber="senate"
    )
    child = Committee.objects.create(
        system_code="tax", name="Taxation", chamber="senate", parent=parent
    )
    other = Committee.objects.create(system_code="other", name="Other", chamber="house")
    jane = Representative.objects.create(bioguide_id="A000011", name="Doe, Jane")
    john = Representative.objects.create(bioguide_id="A000012", name="Smith, John")
    for committee, rep, congress in [
        (child, jane, 119),
        (child, john, 119),
        (other, jane, 118),
    ]:
        CommitteeMembership.objects.create(
            committee=committee,
            representative=rep,
            congress=congress,
            source_name="test",
            source_code="test",
        )
    client = APIClient()
    result = client.get(
        "/api/committees/?congress=119&search=tax&member=Jane%20Doe&level=subcommittee"
    )
    assert result.status_code == 200
    assert [row["id"] for row in result.data["results"]] == [child.pk]
    assert len(result.data["results"][0]["members"]) == 2
    assert (
        client.get("/api/committees/?search=Finance&level=committee").data["count"] == 1
    )
    assert (
        client.get("/api/committees/?congress=119&member=Jane&chamber=house").data[
            "count"
        ]
        == 0
    )
    assert client.get("/api/committees/?level=bad").status_code == 400


def test_introduced_bills_pages_are_distinct_and_exclude_cosponsorships():
    from apps.congress.models import BillCosponsor

    committee = Committee.objects.create(
        system_code="test", name="Test", chamber="house"
    )
    member = Representative.objects.create(bioguide_id="A000003", name="Member")
    CommitteeMembership.objects.create(
        committee=committee,
        representative=member,
        congress=119,
        source_name="test",
        source_code="test",
    )
    bills = [
        Bill.objects.create(
            jurisdiction="federal", session=119, bill_number=f"HR {i}", sponsor=member
        )
        for i in range(3)
    ]
    other = Bill.objects.create(
        jurisdiction="federal", session=119, bill_number="HR 99"
    )
    BillCosponsor.objects.create(bill=other, representative=member)
    client = APIClient()
    path = f"/api/committees/{committee.pk}/introduced-bills/?congress=119&page_size=2"
    first = client.get(path).data
    second = client.get(path + "&page=2").data
    ids = [b["id"] for b in first["results"] + second["results"]]
    assert ids == [b.pk for b in reversed(bills)]
    assert first["next"] and second["next"] is None
