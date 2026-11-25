import pytest
from django.core.cache import cache

from apps.accounts.models import TrackedTopic
from apps.accounts.tests.test_recommendations_api import (
    PATH,
    bill,
    client,
    representative,
    topic,
)

pytestmark = pytest.mark.django_db(transaction=True)


def test_filters_apply_before_pagination_and_have_independent_cached_cursors():
    cache.clear()
    api, user = client()
    health, education = topic(), topic("education")
    TrackedTopic.objects.create(user=user, topic=health)
    rep = representative()
    wanted = [
        bill(n, sponsor=rep, topics=(health, education), title=f"College {n}")
        for n in range(1, 4)
    ]
    bill(99, topics=(health,), title="Unrelated")
    params = {
        "q": "College",
        "topic_id": education.id,
        "sponsor": f"id:{rep.id}",
        "state": "NY",
        "status": "introduced",
        "sort": "title",
        "page_size": 1,
    }
    first = api.get(PATH, params)
    assert first.status_code == 200
    assert first.json()["results"][0]["bill"]["id"] == wanted[0].id
    assert first.json()["count"] == 3
    assert api.get(PATH).status_code == 200
    second = api.get(PATH, {**params, "cursor": first.json()["next_cursor"]})
    assert second.status_code == 200
    assert second.json()["results"][0]["bill"]["id"] == wanted[1].id
    assert api.get(
        PATH, {**params, "q": "Unrelated", "cursor": first.json()["next_cursor"]}
    ).status_code in (409, 410)
    assert api.get(PATH, {"q": "Does not exist"}).json()["results"] == []
    assert TrackedTopic.objects.filter(user=user).count() == 1


def test_dashboard_raw_status_accepts_full_official_action():
    cache.clear()
    api, user = client()
    health = topic()
    TrackedTopic.objects.create(user=user, topic=health)
    rep = representative()
    wanted = bill(2483, sponsor=rep, topics=(health,))
    wanted.status = (
        "POSTPONED PROCEEDINGS - At the conclusion of debate on the Pettersen amendment, "
        "the Chair put the question on agreeing to the amendment and by voice vote, announced "
        "the noes had prevailed. Ms. Pettersen demanded a recorded vote, and the Chair postponed "
        "further proceedings until a time to be announced."
    )
    wanted.save()
    expected = {wanted.pk}
    for number in range(1, 10):
        related = bill(number, sponsor=rep, topics=(health,))
        related.status = wanted.status
        related.save()
        expected.add(related.pk)
    bill(99, sponsor=representative("B000002"), topics=(health,))
    params = {"status": f"raw:{wanted.status}"}
    assert len(params["status"]) > 300
    page = api.get(PATH, {**params, "page_size": 10}).json()
    assert {r["bill"]["id"] for r in page["results"]} == expected
    reps = api.get("/api/tracking/representative-recommendations/", params)
    assert [r["representative_id"] for r in reps.json()["results"]] == [rep.pk]


def test_representative_filters_limit_candidates_before_top_five():
    cache.clear()
    api, user = client()
    health = topic()
    TrackedTopic.objects.create(user=user, topic=health)
    matching, other = representative(), representative("B000002")
    for n in range(10):
        bill(n + 1, sponsor=matching, topics=(health,), title=f"College support {n}")
        bill(n + 101, sponsor=other, topics=(health,), title=f"Hospital support {n}")
    response = api.get(
        "/api/tracking/representative-recommendations/", {"q": "College"}
    )
    assert response.status_code == 200
    assert [r["representative_id"] for r in response.json()["results"]] == [matching.id]
    assert (
        api.get(
            "/api/tracking/representative-recommendations/", {"q": "No match"}
        ).json()["results"]
        == []
    )
