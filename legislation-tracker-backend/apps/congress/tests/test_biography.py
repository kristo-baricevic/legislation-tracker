import time
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from apps.congress import biography


@pytest.fixture(autouse=True)
def empty_cache():
    cache.clear()
    yield
    cache.clear()


def payloads():
    return [
        {
            "results": {
                "bindings": [
                    {
                        "item": {
                            "type": "uri",
                            "value": "http://www.wikidata.org/entity/Q359442",
                        }
                    }
                ]
            }
        },
        {
            "entities": {
                "Q359442": {
                    "id": "Q359442",
                    "claims": {
                        "P1157": [
                            {
                                "rank": "normal",
                                "mainsnak": {
                                    "snaktype": "value",
                                    "datavalue": {"value": "S000033"},
                                },
                            }
                        ]
                    },
                    "sitelinks": {"enwiki": {"title": "Bernie Sanders"}},
                }
            }
        },
        {
            "query": {
                "pages": [
                    {
                        "pageid": 361176,
                        "ns": 0,
                        "title": "Bernie Sanders",
                        "fullurl": "https://en.wikipedia.org/wiki/Bernie_Sanders",
                        "lastrevid": 1378464460,
                        "pageprops": {"wikibase_item": "Q359442"},
                        "revisions": [
                            {"revid": 1378464460, "timestamp": "2026-10-04T16:55:30Z"}
                        ],
                        "extract": "Bernie Sanders is an American politician who serves as a United States senator from Vermont. "
                        + "Public biography text. " * 30,
                    }
                ]
            }
        },
    ]


@override_settings(LEGISLATOR_WIKIPEDIA_ENABLED=True)
def test_exact_identity_short_plaintext_bio_has_observed_article_provenance(
    monkeypatch,
):
    inputs = iter(payloads())
    monkeypatch.setattr(
        biography,
        "_json_get",
        lambda *args, **kwargs: deepcopy(next(inputs)),
        raising=False,
    )
    result = biography.representative_biography(SimpleNamespace(bioguide_id="S000033"))
    assert result["status"] == "available"
    assert result["wikidata_id"] == "Q359442"
    assert result["page_id"] == 361176
    assert len(result["text"]) <= 500
    assert result["shortened"] is True
    assert result["observed_revision_id"] == 1378464460
    assert (
        result["observed_revision_url"]
        == "https://en.wikipedia.org/w/index.php?oldid=1378464460"
    )
    assert result["fetched_at"]
    assert result["license"] == "CC BY-SA 4.0"
    assert "revision_id" not in result
    # A repeated read is served from verified cache, with no additional upstream read.
    assert (
        biography.representative_biography(SimpleNamespace(bioguide_id="S000033"))
        == result
    )


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("multiple", "identity_ambiguous"),
        ("no_match", "identity_unavailable"),
        ("deprecated", "identity_mismatch"),
        ("wrong_bioguide", "identity_mismatch"),
        ("wrong_wikibase", "identity_mismatch"),
        ("disambiguation", "page_unavailable"),
        ("missing", "page_unavailable"),
        ("unsafe_url", "invalid_upstream_data"),
        ("empty", "page_unavailable"),
        ("revision_race", "revision_metadata_inconsistent"),
    ],
)
@override_settings(LEGISLATOR_WIKIPEDIA_ENABLED=True)
def test_bad_identity_or_page_fails_closed(monkeypatch, mutation, reason):
    data = payloads()
    if mutation == "multiple":
        data[0]["results"]["bindings"].append(
            {"item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q1"}}
        )
    elif mutation == "no_match":
        data[0]["results"]["bindings"] = []
    elif mutation == "deprecated":
        data[1]["entities"]["Q359442"]["claims"]["P1157"][0]["rank"] = "deprecated"
    elif mutation == "wrong_bioguide":
        data[1]["entities"]["Q359442"]["claims"]["P1157"][0]["mainsnak"]["datavalue"][
            "value"
        ] = "X000001"
    else:
        page = data[2]["query"]["pages"][0]
        if mutation == "wrong_wikibase":
            page["pageprops"]["wikibase_item"] = "Q1"
        if mutation == "disambiguation":
            page["pageprops"]["disambiguation"] = ""
        if mutation == "missing":
            page["missing"] = True
        if mutation == "unsafe_url":
            page["fullurl"] = "https://en.wikipedia.org.evil.test/wiki/Bernie_Sanders"
        if mutation == "empty":
            page["extract"] = ""
        if mutation == "revision_race":
            page["lastrevid"] = 1
    if mutation == "revision_race":
        data.append(deepcopy(data[2]))
    inputs = iter(data)
    monkeypatch.setattr(
        biography,
        "_json_get",
        lambda *args, **kwargs: deepcopy(next(inputs)),
        raising=False,
    )
    result = biography.representative_biography(SimpleNamespace(bioguide_id="S000033"))
    assert result["status"] == "unavailable"
    assert result["reason"] == reason
    assert result["text"] is None


@override_settings(LEGISLATOR_WIKIPEDIA_ENABLED=True)
def test_stale_snapshot_survives_timeout_but_identity_mismatch_removes_it(monkeypatch):
    clock = timezone.now()
    monkeypatch.setattr(biography.timezone, "now", lambda: clock)
    monkeypatch.setattr(time, "time", lambda: clock.timestamp())
    inputs = iter(payloads())
    monkeypatch.setattr(
        biography,
        "_json_get",
        lambda *args, **kwargs: deepcopy(next(inputs)),
        raising=False,
    )
    rep = SimpleNamespace(bioguide_id="S000033")
    valid = biography.representative_biography(rep)
    assert valid["status"] == "available"
    clock += timedelta(days=2)

    def timeout(*args, **kwargs):
        raise biography.BiographyUnavailable("upstream_timeout")

    monkeypatch.setattr(biography, "_json_get", timeout)
    stale = biography.representative_biography(rep)
    assert stale["status"] == "stale"
    assert stale["text"] == valid["text"]
    assert stale["fetched_at"] == valid["fetched_at"]
    clock += timedelta(minutes=16)

    def mismatch(*args, **kwargs):
        raise biography.BiographyUnavailable("identity_mismatch")

    monkeypatch.setattr(biography, "_json_get", mismatch)
    assert biography.representative_biography(rep)["text"] is None


@override_settings(LEGISLATOR_WIKIPEDIA_ENABLED=True)
def test_cache_outage_and_invalid_bioguide_make_no_upstream_request(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected upstream call")

    monkeypatch.setattr(biography, "_json_get", forbidden, raising=False)
    assert (
        biography.representative_biography(
            SimpleNamespace(bioguide_id='bad" injection')
        )["reason"]
        == "identity_unavailable"
    )
    monkeypatch.setattr(
        cache, "get", lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError())
    )
    assert (
        biography.representative_biography(SimpleNamespace(bioguide_id="S000033"))[
            "reason"
        ]
        == "cache_unavailable"
    )


class Response:
    def __init__(self, status=200, headers=None, body=b'{"ok":true}'):
        self.status_code = status
        self.ok = status < 400
        self.headers = {"Content-Type": "application/json", **(headers or {})}
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, chunk_size):
        for index in range(len(self.body)):
            yield self.body[index : index + 1]


def transport(monkeypatch, response):
    calls = []

    class Session:
        trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            calls.append((url, kwargs, self.trust_env))
            return response

    monkeypatch.setattr(biography.requests, "Session", Session)
    return calls


def test_public_transport_does_not_use_credentials_redirects_or_compression(
    monkeypatch,
):
    calls = transport(monkeypatch, Response())
    assert biography._json_get(
        biography.QUERY_URL, {"format": "json"}, time.monotonic() + 8
    ) == {"ok": True}
    _, options, trust_env = calls[0]
    assert trust_env is False
    assert options["allow_redirects"] is False
    assert options["stream"] is True
    assert options["headers"]["Accept-Encoding"] == "identity"
    assert "auth" not in options and "cookies" not in options
    assert max(options["timeout"]) <= 2


@pytest.mark.parametrize(
    "response,reason",
    [
        (Response(status=403), "source_denied"),
        (Response(status=429, headers={"Retry-After": "120"}), "source_rate_limited"),
        (Response(status=302), "source_redirected"),
        (Response(status=500), "source_unavailable"),
        (Response(headers={"Content-Type": "text/html"}), "invalid_upstream_data"),
        (Response(headers={"Content-Encoding": "gzip"}), "invalid_upstream_data"),
        (Response(headers={"Content-Length": "999999"}), "invalid_upstream_data"),
        (Response(body=b"malformed"), "invalid_upstream_data"),
        (Response(body=b"[]"), "invalid_upstream_data"),
        (Response(body=b'{"error":{"code":"maxlag"}}'), "source_maxlag"),
    ],
)
def test_denied_and_malformed_transport_fails_closed(monkeypatch, response, reason):
    transport(monkeypatch, response)
    with pytest.raises(biography.BiographyUnavailable) as error:
        biography._json_get(biography.WIKIPEDIA_URL, {}, time.monotonic() + 8)
    assert error.value.reason == reason
    if response.status_code == 429:
        assert error.value.retry_seconds == 120


def test_stream_size_and_deadline_are_checked(monkeypatch):
    transport(monkeypatch, Response(body=b"123456"))
    monkeypatch.setattr(biography, "MAX_BYTES", 5)
    with pytest.raises(biography.BiographyUnavailable, match="invalid_upstream_data"):
        biography._json_get(biography.QUERY_URL, {}, time.monotonic() + 8)
    instants = iter([0, 9])
    monkeypatch.setattr(biography.time, "monotonic", lambda: next(instants))
    with pytest.raises(biography.BiographyUnavailable, match="upstream_timeout"):
        biography._json_get(biography.QUERY_URL, {}, 8)


@override_settings(LEGISLATOR_WIKIPEDIA_ENABLED=True)
def test_provider_backoff_and_lock_prevent_repeated_outbound_calls(monkeypatch):
    calls = []

    def denied(identifier):
        calls.append(identifier)
        raise biography.BiographyUnavailable("source_rate_limited", 120)

    monkeypatch.setattr(biography, "_snapshot", denied)
    assert (
        biography.representative_biography(SimpleNamespace(bioguide_id="S000033"))[
            "reason"
        ]
        == "source_rate_limited"
    )
    assert (
        biography.representative_biography(SimpleNamespace(bioguide_id="I000001"))[
            "reason"
        ]
        == "source_rate_limited"
    )
    assert calls == ["S000033"]
    cache.clear()
    cache.add(biography.GLOBAL_LOCK, "another-worker", 30)
    assert (
        biography.representative_biography(SimpleNamespace(bioguide_id="I000001"))[
            "reason"
        ]
        == "provider_busy"
    )
    assert calls == ["S000033"]


@override_settings(LEGISLATOR_WIKIPEDIA_ENABLED=True)
def test_revision_race_recovers_once_and_old_cache_expires(monkeypatch):
    data = payloads()
    previous = deepcopy(data[2])
    previous["query"]["pages"][0]["lastrevid"] = 1
    data.insert(2, previous)
    inputs = iter(data)
    monkeypatch.setattr(biography, "_json_get", lambda *args: deepcopy(next(inputs)))
    rep = SimpleNamespace(bioguide_id="S000033")
    valid = biography.representative_biography(rep)
    assert valid["status"] == "available"
    valid["fetched_at"] = (timezone.now() - timedelta(days=8)).isoformat()
    cache.set("legislator-biography:v1:en:S000033", valid, 600)

    def timeout(*args):
        raise biography.BiographyUnavailable("upstream_timeout")

    monkeypatch.setattr(biography, "_snapshot", timeout)
    assert biography.representative_biography(rep)["text"] is None
