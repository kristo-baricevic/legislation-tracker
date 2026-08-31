import pytest

from apps.ingestion import congress_client


def test_request_explicitly_asks_congress_for_json(monkeypatch):
    captured = {}

    class Response:
        ok = True
        status_code = 200
        text = "{}"

        def json(self):
            return {}

    def fake_request(method, url, params=None, timeout=None):
        captured.update(method=method, url=url, params=params, timeout=timeout)
        return Response()

    monkeypatch.setattr(congress_client, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(congress_client.requests, "request", fake_request)

    assert congress_client._request("GET", "member/congress/119") == {}
    assert captured["params"] == {"api_key": "test-key", "format": "json"}


def test_request_wraps_transport_errors_as_retryable_congress_api_errors(monkeypatch):
    def fake_request(*args, **kwargs):
        raise congress_client.requests.ConnectionError("Congress is unavailable")

    monkeypatch.setattr(congress_client.requests, "request", fake_request)

    with pytest.raises(congress_client.CongressAPIError, match="request failed"):
        congress_client._request("GET", "member/congress/119")


def test_senate_xml_transport_errors_are_retryable_congress_api_errors(monkeypatch):
    def fake_get(*args, **kwargs):
        raise congress_client.requests.ConnectionError("Senate is unavailable")

    monkeypatch.setattr(congress_client.requests, "get", fake_get)

    with pytest.raises(
        congress_client.CongressAPIError, match="Senate roll-call source failed"
    ):
        congress_client._request_senate_xml("https://www.senate.gov/example.xml")


def test_bill_actions_pages_through_recorded_vote_references(monkeypatch):
    calls = []
    expected_actions = [
        {
            "actionDate": "2026-01-02",
            "recordedVotes": [
                {
                    "chamber": "House",
                    "congress": 119,
                    "rollNumber": 17,
                    "sessionNumber": 1,
                    "url": "https://api.congress.gov/v3/house-vote/119/1/17",
                }
            ],
        },
        {"actionDate": "2026-01-01"},
        {
            "actionDate": "2025-12-31",
            "recordedVotes": [
                {
                    "chamber": "Senate",
                    "congress": 119,
                    "rollNumber": 3,
                    "sessionNumber": 1,
                    "url": "https://www.senate.gov/legislative/LIS/roll_call_votes/vote1191/vote_119_1_00003.xml",
                }
            ],
        },
    ]

    def fake_request(method, path, params=None):
        calls.append((method, path, params))
        offset = params["offset"]
        if offset == 0:
            return {"actions": expected_actions[:2]}
        return {"actions": expected_actions[2:]}

    monkeypatch.setattr(congress_client, "_request", fake_request)
    monkeypatch.setattr(congress_client, "_throttle", lambda: None)

    actions = congress_client.bill_actions(119, "hr", "1", limit=2)

    assert actions == expected_actions
    assert calls == [
        (
            "GET",
            "bill/119/hr/1/actions",
            {"limit": 2, "offset": 0},
        ),
        (
            "GET",
            "bill/119/hr/1/actions",
            {"limit": 2, "offset": 2},
        ),
    ]


def test_house_vote_detail_uses_session_scoped_detail_and_members_endpoints(
    monkeypatch,
):
    calls = []

    def fake_request(method, path, params=None):
        calls.append((method, path, params))
        if path.endswith("/members"):
            return {
                "houseRollCallVoteMemberVotes": {
                    "results": [
                        {
                            "bioguideID": "A000001",
                            "firstName": "Ada",
                            "lastName": "Member",
                            "voteCast": "Aye",
                            "voteParty": "D",
                            "voteState": "NY",
                        }
                    ]
                }
            }
        return {
            "houseRollCallVote": {
                "startDate": "2026-01-02T00:00:00Z",
                "result": "Passed",
                "votePartyTotal": [
                    {"yeaTotal": 212, "nayTotal": 193},
                ],
            }
        }

    monkeypatch.setattr(congress_client, "_request", fake_request)
    monkeypatch.setattr(congress_client, "_throttle", lambda: None)

    vote = congress_client.vote_detail(119, "house", 42, session_number=1)

    assert [call[1] for call in calls] == [
        "house-vote/119/1/42",
        "house-vote/119/1/42/members",
    ]
    assert vote == {
        "date": "2026-01-02T00:00:00Z",
        "result": "Passed",
        "yeas": 212,
        "nays": 193,
        "members": [
            {
                "bioguideId": "A000001",
                "name": "Ada Member",
                "party": "D",
                "state": "NY",
                "chamber": "house",
                "position": "yes",
            }
        ],
    }


def test_house_vote_detail_paginates_all_member_positions(monkeypatch):
    calls = []
    first_page = [
        {
            "bioguideID": f"A{index:06d}",
            "firstName": "Member",
            "lastName": str(index),
            "voteCast": "Yea",
        }
        for index in range(250)
    ]

    def fake_request(method, path, params=None):
        calls.append((method, path, params))
        if not path.endswith("/members"):
            return {"houseRollCallVote": {"votePartyTotal": []}}
        if params.get("offset") == 0:
            results = first_page
        else:
            results = [
                {
                    "bioguideID": "A000250",
                    "firstName": "Member",
                    "lastName": "250",
                    "voteCast": "Nay",
                }
            ]
        return {"houseRollCallVoteMemberVotes": {"results": results}}

    monkeypatch.setattr(congress_client, "_request", fake_request)
    monkeypatch.setattr(congress_client, "_throttle", lambda: None)

    vote = congress_client.vote_detail(119, "house", 42, session_number=1)

    assert [call[2] for call in calls[1:]] == [
        {"limit": 250, "offset": 0},
        {"limit": 250, "offset": 250},
    ]
    assert len(vote["members"]) == 251
    assert vote["members"][-1]["position"] == "no"


def test_senate_vote_detail_uses_official_senate_xml_with_bioguide_ids(monkeypatch):
    calls = []

    class Response:
        ok = True
        status_code = 200
        text = ""

        def __init__(self, content):
            self.content = content

    vote_xml = b"""
        <roll_call_vote>
          <vote_date>January 3, 2026, 10:35 AM</vote_date>
          <vote_result>Agreed to</vote_result>
          <count><yeas>60</yeas><nays>40</nays></count>
          <members>
            <member>
              <first_name>Sam</first_name><last_name>Senator</last_name>
              <party>I</party><state>VT</state><vote_cast>Not Voting</vote_cast>
            </member>
          </members>
        </roll_call_vote>
    """
    members_xml = b"""
        <contact_information>
          <member>
            <first_name>Samuel</first_name><last_name>Senator</last_name>
            <state>VT</state><bioguide_id>S000001</bioguide_id>
          </member>
        </contact_information>
    """

    def fake_get(url, timeout=None):
        calls.append((url, timeout))
        return Response(vote_xml if "roll_call_votes" in url else members_xml)

    monkeypatch.setattr(
        congress_client,
        "_request",
        lambda *args, **kwargs: pytest.fail("Senate votes must not use Congress.gov"),
    )
    monkeypatch.setattr(congress_client.requests, "get", fake_get)

    vote = congress_client.vote_detail(119, "senate", 7, session_number=1)

    assert [call[0] for call in calls] == [
        (
            "https://www.senate.gov/legislative/LIS/roll_call_votes/"
            "vote1191/vote_119_1_00007.xml"
        ),
        "https://www.senate.gov/general/contact_information/senators_cfm.xml",
    ]
    assert vote == {
        "date": "2026-01-03T15:35:00+00:00",
        "result": "Agreed to",
        "yeas": 60,
        "nays": 40,
        "members": [
            {
                "bioguideId": "S000001",
                "name": "Sam Senator",
                "party": "I",
                "state": "VT",
                "chamber": "senate",
                "position": "not_voting",
            }
        ],
    }


def test_senate_vote_detail_resolves_former_senators_from_congress_history(
    monkeypatch,
):
    class Response:
        ok = True
        status_code = 200
        text = ""

        def __init__(self, content):
            self.content = content

    vote_xml = b"""
        <roll_call_vote>
          <vote_date>January 3, 2026, 10:35 AM</vote_date>
          <vote_result>Agreed to</vote_result>
          <count><yeas>60</yeas><nays>40</nays></count>
          <members>
            <member>
              <first_name>Former</first_name><last_name>Senator</last_name>
              <party>I</party><state>VT</state><vote_cast>Yea</vote_cast>
              <lis_member_id>S999</lis_member_id>
            </member>
          </members>
        </roll_call_vote>
    """
    current_members_xml = b"<contact_information />"

    def fake_get(url, timeout=None):
        return Response(vote_xml if "roll_call_votes" in url else current_members_xml)

    monkeypatch.setattr(congress_client.requests, "get", fake_get)
    monkeypatch.setattr(
        congress_client,
        "member_list",
        lambda congress, current_member, limit, offset: [
            {
                "bioguideId": "S000999",
                "name": "Senator, Former",
                "state": "Vermont",
                "terms": {"item": [{"chamber": "Senate"}]},
            }
        ],
    )
    monkeypatch.setattr(congress_client, "_throttle", lambda: None)

    vote = congress_client.vote_detail(119, "senate", 7, session_number=1)

    assert vote["members"][0]["bioguideId"] == "S000999"


def test_bill_text_list_prefers_the_real_xml_format_over_the_version_referrer(
    monkeypatch,
):
    def fake_request(method, path, params=None):
        return {
            "textVersions": [
                {
                    "type": "Introduced in House",
                    "url": "https://api.congress.gov/v3/bill/119/hr/1/text/ih",
                    "formats": [
                        {
                            "type": "PDF",
                            "url": "https://www.congress.gov/119/bills/hr1/BILLS-119hr1ih.pdf",
                        },
                        {
                            "type": "Formatted Text",
                            "url": "https://www.congress.gov/119/bills/hr1/BILLS-119hr1ih.htm",
                        },
                        {
                            "type": "Formatted XML",
                            "url": "https://www.congress.gov/119/bills/hr1/BILLS-119hr1ih.xml",
                        },
                    ],
                }
            ]
        }

    monkeypatch.setattr(congress_client, "_request", fake_request)
    monkeypatch.setattr(congress_client, "_throttle", lambda: None)

    versions = congress_client.bill_text_list(119, "hr", "1")

    assert versions == [
        {
            "version_label": "Introduced in House",
            "url": "https://www.congress.gov/119/bills/hr1/BILLS-119hr1ih.xml",
        }
    ]
