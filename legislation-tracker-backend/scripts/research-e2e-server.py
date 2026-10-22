"""Disposable browser-test API + durable-task runner. Only upstreams are faked.

Never accepts a database URL; every run creates its own temporary SQLite DB.
No network source calls, production database, or existing stack processes.
"""
import os
import sys
import tempfile
import threading
import time
import json
from pathlib import Path
from unittest.mock import patch
from wsgiref.simple_server import make_server, WSGIServer
from socketserver import ThreadingMixIn


class BrowserTestServer(ThreadingMixIn, WSGIServer):
    # Browsers can preconnect without sending a request. A single-threaded
    # server blocks every other API request behind that idle connection.
    daemon_threads = True

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
scratch = tempfile.TemporaryDirectory(prefix="legislation-research-e2e-")
os.environ.update(DATABASE_URL=f"sqlite:///{scratch.name}/research.sqlite3", DJANGO_SETTINGS_MODULE="config.settings.test", DJANGO_SECRET_KEY="isolated-research-browser-test-key-not-for-deployment", ALLOWED_HOSTS="127.0.0.1,localhost,testserver", CORS_ALLOWED_ORIGINS="http://127.0.0.1:13420", CSRF_TRUSTED_ORIGINS="http://127.0.0.1:13420", FEC_API_KEY="fixture-only", LEGAL_NLP_V21_WRITE_ENABLED="False", LLM_ENHANCEMENTS_ENABLED="False")
import django
django.setup()
from django.conf import settings
from django.core.management import call_command
from django.core.wsgi import get_wsgi_application
from django.db import close_old_connections
from django.contrib.auth import get_user_model
from apps.congress.models import Representative
from apps.legislation.models import Bill, Topic, BillTopic
from apps.campaign_finance.models import CandidateIdentity, RepresentativeCandidate
from apps.ingestion.models import IngestionWorkItem
from apps.ingestion.tasks import process_ingestion_work_item

settings.CONGRESS_API_KEY = "fixture-only"
settings.LEGISLATOR_WIKIPEDIA_ENABLED = True
call_command("migrate", verbosity=0)
get_user_model().objects.create_user(username="research@example.test", email="research@example.test", password="Research-test-password-2026!")
for number, chamber, fec in [(1, "house", "H0NY00001"), (2, "senate", "S0NY00001"), (3, "house", None), (4, "house", "H8NY15148")]:
    rep = Representative.objects.create(bioguide_id=f"T00000{number}", name=f"Research Member {number}", chamber=chamber, state="NY", district="1" if chamber == "house" else None, party="Independent")
    if fec:
        candidate = CandidateIdentity.objects.create(fec_id=fec, name=rep.name, state="NY", office=fec[0])
        RepresentativeCandidate.objects.create(representative=rep, candidate=candidate, periods=[2026], verified=True, evidence_url=f"https://www.fec.gov/data/candidate/{fec}/")
        if number == 2:
            second = CandidateIdentity.objects.create(fec_id="S0NY00002", name=rep.name, state="NY", office="S")
            RepresentativeCandidate.objects.create(representative=rep, candidate=second, periods=[2026], verified=True, evidence_url="https://www.fec.gov/data/candidate/S0NY00002/")
    bill = Bill.objects.create(bill_number=f"HR {number}", session=119, title=f"Research education bill {number}", jurisdiction="federal", sponsor=rep, introduced_at="2026-01-01")
    topic, _ = Topic.objects.get_or_create(slug="education", defaults={"name": "Education"})
    BillTopic.objects.create(bill=bill, topic=topic)


def fec_page(path, params):
    if path == "candidates/search/":
        return {"results": [], "pagination": {"pages": 1}}
    if path.endswith("/committees/"):
        committee = "C00639591" if "H8NY15148" in path else "C00000003" if "S0NY00002" in path else "C00000001"
        return {"results": [{"committee_id": committee, "name": "Member campaign " + committee, "designation": "P"}], "pagination": {"pages": 1}}
    if path.endswith("/totals/"):
        return {"results": [{"receipts": 1200, "disbursements": 300, "individual_itemized_contributions": 0, "political_party_committee_contributions": 0, "other_political_committee_contributions": 150, "contribution_refunds": 25, "coverage_start_date": "2025-01-01", "coverage_end_date": "2026-10-01"}], "pagination": {"pages": 1}}
    if params.get("last_index"):
        return {"results": [], "pagination": {"last_indexes": {}}}
    if params.get("committee_id") == "C00639591":
        recorded = json.loads((Path(__file__).resolve().parents[1] / "apps/congress/tests/fixtures/fec_recorded_2026_10_22.json").read_text())
        return recorded["committee_receipts" if path.endswith("schedule_a/") else "refunds"]
    if path == "schedules/schedule_a/":
        return {"results": [{"sub_id": "1001", "committee_id": "C00000001", "contributor_id": "C00000002", "contributor_name": "Education Example PAC", "entity_type": "PAC", "line_number": "11C", "contribution_receipt_amount": 150, "contribution_receipt_date": "2026-01-01"}], "pagination": {"last_indexes": {"last_index": "1001", "last_contribution_receipt_date": "2026-01-01"}}}
    if path == "schedules/schedule_b/":
        return {"results": [{"sub_id": "1002", "committee_id": "C00000001", "recipient_committee_id": "C00000002", "recipient_name": "Education Example PAC", "entity_type": "PAC", "line_number": "20C", "disbursement_amount": 25, "disbursement_date": "2026-02-01"}], "pagination": {"last_indexes": {"last_index": "1002", "last_disbursement_date": "2026-02-01"}}}
    raise AssertionError(f"Unexpected fixture endpoint: {path}")


class FixtureResponse:
    status_code = 200
    headers = {"Content-Type": "application/json"}
    def __init__(self, payload): self.body = json.dumps(payload).encode()
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def iter_content(self, size):
        for offset in range(0, len(self.body), size):
            yield self.body[offset:offset + size]


class FixtureSession:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def get(self, url, *, params, **kwargs):
        assert url.startswith("https://api.open.fec.gov/v1/")
        payload = fec_page(url.removeprefix("https://api.open.fec.gov/v1/"), params)
        if params.get("line_number"):
            line = params["line_number"].removeprefix("F3-")
            payload["results"] = [row for row in payload["results"] if row.get("line_number") == line]
            if not payload["results"]:
                payload["pagination"] = {"last_indexes": {}}
        if params.get("committee_id") == "C00000003":
            for row in payload["results"]:
                row["committee_id"] = "C00000003"
                row["sub_id"] = "3" + row["sub_id"]
        return FixtureResponse(payload)


def wiki(identifier):
    return {"text": "This member serves New York in Congress. The member previously worked in public service.", "observed_revision_url": "https://en.wikipedia.org/w/index.php?oldid=1", "observed_revision_id": 1, "wikidata_id": "Q1", "attribution": "Wikipedia contributors", "license": "CC BY-SA 4.0"}


def worker(stop_after_page=False):
    while True:
        close_old_connections()
        work = IngestionWorkItem.objects.filter(kind="representative_research", status="pending").order_by("id").first()
        if work:
            process_ingestion_work_item.apply(args=[work.pk]).get()
            from apps.campaign_finance.models import FinanceResearchCheckpoint
            if stop_after_page and FinanceResearchCheckpoint.objects.filter(schedule__startswith="a").exclude(page_hashes=[]).exists():
                # Kill this runner after a committed page. A fresh runner must
                # continue solely from persisted work/checkpoints.
                close_old_connections()
                return
        time.sleep(.1)


def supervise_worker():
    first = threading.Thread(target=worker, kwargs={"stop_after_page": True}, daemon=True)
    first.start()
    first.join()
    worker()


with patch("apps.campaign_finance.fec_client.requests.Session", FixtureSession), patch("apps.ingestion.congress_client.member_detail", lambda key: {"bioguideId": key, "depiction": {"imageUrl": f"https://www.congress.gov/img/member/{key.lower()}_200.jpg", "attribution": "Congress.gov"}}), patch("apps.congress.biography._snapshot", wiki):
    threading.Thread(target=supervise_worker, daemon=True).start()
    with make_server("127.0.0.1", 18420, get_wsgi_application(), server_class=BrowserTestServer) as server:
        server.serve_forever()
