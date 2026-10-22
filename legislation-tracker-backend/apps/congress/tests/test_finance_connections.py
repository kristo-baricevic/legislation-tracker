import pytest
from rest_framework.test import APIClient
from apps.congress.models import Representative
from apps.legislation.models import Bill, Topic, BillTopic

pytestmark = pytest.mark.django_db


def test_connections_preserve_bill_evidence_without_donor_endorsement():
    rep = Representative.objects.create(bioguide_id="T000001", name="Test", chamber="house", state="NY")
    bill = Bill.objects.create(bill_number="HR 1", session=119, title="Test Bill", jurisdiction="federal", sponsor=rep, introduced_at="2026-01-01")
    topic, _ = Topic.objects.get_or_create(name="Education", slug="education")
    BillTopic.objects.create(bill=bill, topic=topic)
    response = APIClient().get(f"/api/representatives/{rep.pk}/connections/?period=2026")
    assert response.status_code == 200
    assert response.data["bills"][0]["id"] == bill.pk
    assert response.data["bills"][0]["relations"] == ["Sponsored"]
    assert response.data["bills"][0]["topics"][0]["id"] == topic.pk
    assert response.data["finance_status"] == "not_researched"
    assert "does not establish donor endorsement" in response.data["notice"]


def test_shared_committee_donor_connects_only_published_same_period_representatives():
    from django.contrib.auth import get_user_model
    from apps.research.services import request_research
    from apps.campaign_finance.models import Contributor, ContributorIdentity, CampaignCommittee, FinanceSnapshot, FinanceTransaction
    user = get_user_model().objects.create_user(username="research")
    donor = Contributor.objects.create(name="Example PAC", kind="committee")
    ContributorIdentity.objects.create(contributor=donor, provider_key="fec:C00000001", verified=True)
    reps = []
    for n in (1, 2):
        rep = Representative.objects.create(bioguide_id=f"T00000{n}", name=f"Member {n}", chamber="house", state="NY")
        reps.append(rep)
        run = request_research(rep.pk, 2026, user.pk)
        snapshot = FinanceSnapshot.objects.create(run=run, representative=rep, period=2026, active=True)
        committee = CampaignCommittee.objects.create(fec_id=f"C0000000{n+1}", name=f"Campaign {n}")
        FinanceTransaction.objects.create(snapshot=snapshot, committee=committee, contributor=donor, source_key=str(n), amount=100, kind="contribution", source_url="https://www.fec.gov/")
    response = APIClient().get(f"/api/representatives/{reps[0].pk}/connections/?period=2026&contributor={donor.pk}")
    assert response.status_code == 200
    assert {item["id"] for item in response.data["related_representatives"]} == {rep.pk for rep in reps}
    from decimal import Decimal
    assert Decimal(response.data["donors"][0]["amount"]) == Decimal("100")
    response = APIClient().get(f"/api/representatives/{reps[0].pk}/connections/?period=2026&contributor={donor.pk}&related_cursor=1")
    assert response.status_code == 200
    assert response.data["related_count"] == 2
    assert [item["id"] for item in response.data["related_representatives"]] == [reps[1].pk]
