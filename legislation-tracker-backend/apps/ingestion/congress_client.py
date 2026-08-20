"""
Congress.gov API v3 client for ingestion.
Uses CONGRESS_API_KEY from Django settings. Base URL: https://api.congress.gov/v3.
"""
import logging
import time
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

SENATE_VOTE_URL_TEMPLATE = (
    "https://www.senate.gov/legislative/LIS/roll_call_votes/"
    "vote{congress}{session}/vote_{congress}_{session}_{roll_number:05d}.xml"
)
SENATE_CURRENT_MEMBERS_URL = (
    "https://www.senate.gov/general/contact_information/senators_cfm.xml"
)
STATE_CODES = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}


class CongressAPIError(Exception):
    """Raised when Congress API returns non-2xx. Celery can retry on this."""

    def __init__(self, message, status_code=None, response_text=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


def _get_api_key():
    return getattr(settings, "CONGRESS_API_KEY", "") or ""


def _request(method, path, params=None):
    base = "https://api.congress.gov/v3"
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    api_key = _get_api_key()
    params = dict(params or {})
    params.setdefault("format", "json")
    if not api_key:
        logger.warning(
            "CONGRESS_API_KEY is not set. Set it in legislation-tracker-backend/.env and restart the Celery worker."
        )
    if api_key:
        params.setdefault("api_key", api_key)
    logger.debug("Congress API request: %s %s (params keys: %s)", method, path, list(params.keys()) if params else [])
    resp = requests.request(method, url, params=params, timeout=30)
    if not resp.ok:
        logger.error(
            "Congress API error: %s %s -> %s %s",
            method, path, resp.status_code, (resp.text[:200] if resp.text else ""),
        )
        raise CongressAPIError(
            f"Congress API error: {resp.status_code}",
            status_code=resp.status_code,
            response_text=resp.text[:500] if resp.text else None,
        )
    return resp.json()


def _throttle():
    """Optional: small delay between requests to avoid rate limits."""
    time.sleep(0.3)


def bill_list(congress, bill_type, from_date_time=None, limit=250, offset=0):
    """
    GET /bill/{congress}/{billType}?sort=updateDate+desc&limit=...&offset=...&fromDateTime=...
    Returns list of items with congress, type, number, updateDate (for cursor).
    """
    bill_type = (bill_type or "hr").lower()
    params = {"sort": "updateDate desc", "limit": limit, "offset": offset}
    if from_date_time:
        params["fromDateTime"] = from_date_time
    data = _request("GET", f"bill/{congress}/{bill_type}", params=params)
    _throttle()
    bills = data.get("bills") or []
    out = []
    for b in bills:
        # API can return flat or nested (bill.number, bill.updateDate)
        inner = b.get("bill", b)
        num = inner.get("number")
        if num is None:
            num = b.get("number")
        update_date = inner.get("updateDateIncludingText") or inner.get("updateDate") or b.get("updateDateIncludingText") or b.get("updateDate")
        out.append({
            "congress": congress,
            "type": bill_type,
            "number": str(num) if num is not None else "",
            "updateDate": update_date,
        })
    logger.info(
        "bill_list: congress=%s bill_type=%s offset=%s from_date_time=%s -> %s bills (raw response had %s items)",
        congress, bill_type, offset, from_date_time, len(out), len(bills),
    )
    if bills and not out:
        logger.warning("bill_list: API returned %s raw items but parsed 0; check response shape.", len(bills))
    return out


def bill_detail(congress, bill_type, bill_number):
    """GET /bill/{congress}/{billType}/{billNumber}. Returns full bill object."""
    bill_type = (bill_type or "hr").lower()
    logger.debug("bill_detail: congress=%s bill_type=%s bill_number=%s", congress, bill_type, bill_number)
    data = _request("GET", f"bill/{congress}/{bill_type}/{bill_number}")
    _throttle()
    return data.get("bill") or data


def bill_actions(congress, bill_type, bill_number, limit=250):
    """Return every action for a bill, including recorded roll-call references."""
    bill_type = (bill_type or "hr").lower()
    offset = 0
    actions = []
    while True:
        data = _request(
            "GET",
            f"bill/{congress}/{bill_type}/{bill_number}/actions",
            params={"limit": limit, "offset": offset},
        )
        _throttle()
        page = data.get("actions") or []
        if not isinstance(page, list):
            raise CongressAPIError("Congress bill actions returned an invalid actions payload")
        actions.extend(action for action in page if isinstance(action, dict))
        if len(page) < limit:
            break
        offset += limit
    return actions


def bill_text_list(congress, bill_type, bill_number):
    """
    GET /bill/{congress}/{billType}/{billNumber}/text.
    Returns list of text versions with labels and URLs for BillDocument.
    """
    bill_type = (bill_type or "hr").lower()
    data = _request("GET", f"bill/{congress}/{bill_type}/{bill_number}/text")
    _throttle()
    # API may return { "textVersions": [ { "type": "...", "url": "..." }, ... ] }
    versions = data.get("textVersions") or data.get("text") or []
    if isinstance(versions, dict):
        versions = versions.get("count", []) or []
    result = []
    for v in versions if isinstance(versions, list) else []:
        label = v.get("type") or v.get("version") or v.get("label") or "unknown"
        url = v.get("url")
        if not url and isinstance(v.get("format"), dict):
            url = v.get("format", {}).get("url")
        if not url and isinstance(v.get("formats"), list):
            for f in v.get("formats", []):
                if f.get("url"):
                    url = f["url"]
                    break
        result.append({"version_label": str(label), "url": url or ""})
    logger.info(
        "bill_text_list: congress=%s bill_type=%s bill_number=%s -> %s versions",
        congress, bill_type, bill_number, len(result),
    )
    return result


def _as_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("item", "results", "members"):
            nested = value.get(key)
            if isinstance(nested, list):
                return nested
    return []


def _safe_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _roll_call_member_results(payload, chamber):
    body = payload.get(f"{chamber}RollCallVoteMemberVotes") or payload
    return _as_list(body.get("results") if isinstance(body, dict) else [])


def _roll_call_members(payload, chamber):
    results = _roll_call_member_results(payload, chamber)
    members = []
    for member in results:
        if not isinstance(member, dict):
            continue
        bioguide_id = member.get("bioguideID") or member.get("bioguideId")
        if not bioguide_id:
            continue
        first_name = str(member.get("firstName") or "").strip()
        last_name = str(member.get("lastName") or "").strip()
        name = " ".join(part for part in (first_name, last_name) if part) or str(
            bioguide_id
        )
        vote_cast = str(member.get("voteCast") or "").lower()
        position = {
            "aye": "yes",
            "yea": "yes",
            "yes": "yes",
            "nay": "no",
            "no": "no",
            "present": "present",
            "not voting": "not_voting",
        }.get(vote_cast, vote_cast or "not_voting")
        members.append(
            {
                "bioguideId": str(bioguide_id),
                "name": name,
                "party": str(member.get("voteParty") or "")[:50],
                "state": str(member.get("voteState") or "")[:2],
                "chamber": chamber,
                "position": position,
            }
        )
    return members


def _request_senate_xml(url):
    response = requests.get(url, timeout=30)
    if not response.ok:
        raise CongressAPIError(
            f"Senate roll-call source error: {response.status_code}",
            status_code=response.status_code,
            response_text=(response.text or "")[:500],
        )
    try:
        return ElementTree.fromstring(response.content)
    except ElementTree.ParseError as exc:
        raise CongressAPIError("Senate roll-call source returned invalid XML") from exc


def _xml_text(element, tag):
    value = element.findtext(tag)
    return value.strip() if value else ""


def _senate_member_key(first_name, last_name, state):
    first = _normalized_member_name(first_name).split()
    return (
        (first[0] if first else "").lower(),
        _normalized_member_name(last_name),
        (state or "").strip().upper(),
    )


def _senate_member_fallback_key(last_name, state):
    return (
        _normalized_member_name(last_name),
        (state or "").strip().upper(),
    )


def _state_code(value):
    state = str(value or "").strip()
    if len(state) == 2:
        return state.upper()
    return STATE_CODES.get(state.casefold(), state.upper())


def _member_summary_name_parts(member):
    first_name = str(member.get("firstName") or "").strip()
    last_name = str(member.get("lastName") or "").strip()
    if first_name and last_name:
        return first_name, last_name
    name = str(member.get("name") or "").strip()
    if "," not in name:
        return "", ""
    last_name, given_names = (part.strip() for part in name.split(",", 1))
    first_name = given_names.split(maxsplit=1)[0] if given_names else ""
    return first_name, last_name


def _member_summary_is_senator(member):
    chamber = str(member.get("chamber") or "").casefold()
    if chamber:
        return chamber == "senate"
    terms = member.get("terms") or []
    if isinstance(terms, dict):
        terms = terms.get("item") or terms.get("terms") or []
    return isinstance(terms, list) and any(
        isinstance(term, dict)
        and str(term.get("chamber") or "").casefold() == "senate"
        for term in terms
    )


def _normalized_member_name(value):
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", value or "")
        if not unicodedata.combining(char)
    ).strip().casefold()


def _senate_bioguide_ids(root):
    exact_matches = {}
    fallback_matches = {}
    ambiguous_fallbacks = set()
    for member in root.findall("./member"):
        first_name = _xml_text(member, "first_name")
        last_name = _xml_text(member, "last_name")
        state = _xml_text(member, "state")
        key = _senate_member_key(
            first_name,
            last_name,
            state,
        )
        bioguide_id = _xml_text(member, "bioguide_id")
        if all(key) and bioguide_id:
            exact_matches[key] = bioguide_id
            fallback_key = _senate_member_fallback_key(last_name, state)
            previous_bioguide_id = fallback_matches.get(fallback_key)
            if previous_bioguide_id and previous_bioguide_id != bioguide_id:
                ambiguous_fallbacks.add(fallback_key)
            else:
                fallback_matches[fallback_key] = bioguide_id
    return (
        exact_matches,
        {
            key: bioguide_id
            for key, bioguide_id in fallback_matches.items()
            if key not in ambiguous_fallbacks
        },
    )


@lru_cache(maxsize=16)
def _historical_senate_bioguide_ids(congress):
    """Map former members of a Congress to Bioguide IDs for Senate votes."""
    exact_matches = {}
    fallback_matches = {}
    ambiguous_fallbacks = set()
    offset = 0
    page_size = 250

    while True:
        page = member_list(
            congress,
            current_member=False,
            limit=page_size,
            offset=offset,
        )
        for member in page:
            if not isinstance(member, dict):
                continue
            if not _member_summary_is_senator(member):
                continue
            first_name, last_name = _member_summary_name_parts(member)
            state = _state_code(member.get("state"))
            bioguide_id = str(member.get("bioguideId") or "").strip()
            key = _senate_member_key(first_name, last_name, state)
            if not all(key) or not bioguide_id:
                continue
            exact_matches[key] = bioguide_id
            fallback_key = _senate_member_fallback_key(last_name, state)
            previous_bioguide_id = fallback_matches.get(fallback_key)
            if previous_bioguide_id and previous_bioguide_id != bioguide_id:
                ambiguous_fallbacks.add(fallback_key)
            else:
                fallback_matches[fallback_key] = bioguide_id
        if len(page) < page_size:
            break
        offset += page_size

    return (
        exact_matches,
        {
            key: bioguide_id
            for key, bioguide_id in fallback_matches.items()
            if key not in ambiguous_fallbacks
        },
    )


def _parse_senate_vote_date(value):
    try:
        local_time = datetime.strptime(
            " ".join(value.split()),
            "%B %d, %Y, %I:%M %p",
        ).replace(tzinfo=ZoneInfo("America/New_York"))
    except ValueError:
        return value
    return local_time.astimezone(timezone.utc).isoformat()


def _senate_vote_detail(congress, session_number, roll_number):
    try:
        vote_number = int(roll_number)
    except (TypeError, ValueError) as exc:
        raise CongressAPIError("Senate roll-call number must be an integer") from exc

    vote_url = SENATE_VOTE_URL_TEMPLATE.format(
        congress=congress,
        session=session_number,
        roll_number=vote_number,
    )
    vote_root = _request_senate_xml(vote_url)
    current_members_root = _request_senate_xml(SENATE_CURRENT_MEMBERS_URL)
    bioguide_ids, fallback_bioguide_ids = _senate_bioguide_ids(
        current_members_root
    )
    historical_bioguide_ids = None
    members = []
    for member in vote_root.findall("./members/member"):
        first_name = _xml_text(member, "first_name")
        last_name = _xml_text(member, "last_name")
        state = _xml_text(member, "state")[:2]
        vote_cast = _xml_text(member, "vote_cast").lower()
        bioguide_id = bioguide_ids.get(
            _senate_member_key(first_name, last_name, state),
        ) or fallback_bioguide_ids.get(
            _senate_member_fallback_key(last_name, state),
        )
        if not bioguide_id:
            if historical_bioguide_ids is None:
                historical_bioguide_ids = _historical_senate_bioguide_ids(congress)
            historical_exact_ids, historical_fallback_ids = historical_bioguide_ids
            bioguide_id = historical_exact_ids.get(
                _senate_member_key(first_name, last_name, state),
            ) or historical_fallback_ids.get(
                _senate_member_fallback_key(last_name, state),
                "",
            )
        members.append(
            {
                "bioguideId": bioguide_id,
                "name": " ".join(part for part in (first_name, last_name) if part)
                or _xml_text(member, "member_full"),
                "party": _xml_text(member, "party")[:50],
                "state": state,
                "chamber": "senate",
                "position": {
                    "aye": "yes",
                    "yea": "yes",
                    "yes": "yes",
                    "nay": "no",
                    "no": "no",
                    "present": "present",
                    "not voting": "not_voting",
                }.get(vote_cast, vote_cast or "not_voting"),
            }
        )

    count = vote_root.find("count")
    _throttle()
    return {
        "date": _parse_senate_vote_date(_xml_text(vote_root, "vote_date")),
        "result": _xml_text(vote_root, "vote_result")
        or _xml_text(vote_root, "vote_question_text")
        or "unknown",
        "yeas": _safe_int(_xml_text(count, "yeas") if count is not None else 0),
        "nays": _safe_int(_xml_text(count, "nays") if count is not None else 0),
        "members": members,
    }


def vote_detail(congress, chamber, roll_number, *, session_number=None, source_url=None):
    """Return a normalized House or Senate roll-call vote and member positions.

    Congress.gov provides House roll-call endpoints. Senate roll calls are
    normalized from the official Senate XML feed.
    """
    chamber = (chamber or "house").lower()
    if chamber not in ("house", "senate") or session_number in (None, ""):
        source = f" ({source_url})" if source_url else ""
        raise CongressAPIError(
            "Congress.gov roll-call ingestion requires a House or Senate session number"
            f"{source}"
        )

    if chamber == "senate":
        return _senate_vote_detail(congress, session_number, roll_number)

    path = f"house-vote/{congress}/{session_number}/{roll_number}"
    logger.debug(
        "vote_detail: congress=%s chamber=%s session=%s roll_number=%s",
        congress,
        chamber,
        session_number,
        roll_number,
    )
    detail_data = _request("GET", path)
    members = []
    offset = 0
    page_size = 250
    while True:
        member_data = _request(
            "GET",
            f"{path}/members",
            params={"limit": page_size, "offset": offset},
        )
        member_results = _roll_call_member_results(member_data, chamber)
        members.extend(_roll_call_members(member_data, chamber))
        if len(member_results) < page_size:
            break
        offset += page_size
    _throttle()

    detail = detail_data.get(f"{chamber}RollCallVote") or detail_data
    party_totals = _as_list(
        detail.get("votePartyTotal") if isinstance(detail, dict) else []
    )
    return {
        "date": detail.get("startDate") or detail.get("updateDate"),
        "result": detail.get("result") or detail.get("voteQuestion") or "unknown",
        "yeas": sum(
            _safe_int(total.get("yeaTotal"))
            for total in party_totals
            if isinstance(total, dict)
        ),
        "nays": sum(
            _safe_int(total.get("nayTotal"))
            for total in party_totals
            if isinstance(total, dict)
        ),
        "members": members,
    }


def member_list(congress, current_member=True, limit=250, offset=0):
    """List members serving in a Congress, with explicit offset pagination."""
    params = {
        "currentMember": "true" if current_member else "false",
        "limit": limit,
        "offset": offset,
    }
    data = _request("GET", f"member/congress/{congress}", params=params)
    _throttle()
    members = data.get("members") or []
    if not isinstance(members, list):
        raise CongressAPIError("Congress member list returned an invalid members payload")
    return members


def member_detail(bioguide_id):
    """Return the rich member profile used to populate the complete roster."""
    data = _request("GET", f"member/{bioguide_id}")
    _throttle()
    return data.get("member") or data
