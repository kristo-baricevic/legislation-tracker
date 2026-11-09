import pytest
from rest_framework.test import APIClient

from apps.congress.models import Representative


@pytest.mark.django_db
@pytest.mark.parametrize("code,aliases", [("D", ["D", "Democrat", "Democratic"]), ("R", ["R", "Republican"]), ("I", ["I", "ID", "Independent"])])
def test_party_filter_matches_aliases_and_combines_with_state(code, aliases):
    wanted = []
    for index, party in enumerate(aliases):
        rep = Representative.objects.create(bioguide_id=f"T{index:06}", name=f"Member {index}", party=party, state="NY", chamber="house", is_current=True)
        wanted.append(rep.pk)
    Representative.objects.create(bioguide_id="X000001", name="Other", party="Other", state="NY", chamber="house", is_current=True)
    Representative.objects.create(bioguide_id="X000002", name="Elsewhere", party=code, state="CA", chamber="house", is_current=True)
    response = APIClient().get("/api/representatives/", {"party": code, "state": "NY"})
    assert response.status_code == 200
    assert {row["id"] for row in response.data["results"]} == set(wanted)
