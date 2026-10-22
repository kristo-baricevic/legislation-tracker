import pytest
from decimal import Decimal
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


def test_historical_connections_use_selected_snapshot_and_separate_activity_dates():
    from django.utils import timezone
    from datetime import timedelta
    from apps.research.models import ResearchRun
    from apps.campaign_finance.models import Contributor, ContributorIdentity, CampaignCommittee, FinanceSnapshot, FinanceTransaction
    rep = Representative.objects.create(bioguide_id="T000011", name="Test", chamber="house", state="NY")
    donor = Contributor.objects.create(name="Historical PAC", kind="committee")
    ContributorIdentity.objects.create(contributor=donor, provider_key="fec:C00000002", verified=True)
    committee = CampaignCommittee.objects.create(fec_id="C00000001", name="Campaign")
    old = FinanceSnapshot.objects.create(representative=rep, period=2026, run=ResearchRun.objects.create(representative=rep, period=2026, status="partial"), published_at=timezone.now() - timedelta(days=1))
    current = FinanceSnapshot.objects.create(representative=rep, period=2026, run=ResearchRun.objects.create(representative=rep, period=2026, status="partial"), published_at=timezone.now(), active=True)
    for snapshot, amount in [(old, 100), (current, 150)]:
        FinanceTransaction.objects.create(snapshot=snapshot, contributor=donor, committee=committee, amount=amount, kind="contribution", source_key="1", source_url="https://www.fec.gov/")
    bill = Bill.objects.create(bill_number="HR 2", session=118, title="Earlier Bill", jurisdiction="federal", sponsor=rep, introduced_at="2024-01-01")
    url = f"/api/representatives/{rep.pk}/connections/?period=2026&snapshot={old.pk}&legislative_start=2024-01-01&legislative_end=2024-12-31"
    result = APIClient().get(url)
    assert result.status_code == 200
    assert Decimal(result.data["donors"][0]["amount"]) == Decimal("100")
    assert result.data["snapshot"] == str(old.pk)
    assert [row["id"] for row in result.data["bills"]] == [bill.pk]
    history_url = f"/api/representatives/{rep.pk}/research-snapshots/?period=2026"
    history = APIClient().get(history_url)
    assert history.status_code == 200
    assert [row["id"] for row in history.data["results"]] == [str(current.pk), str(old.pk)]
    old.invalidated = True
    old.save()
    assert APIClient().get(url).status_code == 404
    assert [row["id"] for row in APIClient().get(history_url).data["results"]] == [str(current.pk)]


def test_historical_shared_donors_never_include_newer_finance_or_repeated_snapshots():
    from django.utils import timezone
    from datetime import timedelta
    from apps.research.models import ResearchRun
    from apps.campaign_finance.models import Contributor, ContributorIdentity, CampaignCommittee, FinanceSnapshot, FinanceTransaction
    now = timezone.now()
    root = Representative.objects.create(bioguide_id="T000021", name="Root", chamber="house", state="NY")
    other = Representative.objects.create(bioguide_id="T000022", name="Other", chamber="house", state="NY")
    donor = Contributor.objects.create(name="PAC", kind="committee")
    ContributorIdentity.objects.create(contributor=donor, provider_key="fec:C00000002", verified=True)
    committee = CampaignCommittee.objects.create(fec_id="C00000001", name="Campaign")
    snapshots = []
    for rep, days, amount in [(root, 2, 100), (other, 4, 10), (other, 3, 20), (other, 1, 30)]:
        snapshot = FinanceSnapshot.objects.create(representative=rep, period=2026, run=ResearchRun.objects.create(representative=rep, period=2026, status="partial"), published_at=now - timedelta(days=days))
        FinanceTransaction.objects.create(snapshot=snapshot, contributor=donor, committee=committee, amount=amount, kind="contribution", source_key="1", source_url="https://www.fec.gov/")
        snapshots.append(snapshot)
    result = APIClient().get(f"/api/representatives/{root.pk}/connections/?period=2026&snapshot={snapshots[0].pk}&contributor={donor.pk}")
    assert result.status_code == 200
    assert {row["id"]: Decimal(row["amount"]) for row in result.data["related_representatives"]} == {root.pk: Decimal(100), other.pk: Decimal(20)}
    snapshots[2].invalidated = True
    snapshots[2].save()
    result = APIClient().get(f"/api/representatives/{root.pk}/connections/?period=2026&snapshot={snapshots[0].pk}&contributor={donor.pk}")
    assert {row["id"]: Decimal(row["amount"]) for row in result.data["related_representatives"]} == {root.pk: Decimal(100), other.pk: Decimal(10)}


@pytest.mark.parametrize("query", ["legislative_start=2024-01-01", "legislative_start=2026-01-01&legislative_end=2024-01-01", "sort=name", "kind=refund"])
def test_connections_reject_ignored_or_invalid_filters(query):
    rep = Representative.objects.create(bioguide_id="T000011", name="Test", chamber="house", state="NY")
    assert APIClient().get(f"/api/representatives/{rep.pk}/connections/?period=2026&{query}").status_code == 400
