from decimal import Decimal
import pytest
from django.contrib.auth import get_user_model
from apps.congress.models import Representative
from apps.campaign_finance.models import CandidateIdentity, RepresentativeCandidate, FinanceSnapshot
from apps.research.services import request_research
from apps.ingestion.tasks import process_ingestion_work_item

pytestmark = pytest.mark.django_db


def test_amendment_and_deleted_record_replace_current_scan_not_history(settings, monkeypatch):
    settings.FEC_API_KEY = "fixture"
    settings.CONGRESS_API_KEY = ""
    settings.LEGISLATOR_WIKIPEDIA_ENABLED = False
    user = get_user_model().objects.create_user(username="refresh")
    rep = Representative.objects.create(bioguide_id="T000010", name="Test", chamber="house", state="NY")
    candidate = CandidateIdentity.objects.create(fec_id="H0NY00001", name="Test", office="H", state="NY")
    RepresentativeCandidate.objects.create(representative=rep, candidate=candidate, periods=[2026], verified=True, evidence_url="https://www.fec.gov/data/candidate/H0NY00001/")
    current_records = []
    def page(path, params):
        if path.endswith("/committees/"):
            return {"results": [{"committee_id": "C00000001", "name": "Campaign", "designation": "P"}], "pagination": {"pages": 1}}
        if path.endswith("/totals/") or path == "schedules/schedule_b/" or params.get("last_index"):
            return {"results": [], "pagination": {}}
        assert path == "schedules/schedule_a/"
        return {"results": current_records, "pagination": {"last_indexes": {"last_index": "next", "last_contribution_receipt_date": "2026-01-01"}}}
    monkeypatch.setattr("apps.campaign_finance.research.get_page", page)
    monkeypatch.setattr("apps.ingestion.tasks.dispatch_ingestion_work.delay", lambda: None)
    def scan(records):
        nonlocal current_records
        current_records = records
        run = request_research(rep.pk, 2026, user.pk)
        for _ in range(15):
            process_ingestion_work_item.apply(args=[run.work_item_id]).get()
            run.refresh_from_db()
            if run.status not in {"queued", "running"}:
                break
        assert run.status == "partial"
        return FinanceSnapshot.objects.get(run=run, active=True)
    def row(sub_id, amount, transaction_id):
        return {"sub_id": sub_id, "committee_id": "C00000001", "contributor_id": "C00000002", "entity_type": "PAC", "contributor_name": "Example PAC", "line_number": "11C", "contribution_receipt_amount": amount, "contribution_receipt_date": "2026-01-01", "transaction_id": transaction_id}
    old = scan([row("1", 100, "amended"), row("2", 50, "deleted")])
    new = scan([row("3", 150, "amended")])
    old.refresh_from_db()
    assert not old.active
    assert old.transactions.count() == 2
    assert new.transactions.count() == 1
    assert new.transactions.get().amount == Decimal("150")
    assert new.transactions.get().source_metadata["transaction_id"] == "amended"
    assert Decimal(new.totals["observed_itemized_contributions"]) == Decimal("150")
