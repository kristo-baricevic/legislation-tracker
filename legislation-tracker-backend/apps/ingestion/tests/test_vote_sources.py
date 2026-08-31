from xml.etree import ElementTree

import pytest

from apps.ingestion import vote_sources
from apps.ingestion.congress_client import CongressAPIError


def test_house_source_uses_offset_cursor_and_does_not_silently_stop_at_first_page(
    monkeypatch,
):
    calls = []

    def fake_request(method, path, params):
        calls.append((method, path, params))
        return {
            "houseRollCallVotes": [
                {"rollNumber": number, "updateDate": "2026-01-02T00:00:00Z"}
                for number in range(params["offset"] + 1, params["offset"] + 251)
            ]
        }

    monkeypatch.setattr(vote_sources, "_request", fake_request)
    source = vote_sources.HouseVoteSource()

    first = source.discover_page(congress=119, session_number=1)
    second = source.discover_page(
        congress=119, session_number=1, cursor=first.next_cursor
    )

    assert (first.refs[0].roll_number, first.next_cursor) == (1, "250")
    assert (second.refs[0].roll_number, second.next_cursor) == (251, "500")
    assert [call[2]["offset"] for call in calls] == [0, 250]


def test_house_source_rejects_duplicate_roll_numbers_on_one_page(monkeypatch):
    monkeypatch.setattr(
        vote_sources,
        "_request",
        lambda *_args, **_kwargs: {
            "houseVotes": [{"rollNumber": 1}, {"rollNumber": 1}]
        },
    )

    with pytest.raises(CongressAPIError, match="duplicate"):
        vote_sources.HouseVoteSource().discover_page(congress=119, session_number=1)


def test_senate_source_parses_official_list_and_rejects_nonempty_cursor(monkeypatch):
    root = ElementTree.fromstring(
        b"<vote_list><vote><vote_number>7</vote_number><vote_date>2026-01-02T00:00:00Z</vote_date></vote></vote_list>"
    )
    monkeypatch.setattr(vote_sources, "_request_senate_xml", lambda _url: root)
    source = vote_sources.SenateVoteSource()

    page = source.discover_page(congress=119, session_number=1)

    assert (page.refs[0].roll_number, page.next_cursor) == (7, None)
    with pytest.raises(CongressAPIError, match="does not support pagination"):
        source.discover_page(congress=119, session_number=1, cursor="1")
