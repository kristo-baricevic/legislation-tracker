"""Bounded, exact-identity Wikimedia excerpts, independent of stored facts."""

import json
import re
import time
from datetime import timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.throttling import AnonRateThrottle

QUERY_URL = "https://query.wikidata.org/sparql"
ENTITY_URL = "https://www.wikidata.org/w/api.php"
WIKIPEDIA_URL = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "LegislationTrackerProfiles/1.0 (https://github.com/kristo-baricevic/legislation-tracker)"
GLOBAL_LOCK = "legislator-biography:v1:provider-lock"
BACKOFF_KEY = "legislator-biography:v1:provider-backoff"
MAX_BYTES = 512_000
FRESH_SECONDS = 24 * 60 * 60
STALE_SECONDS = 7 * 24 * 60 * 60
NEGATIVE_SECONDS = 15 * 60


class BiographyThrottle(AnonRateThrottle):
    rate = "12/min"
    scope = "legislator_biography"

    def allow_request(self, request, view):
        try:
            return super().allow_request(request, view)
        except Exception:
            # The view returns an unavailable snapshot without an outbound call.
            # A broken rate-limit cache must never enable uncached enrichment.
            request.biography_cache_unavailable = True
            return True


class BiographyUnavailable(Exception):
    def __init__(self, reason, retry_seconds=None):
        self.reason = reason
        self.retry_seconds = retry_seconds
        super().__init__(reason)


def _retry_seconds(value):
    if not value:
        return NEGATIVE_SECONDS
    try:
        return max(1, int(value))
    except (ValueError, TypeError):
        try:
            instant = parsedate_to_datetime(value)
            if timezone.is_naive(instant):
                return NEGATIVE_SECONDS
            return max(1, int((instant - timezone.now()).total_seconds()))
        except (ValueError, TypeError, OverflowError):
            return NEGATIVE_SECONDS


def _json_get(url, params, deadline):
    if url not in {QUERY_URL, ENTITY_URL, WIKIPEDIA_URL}:
        raise BiographyUnavailable("invalid_upstream_data")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise BiographyUnavailable("upstream_timeout")
    # A private session never reads .netrc credentials, environment proxy auth,
    # or a user cookie jar. Only these fixed public endpoints are requested.
    with requests.Session() as session:
        session.trust_env = False
        try:
            with session.get(
                url,
                params=params,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                },
                timeout=(min(2, remaining / 2), min(2, remaining / 2)),
                allow_redirects=False,
                stream=True,
            ) as response:
                if response.status_code in (403, 429):
                    raise BiographyUnavailable(
                        (
                            "source_denied"
                            if response.status_code == 403
                            else "source_rate_limited"
                        ),
                        _retry_seconds(response.headers.get("Retry-After")),
                    )
                if 300 <= response.status_code < 400:
                    raise BiographyUnavailable("source_redirected")
                if not response.ok:
                    raise BiographyUnavailable("source_unavailable")
                if response.headers.get("Content-Encoding", "identity") not in (
                    "",
                    "identity",
                ):
                    raise BiographyUnavailable("invalid_upstream_data")
                if "json" not in response.headers.get("Content-Type", ""):
                    raise BiographyUnavailable("invalid_upstream_data")
                content_length = response.headers.get("Content-Length")
                if content_length and (
                    not content_length.isdigit() or int(content_length) > MAX_BYTES
                ):
                    raise BiographyUnavailable("invalid_upstream_data")
                body = bytearray()
                # One-byte streaming checks prevent a slow, continuously dripping
                # response from filling a large chunk before the deadline check.
                for chunk in response.iter_content(chunk_size=1):
                    if time.monotonic() >= deadline:
                        raise BiographyUnavailable("upstream_timeout")
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise BiographyUnavailable("invalid_upstream_data")
                data = json.loads(body)
        except requests.Timeout as error:
            raise BiographyUnavailable("upstream_timeout") from error
        except (requests.RequestException, ValueError, UnicodeError) as error:
            raise BiographyUnavailable("invalid_upstream_data") from error
    if not isinstance(data, dict):
        raise BiographyUnavailable("invalid_upstream_data")
    if "error" in data:
        raise BiographyUnavailable(
            "source_maxlag"
            if isinstance(data["error"], dict) and data["error"].get("code") == "maxlag"
            else "invalid_upstream_data"
        )
    return data


def unavailable_biography(reason):
    return {
        "status": "unavailable",
        "text": None,
        "reason": reason,
        "wikidata_id": None,
        "page_id": None,
        "observed_revision_id": None,
        "observed_revision_at": None,
        "page_url": None,
        "observed_revision_url": None,
        "fetched_at": None,
        "shortened": False,
        "attribution": "Wikipedia contributors",
        "license": "CC BY-SA 4.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
    }


def _snapshot(identifier):
    deadline = time.monotonic() + 8
    query = f'SELECT DISTINCT ?item WHERE {{ ?item wdt:P1157 "{identifier}". }} LIMIT 2'
    found = _json_get(QUERY_URL, {"query": query, "format": "json"}, deadline)
    bindings = found.get("results", {}).get("bindings")
    if not isinstance(bindings, list):
        raise BiographyUnavailable("invalid_upstream_data")
    if not bindings:
        raise BiographyUnavailable("identity_unavailable")
    if len(bindings) != 1:
        raise BiographyUnavailable("identity_ambiguous")
    item = bindings[0].get("item", {})
    match = re.fullmatch(
        r"https?://www\.wikidata\.org/entity/(Q[1-9]\d{0,14})", item.get("value", "")
    )
    if item.get("type") != "uri" or not match:
        raise BiographyUnavailable("invalid_upstream_data")
    qid = match[1]
    result = _json_get(
        ENTITY_URL,
        {
            "action": "wbgetentities",
            "ids": qid,
            "props": "claims|sitelinks",
            "format": "json",
        },
        deadline,
    )
    entity = result.get("entities", {}).get(qid, {})
    claims = entity.get("claims", {}).get("P1157", [])
    if entity.get("id") != qid or not any(
        claim.get("rank") != "deprecated"
        and claim.get("mainsnak", {}).get("snaktype") == "value"
        and claim.get("mainsnak", {}).get("datavalue", {}).get("value") == identifier
        for claim in claims
    ):
        raise BiographyUnavailable("identity_mismatch")
    title = entity.get("sitelinks", {}).get("enwiki", {}).get("title")
    if (
        not isinstance(title, str)
        or not title.strip()
        or len(title) > 512
        or re.search(r"[\x00-\x1f\x7f]", title)
    ):
        raise BiographyUnavailable("page_unavailable")
    params = {
        "action": "query",
        "format": "json",
        "formatversion": 2,
        "prop": "extracts|info|revisions|pageprops",
        "titles": title,
        "exintro": 1,
        "explaintext": 1,
        "exchars": 500,
        "inprop": "url",
        "rvprop": "ids|timestamp",
    }
    for attempt in range(2):
        result = _json_get(WIKIPEDIA_URL, params, deadline)
        pages = result.get("query", {}).get("pages")
        if (
            not isinstance(pages, list)
            or len(pages) != 1
            or not isinstance(pages[0], dict)
        ):
            raise BiographyUnavailable("invalid_upstream_data")
        page = pages[0]
        props = page.get("pageprops", {})
        if props.get("wikibase_item") != qid:
            raise BiographyUnavailable("identity_mismatch")
        if (
            page.get("ns") != 0
            or any(key in page for key in ("missing", "invalid", "redirect"))
            or "disambiguation" in props
        ):
            raise BiographyUnavailable("page_unavailable")
        revisions = page.get("revisions", [])
        revision = (
            revisions[0] if isinstance(revisions, list) and len(revisions) == 1 else {}
        )
        revid = revision.get("revid")
        if type(revid) is not int or revid <= 0 or page.get("lastrevid") != revid:
            if attempt == 0:
                continue
            raise BiographyUnavailable("revision_metadata_inconsistent")
        break
    observed_at = revision.get("timestamp")
    instant = parse_datetime(observed_at) if isinstance(observed_at, str) else None
    if (
        instant is None
        or timezone.is_naive(instant)
        or instant > timezone.now() + timedelta(minutes=5)
    ):
        raise BiographyUnavailable("invalid_upstream_data")
    page_id = page.get("pageid")
    page_title = page.get("title")
    url = page.get("fullurl")
    try:
        parsed = urlsplit(url)
        safe = (
            parsed.scheme == "https"
            and parsed.hostname == "en.wikipedia.org"
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
            and not parsed.query
            and not parsed.fragment
            and isinstance(page_title, str)
            and unquote(parsed.path) == "/wiki/" + page_title.replace(" ", "_")
            and "/../" not in unquote(parsed.path)
        )
    except (ValueError, TypeError):
        safe = False
    if not safe or type(page_id) is not int or page_id <= 0:
        raise BiographyUnavailable("invalid_upstream_data")
    extract = page.get("extract")
    if not isinstance(extract, str) or not extract.strip():
        raise BiographyUnavailable("page_unavailable")
    text = re.sub(r"\s+", " ", extract).strip()
    shortened = len(text) > 500
    if shortened:
        boundary = text.rfind(" ", 0, 501)
        text = text[:boundary] if boundary > 0 else ""
    if not text:
        raise BiographyUnavailable("page_unavailable")
    return {
        "status": "available",
        "text": text,
        "reason": None,
        "wikidata_id": qid,
        "page_id": page_id,
        "observed_revision_id": revid,
        "observed_revision_at": observed_at,
        "page_url": url,
        "observed_revision_url": f"https://en.wikipedia.org/w/index.php?oldid={revid}",
        "fetched_at": timezone.now().isoformat(),
        "shortened": shortened,
        "attribution": "Wikipedia contributors",
        "license": "CC BY-SA 4.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "identity_source_url": f"https://www.wikidata.org/wiki/{qid}",
    }


def _failure(reason, previous):
    if previous and reason not in {
        "identity_mismatch",
        "identity_ambiguous",
        "identity_unavailable",
        "page_unavailable",
    }:
        return {**previous, "status": "stale", "reason": reason}
    return unavailable_biography(reason)


def representative_biography(representative):
    if not getattr(settings, "LEGISLATOR_WIKIPEDIA_ENABLED", False):
        return unavailable_biography("provider_disabled")
    identifier = representative.bioguide_id
    if not isinstance(identifier, str) or not re.fullmatch(r"[A-Z]\d{6}", identifier):
        return unavailable_biography("identity_unavailable")
    key = f"legislator-biography:v1:en:{identifier}"
    owner = uuid4().hex
    locked = False
    try:
        previous = cache.get(key)
        if previous:
            fetched = parse_datetime(previous["fetched_at"])
            age = (timezone.now() - fetched).total_seconds()
            if 0 <= age <= FRESH_SECONDS:
                return previous
            if not 0 <= age <= STALE_SECONDS:
                previous = None
        negative = cache.get(key + ":negative")
        if negative:
            return _failure(negative, previous)
        backoff = cache.get(BACKOFF_KEY)
        if backoff:
            return _failure(backoff, previous)
        if not cache.add(GLOBAL_LOCK, owner, timeout=30):
            return _failure("provider_busy", previous)
        locked = True
        try:
            result = _snapshot(identifier)
        except BiographyUnavailable as error:
            if error.reason in {
                "identity_mismatch",
                "identity_ambiguous",
                "identity_unavailable",
                "page_unavailable",
            }:
                cache.delete(key)
            cache.set(key + ":negative", error.reason, timeout=NEGATIVE_SECONDS)
            if error.retry_seconds:
                cache.set(BACKOFF_KEY, error.reason, timeout=error.retry_seconds)
            return _failure(error.reason, previous)
        except (ValueError, TypeError, KeyError, AttributeError, IndexError):
            cache.set(
                key + ":negative", "invalid_upstream_data", timeout=NEGATIVE_SECONDS
            )
            return _failure("invalid_upstream_data", previous)
        cache.set(key, result, timeout=STALE_SECONDS)
        cache.delete(key + ":negative")
        return result
    except Exception:
        # Cache outage fails closed instead of making uncached public reads.
        return unavailable_biography("cache_unavailable")
    finally:
        if locked:
            try:
                if cache.get(GLOBAL_LOCK) == owner:
                    cache.delete(GLOBAL_LOCK)
            except Exception:
                pass
