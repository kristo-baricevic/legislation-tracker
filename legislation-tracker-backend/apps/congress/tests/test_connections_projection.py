import pytest
from django.core.cache import cache
from rest_framework.test import APIClient
from apps.congress.models import Representative
from apps.legislation.models import Bill, Topic, BillTopic

pytestmark = pytest.mark.django_db(transaction=True)


def test_typed_edges_and_cached_projection_refresh_after_bulk_topic_change(monkeypatch):
    from apps.campaign_finance import connections
    cache.clear()
    rep = Representative.objects.create(bioguide_id="T000051", name="Test", chamber="house", state="NY")
    bill = Bill.objects.create(bill_number="HR 4", session=119, title="Education bill", jurisdiction="federal", sponsor=rep, introduced_at="2026-01-01")
    topic = Topic.objects.create(name="Education policy", slug="education-policy")
    BillTopic.objects.create(bill=bill, topic=topic)
    url = f"/api/representatives/{rep.pk}/connections/?period=2026"
    first = APIClient().get(url)
    assert first.status_code == 200
    assert {e["kind"] for e in first.data["edges"]} == {"sponsored", "bill_tagged_topic"}
    assert all(e["evidence_url"] for e in first.data["edges"])
    original = connections.build_connections
    monkeypatch.setattr(connections, "build_connections", lambda *a, **k: (_ for _ in ()).throw(AssertionError("cache miss")))
    assert APIClient().get(url).data == first.data
    monkeypatch.setattr(connections, "build_connections", original)
    Topic.objects.filter(pk=topic.pk).update(name="Updated education policy")
    updated = APIClient().get(url)
    assert any(n["label"] == "Updated education policy" for n in updated.data["nodes"])
    BillTopic.objects.filter(bill=bill).delete()
    assert {e["kind"] for e in APIClient().get(url).data["edges"]} == {"sponsored"}


def test_rolled_back_projection_never_poison_cache():
    from django.db import transaction
    from apps.campaign_finance.connections import get_connections
    cache.clear()
    rep = Representative.objects.create(bioguide_id="T000052", name="Original", chamber="house", state="NY")
    get_connections(rep.pk, 2026)
    with transaction.atomic():
        Representative.objects.filter(pk=rep.pk).update(name="Rolled back")
        get_connections(rep.pk, 2026)
        transaction.set_rollback(True)
    Representative.objects.filter(pk=rep.pk).update(name="Committed")
    result = get_connections(rep.pk, 2026)
    assert any(n["label"] == "Committed" for n in result["nodes"])


def test_committee_name_change_invalidates_projection():
    from apps.campaign_finance.models import CampaignCommittee, ConnectionRevision
    revision, _ = ConnectionRevision.objects.get_or_create(pk=1)
    committee = CampaignCommittee.objects.create(fec_id="C00000099", name="Original")
    revision.refresh_from_db()
    before = revision.generation
    CampaignCommittee.objects.filter(pk=committee.pk).update(name="Corrected")
    revision.refresh_from_db()
    assert revision.generation > before


def test_edges_preserve_withdrawal_and_procedural_vote_context():
    from datetime import datetime, timezone
    from apps.congress.models import BillCosponsor, Vote, VoteRecord
    rep = Representative.objects.create(bioguide_id="T000053", name="Member", chamber="house", state="NY")
    bill = Bill.objects.create(bill_number="HR 5", session=119, title="Test bill", jurisdiction="federal", introduced_at="2026-01-01")
    when = datetime(2026, 2, 1, tzinfo=timezone.utc)
    BillCosponsor.objects.create(representative=rep, bill=bill, sponsorship_date="2026-01-02", withdrawn_at=when)
    for number, question, position in [(1, "On the previous question", "yes"), (2, "On passage", "no")]:
        vote = Vote.objects.create(bill=bill, congress=119, chamber="house", roll_number=number, vote_date=when, result="passed", question=question)
        VoteRecord.objects.create(vote=vote, representative=rep, position=position)
    data = APIClient().get(f"/api/representatives/{rep.pk}/connections/?period=2026").data
    edges = data["edges"]
    cosponsor = next(edge for edge in edges if edge["kind"] == "cosponsored")
    assert str(cosponsor["withdrawn_at"]).startswith("2026-02-01")
    votes = [edge for edge in edges if edge["kind"] == "recorded_vote"]
    assert {edge["label"] for edge in votes} == {"On the previous question: yes", "On passage: no"}
    assert all(str(edge["date"]).startswith("2026-02-01") for edge in votes)
    assert data["count"] == 1
