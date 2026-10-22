"""Disposable browser-test API + durable-task runner. Only upstreams are faked.

Never accepts a database URL; every run creates its own temporary SQLite DB.
No network source calls, production database, or existing stack processes.
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch
from wsgiref.simple_server import make_server

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
for number, chamber, fec in [(1, "house", "H0NY00001"), (2, "senate", "S0NY00001"), (3, "house", None)]:
    rep = Representative.objects.create(bioguide_id=f"T00000{number}", name=f"Research Member {number}", chamber=chamber, state="NY", district="1" if chamber == "house" else None, party="Independent")
    if fec:
        candidate = CandidateIdentity.objects.create(fec_id=fec, name=rep.name, state="NY", office=fec[0])
        RepresentativeCandidate.objects.create(representative=rep, candidate=candidate, periods=[2026], verified=True, evidence_url=f"https://www.fec.gov/data/candidate/{fec}/")
    bill = Bill.objects.create(bill_number=f"HR {number}", session=119, title=f"Research education bill {number}", jurisdiction="federal", sponsor=rep, introduced_at="2026-01-01")
    topic, _ = Topic.objects.get_or_create(slug="education", defaults={"name": "Education"})
    BillTopic.objects.create(bill=bill, topic=topic)


def fec_page(path, params):
    if path == "candidates/search/":
        return {"results": [], "pagination": {"pages": 1}}
    if path.endswith("/committees/"):
        return {"results": [{"committee_id": "C00000001", "name": "Member campaign", "designation": "P"}], "pagination": {"pages": 1}}
    if path.endswith("/totals/"):
        return {"results": [{"individual_itemized_contributions": 0, "political_party_committee_contributions": 0, "other_political_committee_contributions": 150, "contribution_refunds": 25, "coverage_start_date": "2025-01-01", "coverage_end_date": "2026-10-01"}], "pagination": {"pages": 1}}
    if params.get("last_index"):
        return {"results": [], "pagination": {"last_indexes": {}}}
    if path == "schedules/schedule_a/":
        return {"results": [{"sub_id": "1001", "committee_id": "C00000001", "contributor_id": "C00000002", "contributor_name": "Education Example PAC", "entity_type": "PAC", "line_number": "11C", "contribution_receipt_amount": 150, "contribution_receipt_date": "2026-01-01"}], "pagination": {"last_indexes": {"last_index": "1001", "last_contribution_receipt_date": "2026-01-01"}}}
    if path == "schedules/schedule_b/":
        return {"results": [{"sub_id": "1002", "committee_id": "C00000001", "recipient_committee_id": "C00000002", "recipient_name": "Education Example PAC", "entity_type": "PAC", "line_number": "20C", "disbursement_amount": 25, "disbursement_date": "2026-02-01"}], "pagination": {"last_indexes": {"last_index": "1002", "last_disbursement_date": "2026-02-01"}}}
    raise AssertionError(f"Unexpected fixture endpoint: {path}")


def wiki(identifier):
    return {"text": "This member serves New York in Congress. The member previously worked in public service.", "observed_revision_url": "https://en.wikipedia.org/w/index.php?oldid=1", "observed_revision_id": 1, "wikidata_id": "Q1", "attribution": "Wikipedia contributors", "license": "CC BY-SA 4.0"}


def worker():
    while True:
        close_old_connections()
        work = IngestionWorkItem.objects.filter(kind="representative_research", status="pending").order_by("id").first()
        if work:
            process_ingestion_work_item.apply(args=[work.pk]).get()
        time.sleep(.1)


with patch("apps.campaign_finance.research.get_page", fec_page), patch("apps.ingestion.congress_client.member_detail", lambda key: {"bioguideId": key, "depiction": {"imageUrl": f"https://www.congress.gov/img/member/{key.lower()}_200.jpg", "attribution": "Congress.gov"}}), patch("apps.congress.biography._snapshot", wiki):
    threading.Thread(target=worker, daemon=True).start()
    with make_server("127.0.0.1", 18420, get_wsgi_application()) as server:
        server.serve_forever()
