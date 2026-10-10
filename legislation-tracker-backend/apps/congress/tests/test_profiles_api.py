from datetime import UTC, date, datetime

import pytest
from rest_framework.test import APIClient

from apps.congress.models import (
    BillCosponsor,
    Representative,
    RepresentativeTerm,
    Vote,
    VoteRecord,
)
from apps.legislation.models import Bill

pytestmark = pytest.mark.django_db


def member(bioguide="I000100", **fields):
    return Representative.objects.create(
        bioguide_id=bioguide,
        name="Same Name",
        chamber=fields.pop("chamber", "senate"),
        party="Independent",
        state=fields.pop("state", "VT"),
        **fields,
    )


def record(representative, roll, *, chamber="house", session=1, **fields):
    vote = Vote.objects.create(
        congress=119,
        chamber=chamber,
        session_number=session,
        roll_number=roll,
        vote_date=datetime(2025, 1, 9, 19, tzinfo=UTC),
        question="On the motion to proceed",
        source_url="https://api.congress.gov/v3/house-vote/119/1/1?api_key=secret",
    )
    return VoteRecord.objects.create(
        vote=vote,
        representative=representative,
        position=fields.pop("position", "yes"),
        raw_position=fields.pop("raw_position", "Yea"),
        **fields,
    )


def test_profile_keeps_historical_identity_and_unavailable_elections_separate():
    representative = member(is_current=False)
    member("I000101", chamber="house", state="NY")
    RepresentativeTerm.objects.create(
        representative=representative,
        chamber="house",
        state="VT",
        district="1",
        start_date=date(2023, 1, 3),
        end_date=date(2027, 1, 3),
    )
    response = APIClient().get(
        f"/api/representatives/{representative.id}/profile/?congress=119"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["identity"]["id"] == representative.id
    assert data["identity"]["bioguide_id"] == "I000100"
    assert data["identity"]["latest_affiliation"]["chamber"] == "senate"
    assert data["service"]["observations"][0]["chamber"] == "house"
    assert data["service"]["observations"][0]["start_year"] == 2023
    assert data["service"]["precision"] == "year"
    assert "2023-01-03" not in str(data["service"])
    for field in ("first_elected", "most_recent_election_won", "term_start"):
        assert data["elections"][0][field]["status"] == "unavailable"
        assert data["elections"][0][field]["value"] is None
    assert data["donors"]["status"] == "unavailable"
    assert data["donors"]["cycle"] is None
    assert data["donors"]["donors"] == []
    assert "image_url" not in data["identity"]


def test_missing_history_does_not_substitute_latest_chamber():
    representative = member()
    response = APIClient().get(
        f"/api/representatives/{representative.id}/profile/?congress=118"
    )
    assert response.status_code == 200
    assert response.json()["service"]["status"] == "unavailable"
    assert response.json()["elections"][0]["chamber"] is None


def test_direct_votes_do_not_use_latest_chamber_or_service_window():
    representative = member()
    other = member("I000101")
    first = record(representative, 1)
    record(other, 2)
    senate = record(
        representative,
        1,
        chamber="senate",
        session=2,
        position="other",
        raw_position="Absent",
    )
    response = APIClient().get(
        f"/api/representatives/{representative.id}/voting-record/?congress=119"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    assert {row["id"] for row in data["results"]} == {first.id, senate.id}
    assert data["coverage"]["member_position_completeness"] == "unknown"
    assert data["coverage"]["stored_record_count"] == 2
    assert {scope["chamber"] for scope in data["coverage"]["provider_scopes"]} == {
        "house",
        "senate",
    }
    by_chamber = {row["chamber"]: row for row in data["results"]}
    assert by_chamber["house"]["source_url"] == "https://clerk.house.gov/Votes/20251"
    assert "api_key" not in str(data)
    assert (
        by_chamber["senate"]["source_url"] is None
    )  # session 2 with 2025 date is inconsistent
    assert by_chamber["senate"]["raw_position"] == "Absent"
    assert by_chamber["senate"]["bill"] is None


def test_votes_have_live_replacement_pagination_and_actual_chamber_filter():
    representative = member()
    record(representative, 1)
    record(representative, 2)
    record(representative, 3, chamber="senate")
    client = APIClient()
    url = f"/api/representatives/{representative.id}/voting-record/?congress=119&chamber=house&page_size=1"
    first = client.get(url).json()
    assert first["count"] == 2
    assert first["pagination_mode"] == "live_pages"
    assert first["page_read_at"]
    assert first["results"][0]["roll_number"] == 2
    first_record_id = first["results"][0]["id"]
    VoteRecord.objects.filter(pk=first_record_id).delete()
    next_response = client.get(url + "&page=2")
    assert next_response.status_code == 404
    assert client.get(url).json()["results"][0]["roll_number"] == 1


@pytest.mark.parametrize(
    "query",
    [
        "",
        "congress=0",
        "congress=999999",
        "congress=119&chamber=state",
        "congress=119&other=1",
        "congress=119&page_size=101",
        "congress=119&page=0",
    ],
)
def test_profile_vote_query_contract_rejects_invalid_scope(query):
    representative = member()
    response = APIClient().get(
        f"/api/representatives/{representative.id}/voting-record/?{query}"
    )
    assert response.status_code == 400


def test_biography_disabled_is_public_and_has_no_upstream_calls(monkeypatch):
    representative = member()

    def forbidden(*args, **kwargs):
        raise AssertionError("disabled provider made a network request")

    monkeypatch.setattr("requests.get", forbidden)
    response = APIClient().get(f"/api/representatives/{representative.id}/biography/")
    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert response.json()["reason"] == "provider_disabled"


def test_introduced_bills_use_sponsor_id_and_safe_public_source_projection():
    representative = member()
    Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 5",
        title="Introduced",
        sponsor=representative,
    )
    response = APIClient().get(
        f"/api/representatives/{representative.id}/sponsored-bills/?congress=119"
    )
    assert response.status_code == 200
    bill = response.json()["results"][0]
    assert bill["sponsor_id"] == representative.id
    assert bill["sponsor_bioguide_id"] == "I000100"
    assert (
        bill["congress_gov_url"]
        == "https://www.congress.gov/bill/119th-congress/house-bill/5"
    )


def test_cosponsors_and_same_name_sponsors_are_not_introduced_bills():
    representative = member()
    other = member("I000101")
    introduced = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="S 5",
        title="Introduced",
        sponsor=representative,
    )
    cosponsored = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 6",
        title="Cosponsored",
        sponsor=other,
    )
    BillCosponsor.objects.create(bill=cosponsored, representative=representative)
    result = (
        APIClient()
        .get(f"/api/representatives/{representative.id}/sponsored-bills/?congress=119")
        .json()
    )
    assert [bill["id"] for bill in result["results"]] == [introduced.id]


def test_chamber_service_scope_retains_uncertain_boundary_years():
    representative = member()
    for chamber, start, end in [
        ("house", 2023, 2025),
        ("senate", 2027, 2029),
        ("house", 2029, 2031),
    ]:
        RepresentativeTerm.objects.create(
            representative=representative,
            chamber=chamber,
            start_date=date(start, 1, 3),
            end_date=date(end, 1, 3),
        )
    client = APIClient()
    all_scopes = client.get(
        f"/api/representatives/{representative.id}/profile/?congress=119"
    ).json()
    assert [
        (term["chamber"], term["start_year"])
        for term in all_scopes["service"]["observations"]
    ] == [("house", 2023), ("senate", 2027)]
    assert "uncertain boundary years" in all_scopes["service"]["notice"]
    house = client.get(
        f"/api/representatives/{representative.id}/profile/?congress=119&chamber=house"
    ).json()
    assert [term["chamber"] for term in house["service"]["observations"]] == ["house"]
    assert house["identity"]["latest_affiliation"]["chamber"] == "senate"


def test_vote_source_uses_civil_year_and_scope_checked_session_list():
    representative = member()
    entry = record(representative, 1, chamber="senate", session=2)
    entry.vote.vote_date = datetime(
        2027, 1, 1, 1, tzinfo=UTC
    )  # Dec31 2026 in Washington
    entry.vote.save()
    client = APIClient()
    url = f"/api/representatives/{representative.id}/voting-record/?congress=119"
    assert (
        client.get(url)
        .json()["results"][0]["source_url"]
        .endswith("vote_119_2_00001.htm")
    )
    entry.vote.session_number = None
    entry.vote.source_url = (
        "https://www.senate.gov/legislative/LIS/roll_call_lists/vote_menu_118_2.xml"
    )
    entry.vote.save()
    assert client.get(url).json()["results"][0]["source_url"] is None
    entry.vote.source_url = (
        "https://www.senate.gov/legislative/LIS/roll_call_lists/vote_menu_119_2.xml"
    )
    entry.vote.save()
    assert client.get(url).json()["results"][0]["source_link_kind"] == "session_list"


def test_positions_remain_distinct_and_public_reads_need_no_auth():
    representative = member()
    for roll, position, raw in [
        (1, "yes", "Yea"),
        (2, "no", "Nay"),
        (3, "present", "Present"),
        (4, "not_voting", "Not Voting"),
        (5, "other", "Absent"),
    ]:
        record(representative, roll, position=position, raw_position=raw)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer invalid")
    result = client.get(
        f"/api/representatives/{representative.id}/voting-record/?congress=119"
    )
    assert result.status_code == 200
    assert {
        (row["position"], row["raw_position"]) for row in result.json()["results"]
    } == {
        ("yes", "Yea"),
        ("no", "Nay"),
        ("present", "Present"),
        ("not_voting", "Not Voting"),
        ("other", "Absent"),
    }
    assert (
        client.get("/api/representatives/999999/profile/?congress=119").status_code
        == 404
    )


def test_biography_public_throttle_limits_repeat_requests():
    from django.core.cache import cache

    cache.clear()
    representative = member()
    client = APIClient()
    for _ in range(12):
        assert (
            client.get(
                f"/api/representatives/{representative.id}/biography/"
            ).status_code
            == 200
        )
    assert (
        client.get(f"/api/representatives/{representative.id}/biography/").status_code
        == 429
    )
    cache.clear()


def test_biography_cache_failure_in_throttle_returns_unavailable_without_network(
    monkeypatch, settings
):
    from django.core.cache import cache

    settings.LEGISLATOR_WIKIPEDIA_ENABLED = True
    representative = member()

    def unavailable(*args, **kwargs):
        raise ConnectionError("cache unavailable")

    def forbidden(*args, **kwargs):
        raise AssertionError("outbound request during throttle failure")

    monkeypatch.setattr(cache, "get", unavailable)
    monkeypatch.setattr("apps.congress.biography._snapshot", forbidden)
    response = APIClient().get(f"/api/representatives/{representative.id}/biography/")
    assert response.status_code == 200
    assert response.json()["reason"] == "cache_unavailable"


def test_public_topic_activity_wrapper_is_strict_and_preserves_helper_contract(
    monkeypatch,
):
    import sys
    from types import ModuleType

    representative = member()
    calls = []
    module = ModuleType("apps.congress.topic_activity")

    def helper(representative_id, *, captured_at):
        calls.append((representative_id, captured_at))
        return {
            "schema_version": "representative-topic-activity-v1",
            "representative": {"id": representative_id},
        }

    module.representative_topic_activity = helper
    monkeypatch.setitem(sys.modules, "apps.congress.topic_activity", module)
    client = APIClient()
    assert (
        client.get(
            f"/api/representatives/{representative.id}/topic-activity/?congress=119"
        ).status_code
        == 400
    )
    assert client.get("/api/representatives/999999/topic-activity/").status_code == 404
    result = client.get(f"/api/representatives/{representative.id}/topic-activity/")
    assert result.status_code == 200
    assert result.json()["schema_version"] == "representative-topic-activity-v1"
    assert calls[0][0] == representative.id and calls[0][1].tzinfo


def test_voting_bill_projection_does_not_add_queries_per_row():
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    representative = member()
    first = record(representative, 1)
    first.vote.bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 1",
        title="Linked bill",
        sponsor=representative,
    )
    first.vote.save()
    url = f"/api/representatives/{representative.id}/voting-record/?congress=119&page_size=30"
    client = APIClient()
    with CaptureQueriesContext(connection) as small:
        assert client.get(url).status_code == 200
    for roll in range(2, 31):
        entry = record(representative, roll)
        entry.vote.bill = Bill.objects.create(
            jurisdiction="federal",
            session=119,
            bill_number=f"HR {roll}",
            title="Linked bill",
            sponsor=representative,
        )
        entry.vote.save()
    with CaptureQueriesContext(connection) as large:
        result = client.get(url)
        assert len(result.json()["results"]) == 30
    assert len(large) <= len(small) + 1


def test_legacy_complete_checks_do_not_establish_member_completeness(monkeypatch):
    representative = member()
    monkeypatch.setattr(
        "apps.congress.profiles._coverage", lambda **kwargs: (True, None, 12)
    )
    result = (
        APIClient()
        .get(f"/api/representatives/{representative.id}/profile/?congress=119")
        .json()
    )
    assert result["coverage"]["legacy_ingestion_check"]["coverage_complete"] is True
    assert result["coverage"]["legacy_ingestion_check"]["discovered_count"] == 12
    assert result["coverage"]["stored_record_count"] == 0
    assert result["coverage"]["member_position_completeness"] == "unknown"
