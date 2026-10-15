from datetime import date

import pytest
from django.core.cache import cache

from apps.accounts.models import TrackedLegislator, TrackedTopic
from apps.accounts.tests.test_recommendations_api import (
    bill,
    client,
    representative,
    topic,
)
from apps.congress.models import RepresentativeTerm
from apps.legislation.models import BillTopic

pytestmark = pytest.mark.django_db(transaction=True)
PATH = "/api/tracking/representative-recommendations/"


@pytest.fixture(autouse=True)
def empty_cache():
    cache.clear()


def test_representative_cold_start_is_private():
    api, _ = client()
    response = api.get(PATH)
    assert response.status_code == 200
    assert response.json()["empty_reason"] == "no_follows"
    assert response["Cache-Control"] == "private, no-store"


def test_representatives_use_explicit_topics_and_exclude_followed():
    api, user = client()
    health = topic()
    TrackedTopic.objects.create(user=user, topic=health)
    rep, followed = representative(), representative("B000002")
    TrackedLegislator.objects.create(user=user, representative=followed)
    for number in range(20):
        bill(number + 1, sponsor=rep, topics=(health,))
    response = api.get(PATH)
    assert response.status_code == 200
    results = response.json()["results"]
    assert [item["representative_id"] for item in results] == [rep.id]
    assert results[0]["score"] == 0.4
    assert results[0]["reasons"][0]["kind"] == "followed_topic"
    evidence = results[0]["topic_activity_evidence"]
    assert evidence["channels"]["sponsor"]["topics"][0]["recurring"] is True


def test_exact_fraction_boundary_and_year_derived_service_uncertainty():
    api, user = client()
    health, education, housing = topic(), topic("education"), topic("housing")
    TrackedTopic.objects.create(user=user, topic=health)
    rep = representative()
    RepresentativeTerm.objects.create(
        representative=rep, chamber="house", state="NY", start_date=date(2025, 1, 3)
    )
    for number in range(30):
        item = bill(number + 1, sponsor=rep, topics=(education, housing))
        if number < 18:
            BillTopic.objects.create(bill=item, topic=health)
    response = api.get(PATH)
    assert response.status_code == 200
    evidence = response.json()["results"][0]["topic_activity_evidence"]
    health_metric = next(
        item
        for item in evidence["channels"]["sponsor"]["topics"]
        if item["topic"]["id"] == health.id
    )
    assert health_metric["raw"]["mass"] == {"numerator": "6", "denominator": "1"}
    assert health_metric["raw"]["share"] == 0.2
    assert health_metric["recurring"] is True
    assert evidence["exposure"]["service_days"] is None
    assert evidence["exposure"]["monthly_rate"] is None
    assert evidence["exposure"]["reason"] == "term_precision_unknown"


def test_bill_only_profile_is_not_representative_interest():
    api, user = client()
    from apps.accounts.models import TrackedBill

    TrackedBill.objects.create(user=user, bill=bill(1, topics=(topic(),)))
    response = api.get(PATH)
    assert response.status_code == 200
    assert response.json()["empty_reason"] == "no_follows"


def test_top_five_is_deterministic_unique_and_isolated():
    api, user = client()
    other_api, other = client("other@example.com")
    health = topic()
    TrackedTopic.objects.create(user=user, topic=health)
    reps = [representative(f"T{i:06}") for i in range(8)]
    for index, rep in enumerate(reps):
        for number in range(10):
            bill(10 * index + number + 1, sponsor=rep, topics=(health,))
    first = api.get(PATH).json()["results"]
    second = api.get(PATH).json()["results"]
    assert [item["representative_id"] for item in first] == [rep.id for rep in reps[:5]]
    assert first == second
    assert len({item["representative_id"] for item in first}) == 5
    assert other_api.get(PATH).json()["results"] == []
    TrackedLegislator.objects.create(user=user, representative=reps[0])
    assert reps[0].id not in {
        item["representative_id"] for item in api.get(PATH).json()["results"]
    }


def test_former_reference_allowed_but_former_candidate_excluded():
    api, user = client()
    health = topic()
    former, current = representative(), representative("B000002")
    former.is_current = False
    former.save(update_fields=["is_current"])
    TrackedLegislator.objects.create(user=user, representative=former)
    for index, rep in enumerate((former, current)):
        for number in range(8):
            bill(10 * index + number + 1, sponsor=rep, topics=(health,))
    response = api.get(PATH)
    assert response.status_code == 200
    assert [item["representative_id"] for item in response.json()["results"]] == [
        current.id
    ]
    assert (
        response.json()["results"][0]["reasons"][0]["kind"]
        == "followed_representative_activity"
    )


def test_anonymous_and_database_failures_keep_privacy_headers():
    from unittest.mock import patch

    from django.db import OperationalError
    from rest_framework.test import APIClient

    anonymous = APIClient().get(PATH)
    assert anonymous.status_code in (401, 403)
    assert anonymous["Cache-Control"] == "private, no-store"
    api, _ = client()
    with patch(
        "apps.accounts.representative_recommendation_views.TrackedTopic.objects.filter",
        side_effect=OperationalError("offline"),
    ):
        response = api.get(PATH)
    assert response.status_code == 503
    assert response["Retry-After"] == "5"
    assert response["Cache-Control"] == "private, no-store"
