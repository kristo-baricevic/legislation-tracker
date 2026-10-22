from decimal import Decimal
import pytest
from django.contrib.auth import get_user_model
from apps.congress.models import Representative

pytestmark = pytest.mark.django_db


def test_schedule_cursor_keeps_both_fields_and_rejects_foreign_parameters():
    from apps.campaign_finance.fec_client import receipt_parameters
    params = receipt_parameters("C00000001", 2026, {"last_index": "123", "last_contribution_receipt_date": "2026-01-01"})
    assert params["last_index"] == "123"
    assert params["last_contribution_receipt_date"] == "2026-01-01"
    with pytest.raises(ValueError):
        receipt_parameters("C00000001", 2026, {"api_key": "override"})


def test_page_replay_does_not_double_count_receipts():
    from apps.research.services import request_research
    from apps.campaign_finance.models import FinanceSnapshot, CampaignCommittee, FinanceResearchCheckpoint
    from apps.campaign_finance.research import persist_page
    rep = Representative.objects.create(bioguide_id="T000003", name="Test", chamber="house", state="NY")
    user = get_user_model().objects.create_user(username="test")
    run = request_research(rep.pk, 2026, user.pk)
    snapshot = FinanceSnapshot.objects.create(run=run, representative=rep, period=2026)
    committee = CampaignCommittee.objects.create(fec_id="C00000001", name="Campaign")
    checkpoint = FinanceResearchCheckpoint.objects.create(snapshot=snapshot, committee=committee)
    page = {"results": [{"sub_id": "1", "committee_id": committee.pk, "contributor_id": "C00000002", "contributor_name": "Test PAC", "entity_type": "PAC", "line_number": "11C", "contribution_receipt_amount": 150}], "pagination": {"last_indexes": {"last_index": "1"}}}
    persist_page(checkpoint, page)
    assert snapshot.transactions.get().amount == Decimal("150")
    with pytest.raises(ValueError, match="repeated_page"):
        persist_page(checkpoint, page)
    assert snapshot.transactions.count() == 1
    changed = {"results": [{**page["results"][0], "contribution_receipt_amount": 200}], "pagination": {"last_indexes": {"last_index": "2"}}}
    with pytest.raises(ValueError, match="source_record_changed"):
        persist_page(checkpoint, changed)
    assert snapshot.transactions.get().amount == Decimal("150")


def test_finance_read_hides_individual_names_without_release_approval(settings):
    from apps.campaign_finance.models import FinanceSnapshot, CampaignCommittee, Contributor, FinanceTransaction
    from apps.research.services import request_research
    from rest_framework.test import APIClient
    settings.FEC_INDIVIDUAL_PUBLICATION_ENABLED = False
    rep = Representative.objects.create(bioguide_id="T000003", name="Test", chamber="house", state="NY")
    run = request_research(rep.pk, 2026, get_user_model().objects.create_user(username="test").pk)
    snapshot = FinanceSnapshot.objects.create(run=run, representative=rep, period=2026, active=True)
    committee = CampaignCommittee.objects.create(fec_id="C00000001", name="Campaign")
    donor = Contributor.objects.create(name="Private donor", kind="individual")
    FinanceTransaction.objects.create(snapshot=snapshot, source_key="1", committee=committee, contributor=donor, amount=100, kind="contribution", source_url="https://www.fec.gov/")
    response = APIClient().get(f"/api/representatives/{rep.pk}/contributors/?period=2026")
    assert response.status_code == 200
    assert response.data["count"] == 0
    assert "Private donor" not in response.content.decode()


def test_refunds_are_separate_disbursements_not_negative_donations():
    from apps.campaign_finance.normalization import normalize_refund
    result = normalize_refund({"sub_id": "12", "committee_id": "C00000001", "recipient_committee_id": "C00000002", "recipient_name": "Example PAC", "entity_type": "PAC", "line_number": "20C", "disbursement_amount": 25, "disbursement_date": "2026-02-01"})
    assert result["kind"] == "refund"
    assert result["amount"] == Decimal("25")
    assert result["identity_key"] == "fec:C00000002"
    assert result["source_key"] == "B:C00000001:12"


def test_nonrefund_disbursement_is_excluded():
    from apps.campaign_finance.normalization import normalize_refund
    result = normalize_refund({"sub_id": "12", "committee_id": "C00000001", "recipient_name": "Vendor", "line_number": "17", "disbursement_amount": 25})
    assert result["effective"] is False


def test_published_snapshot_remains_readable_after_refresh_but_not_revocation():
    from apps.campaign_finance.models import FinanceSnapshot
    from apps.research.services import request_research
    from rest_framework.test import APIClient
    from django.utils import timezone
    rep = Representative.objects.create(bioguide_id="T000006", name="Test", chamber="house", state="NY")
    run = request_research(rep.pk, 2026, get_user_model().objects.create_user(username="test").pk)
    saved = FinanceSnapshot.objects.create(run=run, representative=rep, period=2026, active=False, published_at=timezone.now())
    url = f"/api/representatives/{rep.pk}/contributors/?period=2026&snapshot={saved.pk}"
    assert APIClient().get(url).status_code == 200
    saved.invalidated = True
    saved.save()
    assert APIClient().get(url).status_code == 404
