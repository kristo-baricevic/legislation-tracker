import pytest
from django.core.cache import cache
from apps.accounts.models import TrackedTopic
from apps.accounts.tests.test_recommendations_api import bill, client, representative, topic, PATH

pytestmark = pytest.mark.django_db(transaction=True)


def test_filters_apply_before_pagination_and_have_independent_cached_cursors():
    cache.clear()
    api, user = client()
    health, education = topic(), topic("education")
    TrackedTopic.objects.create(user=user, topic=health)
    rep = representative()
    wanted = [bill(n, sponsor=rep, topics=(health, education), title=f"College {n}") for n in range(1, 4)]
    bill(99, topics=(health,), title="Unrelated")
    params = {"q": "College", "topic_id": education.id, "sponsor": f"id:{rep.id}", "state": "NY", "status": "introduced", "sort": "title", "page_size": 1}
    first = api.get(PATH, params)
    assert first.status_code == 200
    assert first.json()["results"][0]["bill"]["id"] == wanted[0].id
    assert first.json()["count"] == 3
    assert api.get(PATH).status_code == 200
    second = api.get(PATH, {**params, "cursor": first.json()["next_cursor"]})
    assert second.status_code == 200
    assert second.json()["results"][0]["bill"]["id"] == wanted[1].id
    assert api.get(PATH, {**params, "q": "Unrelated", "cursor": first.json()["next_cursor"]}).status_code in (409, 410)
    assert api.get(PATH, {"q": "Does not exist"}).json()["results"] == []
    assert TrackedTopic.objects.filter(user=user).count() == 1


def test_representative_filters_limit_candidates_before_top_five():
    cache.clear()
    api, user = client()
    health = topic()
    TrackedTopic.objects.create(user=user, topic=health)
    matching, other = representative(), representative("B000002")
    for n in range(10):
        bill(n + 1, sponsor=matching, topics=(health,), title=f"College support {n}")
        bill(n + 101, sponsor=other, topics=(health,), title=f"Hospital support {n}")
    response = api.get("/api/tracking/representative-recommendations/", {"q": "College"})
    assert response.status_code == 200
    assert [r["representative_id"] for r in response.json()["results"]] == [matching.id]
    assert api.get("/api/tracking/representative-recommendations/", {"q": "No match"}).json()["results"] == []
