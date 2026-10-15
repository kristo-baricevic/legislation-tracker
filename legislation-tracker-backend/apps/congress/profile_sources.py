"""Credential-free reader links projected only from validated public identities."""

import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .current import congress_date_bounds


def bioguide_url(identifier):
    if not isinstance(identifier, str) or not re.fullmatch(r"[A-Z]\d{6}", identifier):
        return None
    return f"https://bioguide.congress.gov/search/bio/{identifier}"


def bill_source_url(bill):
    if bill.jurisdiction != "federal" or not 93 <= bill.session <= 1000:
        return None
    match = re.fullmatch(r"(HR|S) ([1-9]\d{0,6})", bill.bill_number.strip().upper())
    if not match:
        return None
    number = bill.session
    suffix = (
        "th"
        if 10 <= number % 100 <= 20
        else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    )
    kind = {"HR": "house-bill", "S": "senate-bill"}[match[1]]
    return f"https://www.congress.gov/bill/{number}{suffix}-congress/{kind}/{match[2]}"


def vote_source_link(vote):
    if (
        vote.session_number in (1, 2)
        and 1 <= vote.congress <= 1000
        and 1 <= vote.roll_number <= 99999
    ):
        start, _ = congress_date_bounds(vote.congress)
        expected_year = start.year + vote.session_number - 1
        if (
            vote.vote_date.astimezone(ZoneInfo("America/New_York")).year
            == expected_year
        ):
            if vote.chamber == "house":
                return (
                    f"https://clerk.house.gov/Votes/{expected_year}{vote.roll_number}",
                    "roll_call",
                )
            if vote.chamber == "senate":
                return (
                    "https://www.senate.gov/legislative/LIS/roll_call_votes/"
                    f"vote{vote.congress}{vote.session_number}/"
                    f"vote_{vote.congress}_{vote.session_number}_{vote.roll_number:05d}.htm",
                    "roll_call",
                )
    # Never publish authenticated API URLs, unsafe schemes or query parameters.
    try:
        parsed = urlsplit(vote.source_url)
        valid = (
            parsed.scheme == "https"
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
            and not parsed.query
            and not parsed.fragment
        )
    except (TypeError, ValueError):
        valid = False
    if valid and parsed.hostname == "www.senate.gov":
        match = re.fullmatch(
            r"/legislative/LIS/roll_call_lists/vote_menu_(\d{1,4})_([12])\.(?:htm|xml)",
            parsed.path,
        )
        if (
            match
            and int(match[1]) == vote.congress
            and (vote.session_number is None or int(match[2]) == vote.session_number)
        ):
            return vote.source_url, "session_list"
    if valid and parsed.hostname == "clerk.house.gov" and parsed.path == "/Votes":
        return vote.source_url, "session_list"
    return None, "unavailable"
