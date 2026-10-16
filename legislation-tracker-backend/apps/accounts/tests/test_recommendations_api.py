from datetime import date
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.accounts.models import TrackedBill, TrackedLegislator, TrackedTopic
from apps.congress.models import BillCosponsor, Representative
from apps.legislation.models import Bill, BillTopic, Topic

pytestmark = pytest.mark.django_db(transaction=True)
PATH = "/api/tracking/recommendations/"


@pytest.fixture(autouse=True)
def empty_cache():
    cache.clear()


def client(email="reader@example.com"):
    user = get_user_model().objects.create_user(username=email, email=email)
    result = APIClient()
    result.force_authenticate(user)
    return result, user


def representative(code="A000001"):
    return Representative.objects.create(
        bioguide_id=code, name=code, chamber="house", party="", state="NY"
    )


def bill(number, *, sponsor=None, topics=(), title=None):
    result = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number=f"HR {number}",
        title=title or f"Bill {number}",
        status="introduced",
        sponsor=sponsor,
        introduced_at=date(2025, 1, 10),
    )
    for topic in topics:
        BillTopic.objects.create(bill=result, topic=topic, confidence_score=None)
    return result


def topic(slug="health"):
    return Topic.objects.get_or_create(slug=slug, defaults={"name": slug.title()})[0]


def test_no_follows_is_private_cold_start():
    api, _ = client()
    response = api.get(PATH)
    assert response.status_code == 200
    assert response.json()["empty_reason"] == "no_follows"
    assert response.json()["results"] == []
    assert response["Cache-Control"] == "private, no-store"


def test_initial_page_reuses_ranking_until_follow_change_or_expiry():
    from apps.accounts.recommendations import build_ranking
    from apps.accounts.recommendation_views import snapshot_key
    api, user = client()
    with patch("apps.accounts.recommendation_views.build_ranking", wraps=build_ranking) as rank:
        assert api.get(PATH).status_code == 200
        assert api.get(PATH).status_code == 200
        assert rank.call_count == 1
        TrackedTopic.objects.create(user=user, topic=topic())
        assert api.get(PATH).status_code == 200
        assert rank.call_count == 2
        cache.delete(snapshot_key(user.pk))
        assert api.get(PATH).status_code == 200
        assert rank.call_count == 3


def test_database_failure_is_private_and_has_retry_hint():
    from django.db import OperationalError

    api, _ = client()
    with patch(
        "apps.accounts.recommendation_views.load_profile",
        side_effect=OperationalError("offline"),
    ):
        response = api.get(PATH)
    assert response.status_code == 503
    assert response["Cache-Control"] == "private, no-store"
    assert "Cookie" in response["Vary"] and "Authorization" in response["Vary"]
    assert response["Retry-After"] == "5"


def test_expired_foreign_cursor_is_uniform_invalid():
    from django.core import signing

    from apps.accounts.recommendation_views import CURSOR_SALT
    from apps.accounts.recommendations import ALGORITHM

    api, user = client()
    with patch("django.core.signing.time.time", return_value=1):
        foreign = signing.dumps(
            {
                "version": ALGORITHM,
                "user_id": user.id + 1,
                "nonce": "a" * 32,
                "offset": 6,
                "page_size": 6,
            },
            salt=CURSOR_SALT,
        )
        owned = signing.dumps(
            {
                "version": ALGORITHM,
                "user_id": user.id,
                "nonce": "a" * 32,
                "offset": 6,
                "page_size": 6,
            },
            salt=CURSOR_SALT,
        )
    assert api.get(PATH, {"cursor": foreign}).status_code == 400
    assert api.get(PATH, {"cursor": owned}).status_code == 410


def test_anonymous_cannot_request_recommendations_under_dev_defaults():
    response = APIClient().get(PATH)
    assert response.status_code in (401, 403)
    assert response["Cache-Control"] == "private, no-store"


def test_crossover_saturates_and_excludes_unrelated_and_own_followed():
    api, user = client()
    health, education = topic(), topic("education")
    rep = representative()
    TrackedTopic.objects.create(user=user, topic=health)
    TrackedTopic.objects.create(user=user, topic=education)
    TrackedLegislator.objects.create(user=user, representative=rep)
    crossed = bill(1, sponsor=rep, topics=(health, education))
    cosponsored = bill(2, topics=(health,))
    BillCosponsor.objects.create(bill=cosponsored, representative=rep)
    topic_only = bill(3, topics=(health,))
    sponsor_only = bill(4, sponsor=rep)
    bill(5)
    own = bill(6, sponsor=rep, topics=(health,))
    TrackedBill.objects.create(user=user, bill=own)
    response = api.get(PATH)
    assert response.status_code == 200
    items = response.json()["results"]
    assert [item["bill"]["id"] for item in items] == [
        crossed.id,
        cosponsored.id,
        topic_only.id,
        sponsor_only.id,
    ]
    assert [item["score"] for item in items] == [1.0, 0.87, 0.48, 0.32]
    assert len(items[0]["reasons"]) == 2
    assert items[1]["reasons"][1]["relation"] == "cosponsor"


def test_user_isolation_and_topic_only_missing_sponsor_normalization():
    api, user = client()
    other_api, other = client("other@example.com")
    health = topic()
    TrackedTopic.objects.create(user=user, topic=health)
    match = bill(1, topics=(health,))
    TrackedBill.objects.create(user=other, bill=match)
    response = api.get(PATH)
    assert response.status_code == 200
    assert response.json()["results"][0]["score"] == 0.8
    assert other_api.get(PATH).json()["results"] == []


def test_seed_metadata_is_weaker_and_seed_ties_are_deterministic():
    api, user = client()
    health, rep = topic(), representative()
    first = bill(1, sponsor=rep, topics=(health,))
    second = bill(2, sponsor=rep, topics=(health,))
    TrackedBill.objects.create(user=user, bill=second)
    TrackedBill.objects.create(user=user, bill=first)
    target = bill(3, sponsor=rep, topics=(health,))
    response = api.get(PATH)
    assert response.status_code == 200
    item = response.json()["results"][0]
    assert item["bill"]["id"] == target.id
    assert item["score"] == 0.35
    assert {reason["seed_bill_id"] for reason in item["reasons"]} == {first.id}


def test_fallback_and_withdrawn_cosponsors_do_not_match():
    api, user = client()
    fallback, rep = topic("general-legislation"), representative()
    TrackedTopic.objects.create(user=user, topic=fallback)
    response = api.get(PATH)
    assert response.status_code == 200
    assert response.json()["empty_reason"] == "unsupported_follows_only"
    TrackedLegislator.objects.create(user=user, representative=rep)
    target = bill(1, topics=(fallback,))
    from django.utils import timezone

    BillCosponsor.objects.create(
        bill=target, representative=rep, withdrawn_at=timezone.now()
    )
    assert api.get(PATH).json()["results"] == []


@pytest.mark.parametrize(
    "query",
    [
        "unknown=1",
        "page_size=0",
        "page_size=13",
        "page_size=6&page_size=6",
        "cursor=bad",
    ],
)
def test_strict_query_contract(query):
    api, _ = client()
    assert api.get(f"{PATH}?{query}").status_code == 400


def test_cursor_only_inherits_size_and_profile_change_invalidates():
    api, user = client()
    health = topic()
    TrackedTopic.objects.create(user=user, topic=health)
    for number in range(20):
        bill(number + 1, topics=(health,))
    first = api.get(PATH, {"page_size": 12})
    assert first.status_code == 200
    token = first.json()["next_cursor"]
    second = api.get(PATH, {"cursor": token})
    assert second.status_code == 200
    assert len(second.json()["results"]) == 8
    assert not (
        {i["bill"]["id"] for i in first.json()["results"]}
        & {i["bill"]["id"] for i in second.json()["results"]}
    )
    assert api.get(PATH, {"cursor": token, "page_size": 6}).status_code == 400
    other_api, _ = client("other@example.com")
    assert other_api.get(PATH, {"cursor": token}).status_code == 400
    TrackedBill.objects.create(
        user=user, bill_id=second.json()["results"][0]["bill"]["id"]
    )
    assert api.get(PATH, {"cursor": token}).status_code == 409


def test_cache_failure_in_throttle_is_private_recoverable_error():
    api, _ = client()
    with patch.object(cache, "get", side_effect=ConnectionError("offline")):
        response = api.get(PATH)
    assert response.status_code == 503
    assert response.json()["detail"] == "recommendations_unavailable"
    assert response["Cache-Control"] == "private, no-store"


def test_initial_query_count_does_not_grow_per_card():
    api, user = client()
    health = topic()
    TrackedTopic.objects.create(user=user, topic=health)
    for number in range(15):
        bill(number + 1, topics=(health,))
    with CaptureQueriesContext(connection) as queries:
        response = api.get(PATH)
    assert response.status_code == 200
    data_queries = [
        q
        for q in queries
        if not q["sql"].upper().startswith(("BEGIN", "COMMIT", "SET "))
    ]
    assert len(data_queries) <= 15


def test_snapshot_byte_bound_rejects_large_metadata_without_truncation():
    api, user = client()
    health = topic()
    TrackedTopic.objects.create(user=user, topic=health)
    bill(1, topics=(health,), title="A" * (1024 * 1024))
    response = api.get(PATH)
    assert response.status_code == 503
    assert response.json()["detail"] == "recommendations_metadata_too_large"


def test_postgresql_rejects_nan_infinities_and_nonpositive_confidence():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL float ordering contract")
    api, user = client()
    health = topic()
    TrackedTopic.objects.create(user=user, topic=health)
    for number, confidence in enumerate(
        (None, 0.5, 0, -1, float("nan"), float("inf"), float("-inf")), start=1
    ):
        item = bill(number)
        BillTopic.objects.create(bill=item, topic=health, confidence_score=confidence)
    response = api.get(PATH)
    assert response.status_code == 200
    assert [item["bill"]["bill_number"] for item in response.json()["results"]] == [
        "HR 1",
        "HR 2",
    ]


def test_catalog_changes_do_not_reorder_continuation_but_deleted_item_invalidates():
    api, user = client()
    health = topic()
    TrackedTopic.objects.create(user=user, topic=health)
    for number in range(8):
        bill(number + 1, topics=(health,))
    first = api.get(PATH).json()
    bill(9, topics=(health,))
    continuation = api.get(PATH, {"cursor": first["next_cursor"]})
    assert continuation.status_code == 200
    assert [item["bill"]["bill_number"] for item in continuation.json()["results"]] == [
        "HR 7",
        "HR 8",
    ]
    Bill.objects.filter(bill_number="HR 7").delete()
    assert api.get(PATH, {"cursor": first["next_cursor"]}).status_code == 409


def test_cold_start_sparse_and_no_match_states():
    api, user = client()
    seed = bill(1)
    TrackedBill.objects.create(user=user, bill=seed)
    assert api.get(PATH).json()["empty_reason"] == "insufficient_metadata"
    health = topic()
    TrackedTopic.objects.create(user=user, topic=health)
    assert api.get(PATH).json()["empty_reason"] == "no_matches"
    target = bill(2, topics=(health,))
    # New corpus entries become visible after the five-minute result cache expires.
    assert api.get(PATH).json()["results"] == []
    from apps.accounts.recommendation_views import snapshot_key
    cache.delete(snapshot_key(user.pk))
    assert api.get(PATH).json()["results"][0]["bill"]["id"] == target.id
    TrackedTopic.objects.filter(user=user).delete()
    assert api.get(PATH).json()["results"] == []


def separate_postgres_write(sql, parameters):
    import psycopg

    config = connection.settings_dict
    with psycopg.connect(
        dbname=config["NAME"],
        user=config["USER"],
        password=config["PASSWORD"],
        host=config["HOST"],
        port=config["PORT"],
    ) as other:
        other.execute(sql, parameters)


def test_postgresql_continuation_owns_consistent_snapshot_during_follow_change():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL repeatable-read interleaving")
    from apps.accounts.recommendations import load_profile

    api, user = client()
    health = topic()
    TrackedTopic.objects.create(user=user, topic=health)
    for number in range(8):
        bill(number + 1, topics=(health,))
    first = api.get(PATH).json()

    def change_after_profile(owner):
        profile = load_profile(owner)
        separate_postgres_write(
            "INSERT INTO accounts_trackedbill (user_id, bill_id, created_at) VALUES (%s, %s, NOW())",
            (owner, Bill.objects.get(bill_number="HR 7").id),
        )
        return profile

    with patch(
        "apps.accounts.recommendation_views.load_profile",
        side_effect=change_after_profile,
    ):
        response = api.get(PATH, {"cursor": first["next_cursor"]})
    assert response.status_code == 200
    assert response.json()["results"][0]["bill"]["bill_number"] == "HR 7"
    assert api.get(PATH, {"cursor": first["next_cursor"]}).status_code == 409


def test_postgresql_initial_profile_and_candidate_queries_share_snapshot():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL repeatable-read interleaving")
    from apps.accounts.recommendations import load_profile

    api, user = client()
    health, education = topic(), topic("education")
    TrackedTopic.objects.create(user=user, topic=health)
    bill(1, topics=(health,))
    bill(2, topics=(education,))

    def change_after_profile(owner):
        profile = load_profile(owner)
        separate_postgres_write(
            "INSERT INTO accounts_trackedtopic (user_id, topic_id, created_at) VALUES (%s, %s, NOW())",
            (owner, education.id),
        )
        return profile

    with patch(
        "apps.accounts.recommendation_views.load_profile",
        side_effect=change_after_profile,
    ):
        response = api.get(PATH)
    assert response.status_code == 200
    assert [item["bill"]["bill_number"] for item in response.json()["results"]] == [
        "HR 1"
    ]
    assert len(api.get(PATH).json()["results"]) == 2


def test_cursor_detects_cache_slot_replacement_before_return():
    from apps.accounts.recommendation_support import cache_call

    api, user = client()
    health = topic()
    TrackedTopic.objects.create(user=user, topic=health)
    for number in range(8):
        bill(number + 1, topics=(health,))
    first = api.get(PATH).json()
    changed = False

    def replace(method, *args, **kwargs):
        nonlocal changed
        value = cache_call(method, *args, **kwargs)
        if method == "get" and not changed:
            changed = True
            cache.set(args[0], {**value, "nonce": "b" * 32}, timeout=300)
        return value

    with patch("apps.accounts.recommendation_views.cache_call", side_effect=replace):
        assert api.get(PATH, {"cursor": first["next_cursor"]}).status_code == 409
