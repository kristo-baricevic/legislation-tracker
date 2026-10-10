"""Opt-in synthetic PostgreSQL benchmark; never touches an ingestion service."""

import json
import os
import time
import tracemalloc
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import TrackedLegislator, TrackedTopic
from apps.accounts.recommendations import candidate_query, load_profile
from apps.accounts.tests.test_recommendations_api import client
from apps.congress.models import BillCosponsor, Representative, Vote, VoteRecord
from apps.congress.topic_activity import representative_activity_catalog
from apps.legislation.models import Bill, BillTopic, Topic

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        os.getenv("RUN_RECOMMENDATION_BENCHMARK") != "1",
        reason="opt-in synthetic benchmark",
    ),
]


def measured(call):
    with CaptureQueriesContext(connection) as queries:
        start = time.perf_counter()
        result = call()
        milliseconds = 1000 * (time.perf_counter() - start)
    controls = [
        q
        for q in queries
        if q["sql"].upper().startswith(("BEGIN", "COMMIT", "SET ", "ROLLBACK"))
    ]
    return result, {
        "milliseconds": round(milliseconds, 2),
        "data_queries": len(queries) - len(controls),
        "control_queries": len(controls),
    }


def test_synthetic_postgresql_query_and_latency_budget():
    assert connection.vendor == "postgresql"
    reps = Representative.objects.bulk_create(
        [
            Representative(
                bioguide_id=f"T{i:06}",
                name=f"Synthetic member {i}",
                chamber="house",
                party="",
                state="NY",
            )
            for i in range(500)
        ]
    )
    topics = Topic.objects.bulk_create(
        [Topic(name=f"Synthetic topic {i}", slug=f"synthetic-{i}") for i in range(30)]
    )
    bills = Bill.objects.bulk_create(
        [
            Bill(
                jurisdiction="federal",
                session=119,
                bill_number=f"HR {i + 1}",
                title=f"Synthetic distinct proposal {i}",
                status="introduced",
                sponsor=reps[i % 500],
                introduced_at=date(2025, 1, 10),
            )
            for i in range(10_000)
        ],
        batch_size=1000,
    )
    BillTopic.objects.bulk_create(
        [
            BillTopic(bill=bill, topic=topics[(i + shift) % 30])
            for i, bill in enumerate(bills)
            for shift in (0, 3, 9)
        ],
        batch_size=2000,
    )
    BillCosponsor.objects.bulk_create(
        [
            BillCosponsor(
                bill=bill,
                representative=reps[(i + shift) % 500],
                sponsorship_date=date(2025, 2, 1),
            )
            for i, bill in enumerate(bills)
            for shift in (1, 7, 23)
        ],
        batch_size=2000,
    )
    votes = Vote.objects.bulk_create(
        [
            Vote(
                bill=bills[i],
                congress=119,
                chamber="house",
                session_number=1,
                roll_number=i + 1,
                vote_date=datetime(2025, 3, 1, tzinfo=UTC),
                question="On Passage",
                result="passed",
                source_url=f"https://clerk.house.gov/Votes/2025{i + 1}",
            )
            for i in range(100)
        ]
    )
    VoteRecord.objects.bulk_create(
        [
            VoteRecord(vote=vote, representative=rep, position="yes")
            for vote in votes
            for rep in reps[:400]
        ],
        batch_size=2000,
    )
    api, user = client()
    for topic in topics[:2]:
        TrackedTopic.objects.create(user=user, topic=topic)
    for rep in reps[:2]:
        TrackedLegislator.objects.create(user=user, representative=rep)
    with connection.cursor() as cursor:
        for table in (
            "legislation_bill",
            "legislation_billtopic",
            "congress_billcosponsor",
            "congress_vote",
            "congress_voterecord",
        ):
            cursor.execute(f"ANALYZE {table}")
    cache.clear()
    first, cold_routing = measured(lambda: api.get("/api/tracking/recommendations/"))
    assert first.status_code == 200
    # Separate one-time Django URL/module imports from repeatable request cost.
    first, initial = measured(lambda: api.get("/api/tracking/recommendations/"))
    assert first.status_code == 200
    second, continuation = measured(
        lambda: api.get(
            "/api/tracking/recommendations/", {"cursor": first.json()["next_cursor"]}
        )
    )
    assert second.status_code == 200
    catalog, cold = measured(representative_activity_catalog)
    result, cached = measured(
        lambda: api.get("/api/tracking/representative-recommendations/")
    )
    assert result.status_code == 200
    plan = candidate_query(load_profile(user.id))[:501].explain(
        analyze=True, buffers=True, format="json"
    )
    cache.clear()
    tracemalloc.start()
    representative_activity_catalog()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    report = {
        "fixture": {
            "bills": 10000,
            "representatives": 500,
            "topics": 30,
            "topic_edges": 30000,
            "cosponsors": 30000,
            "votes": 100,
            "vote_records": 40000,
        },
        "cold_routing_and_initial_bills": cold_routing,
        "initial_bills": initial,
        "continuation_bills": continuation,
        "cold_activity": cold,
        "cached_representatives": cached,
        "catalog_json_bytes": len(json.dumps(catalog, separators=(",", ":")).encode()),
        "catalog_peak_python_bytes": peak,
        "database": connection.pg_version,
    }
    output = Path(__file__).resolve().parents[4] / "docs" / "recommendations"
    output.mkdir(parents=True, exist_ok=True)
    (output / "synthetic-performance.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    (output / "bill-candidate-explain.json").write_text(plan + "\n")
    print(json.dumps(report))
    assert initial["data_queries"] <= 15
    assert continuation["data_queries"] <= 8
    assert cold["data_queries"] <= 12
    assert cached["data_queries"] <= 5
    assert initial["milliseconds"] < 500
    assert continuation["milliseconds"] < 150
    assert cold["milliseconds"] < 2000
    assert cached["milliseconds"] < 250
