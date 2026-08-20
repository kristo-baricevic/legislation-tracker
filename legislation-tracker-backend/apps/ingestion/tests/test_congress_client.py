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


def test_house_vote_detail_uses_session_scoped_detail_and_members_endpoints(monkeypatch):
    calls = []

    def fake_request(method, path, params=None):
        calls.append((method, path, params))
        if path.endswith("/members"):
            return {
                "houseRollCallVoteMemberVotes": {
                    "results": [
                        {
                            "bioguideId": "A000001",
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
            "bioguideId": f"A{index:06d}",
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
                    "bioguideId": "A000250",
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


def test_senate_vote_detail_uses_the_session_scoped_senate_endpoints(monkeypatch):
    calls = []

    def fake_request(method, path, params=None):
        calls.append((method, path, params))
        if path.endswith("/members"):
            return {
                "senateRollCallVoteMemberVotes": {
                    "results": [
                        {
                            "bioguideId": "S000001",
                            "firstName": "Sam",
                            "lastName": "Senator",
                            "voteCast": "Not Voting",
                            "voteParty": "I",
                            "voteState": "VT",
                        }
                    ]
                }
            }
        return {
            "senateRollCallVote": {
                "startDate": "2026-01-03T00:00:00Z",
                "result": "Agreed to",
                "votePartyTotal": [{"yeaTotal": 60, "nayTotal": 40}],
            }
        }

    monkeypatch.setattr(congress_client, "_request", fake_request)
    monkeypatch.setattr(congress_client, "_throttle", lambda: None)

    vote = congress_client.vote_detail(119, "senate", 7, session_number=1)

    assert [call[1] for call in calls] == [
        "senate-vote/119/1/7",
        "senate-vote/119/1/7/members",
    ]
    assert vote == {
        "date": "2026-01-03T00:00:00Z",
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


def test_bill_text_list_preserves_top_level_version_url(monkeypatch):
    def fake_request(method, path, params=None):
        return {
            "textVersions": [
                {
                    "type": "Introduced",
                    "url": "https://example.test/bills/hr1.xml",
                }
            ]
        }

    monkeypatch.setattr(congress_client, "_request", fake_request)
    monkeypatch.setattr(congress_client, "_throttle", lambda: None)

    versions = congress_client.bill_text_list(119, "hr", "1")

    assert versions == [
        {
            "version_label": "Introduced",
            "url": "https://example.test/bills/hr1.xml",
        }
    ]
