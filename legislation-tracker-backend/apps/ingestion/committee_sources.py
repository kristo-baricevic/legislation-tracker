"""Fail-closed parsers for the official current committee-roster feeds."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import requests
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from django.conf import settings

from apps.congress.current import current_congress

COMMITTEE_CODE_RE = re.compile(r"^(?:hs|ss|sl|sp|sc|js|jc)[a-z]{2}\d{2}$")
HOUSE_RAW_CODE_RE = re.compile(r"^[A-Za-z]{2}\d{2}$")


class CommitteeRosterError(ValueError):
    """An official roster cannot safely be treated as a complete snapshot."""


class CommitteeRosterTransportError(CommitteeRosterError):
    """A transient transport failure while retrieving an official roster."""


@dataclass(frozen=True)
class CommitteeAssignment:
    bioguide_id: str
    committee_code: str
    committee_name: str
    chamber: str
    parent_code: str | None
    rank: int | None
    role: str
    party_side: str
    source_code: str = ""
    parent_name: str = ""


@dataclass(frozen=True)
class CommitteeRosterSnapshot:
    congress: int
    chamber: str
    published_at: datetime
    source_url: str
    source_hash: str
    assignments: tuple[CommitteeAssignment, ...]


def normalize_committee_system_code(*, source: str, chamber: str, raw_code: str) -> str:
    """Normalize a source code without silently inventing an identity."""

    value = str(raw_code or "").strip().casefold()
    if not value:
        raise CommitteeRosterError("Committee assignment is missing a source code")
    if source == "congress":
        if not COMMITTEE_CODE_RE.fullmatch(value):
            raise CommitteeRosterError(
                f"Invalid Congress.gov committee code: {raw_code}"
            )
        return value
    if source == "house":
        if value.startswith("hs"):
            if not COMMITTEE_CODE_RE.fullmatch(value):
                raise CommitteeRosterError(f"Invalid House committee code: {raw_code}")
            return value
        if chamber != "house" or not HOUSE_RAW_CODE_RE.fullmatch(value):
            raise CommitteeRosterError(f"Invalid House committee code: {raw_code}")
        return f"hs{value}"
    if source == "senate":
        if chamber not in {"senate", "joint"} or not COMMITTEE_CODE_RE.fullmatch(value):
            raise CommitteeRosterError(f"Invalid Senate committee code: {raw_code}")
        return value
    raise CommitteeRosterError(f"Unsupported committee source: {source}")


def _parse_xml(raw: bytes):
    try:
        return ElementTree.fromstring(raw)
    except (DefusedXmlException, ElementTree.ParseError) as exc:
        raise CommitteeRosterError(
            "Committee roster source returned invalid XML"
        ) from exc


def _text(element, path: str) -> str:
    return (element.findtext(path) or "").strip()


def _parse_house_published_at(value: str) -> datetime:
    try:
        return datetime.strptime(value.strip(), "%B %d, %Y").replace(tzinfo=UTC)
    except ValueError as exc:
        raise CommitteeRosterError(
            "House roster is missing a valid publish date"
        ) from exc


def _parse_senate_published_at(root) -> datetime:
    value = " ".join(
        part
        for part in (_text(root, "./lastUpdate/date"), _text(root, "./lastUpdate/time"))
        if part
    )
    value = re.sub(r"\s+(?:EDT|EST)$", "", value, flags=re.IGNORECASE)
    for format_string in (
        "%A, %B %d, %Y %I:%M:%S %p",
        "%A, %B %d, %Y %I:%M %p",
        "%A, %B %d, %Y",
    ):
        try:
            parsed = datetime.strptime(value, format_string)
            return parsed.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(UTC)
        except ValueError:
            continue
    raise CommitteeRosterError("Senate roster is missing a valid publication timestamp")


def _role(value: str) -> str:
    normalized = value.strip().casefold()
    if not normalized:
        return "member"
    if "ranking" in normalized:
        return "ranking_member"
    if "vice chair" in normalized or "vice-chair" in normalized:
        return "vice_chair"
    if "chair" in normalized:
        return "chair"
    return "other"


def _rank(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise CommitteeRosterError(
            "Committee membership rank must be an integer"
        ) from exc
    if result < 1:
        raise CommitteeRosterError("Committee membership rank must be positive")
    return result


def parse_house_committee_roster(
    raw: bytes, *, source_url: str
) -> CommitteeRosterSnapshot:
    """Parse the Clerk's complete current House member/committee XML feed."""

    root = _parse_xml(raw)
    if root.tag != "MemberData":
        raise CommitteeRosterError("House roster has an unexpected root element")
    try:
        congress = int(_text(root, "./title-info/congress-num"))
    except ValueError as exc:
        raise CommitteeRosterError(
            "House roster is missing its Congress number"
        ) from exc
    published_at = _parse_house_published_at(root.attrib.get("publish-date", ""))
    majority = _text(root, "./title-info/majority")

    committee_metadata: dict[str, tuple[str, str | None, str]] = {}
    for committee in root.findall("./committees/committee"):
        raw_code = committee.attrib.get("comcode", "")
        code = normalize_committee_system_code(
            source="house", chamber="house", raw_code=raw_code
        )
        committee_metadata[code] = (
            _text(committee, "committee-fullname") or code,
            None,
            raw_code,
        )
        for subcommittee in committee.findall("subcommittee"):
            sub_raw_code = subcommittee.attrib.get("subcomcode", "")
            sub_code = normalize_committee_system_code(
                source="house", chamber="house", raw_code=sub_raw_code
            )
            committee_metadata[sub_code] = (
                _text(subcommittee, "subcommittee-fullname") or sub_code,
                code,
                sub_raw_code,
            )
    if not committee_metadata:
        raise CommitteeRosterError("House roster contains no committee definitions")

    assignments: list[CommitteeAssignment] = []
    identities: set[tuple[str, str]] = set()
    for member in root.findall("./members/member"):
        bioguide_id = _text(member, "./member-info/bioguideID")
        source_assignments = list(member.findall("./committee-assignments/committee"))
        source_assignments.extend(
            member.findall("./committee-assignments/subcommittee")
        )
        # The Clerk's current feed includes empty elements for vacancies and
        # non-assignment placeholders. They do not identify a relationship.
        source_assignments = [
            item
            for item in source_assignments
            if item.attrib.get("comcode") or item.attrib.get("subcomcode")
        ]
        if not source_assignments:
            continue
        if not bioguide_id:
            raise CommitteeRosterError(
                "House roster has an assigned member without a Bioguide ID"
            )
        caucus = _text(member, "./member-info/caucus")
        party_side = "majority" if caucus and caucus == majority else "minority"
        for item in source_assignments:
            raw_code = item.attrib.get("comcode") or item.attrib.get("subcomcode") or ""
            code = normalize_committee_system_code(
                source="house", chamber="house", raw_code=raw_code
            )
            metadata = committee_metadata.get(code)
            if metadata is None:
                raise CommitteeRosterError(
                    f"House assignment refers to unknown committee code: {raw_code}"
                )
            name, parent_code, canonical_source_code = metadata
            parent_name = committee_metadata.get(parent_code, ("", None, ""))[0]
            identity = (bioguide_id, code)
            if identity in identities:
                raise CommitteeRosterError(
                    "House roster contains a duplicate assignment"
                )
            identities.add(identity)
            assignments.append(
                CommitteeAssignment(
                    bioguide_id=bioguide_id,
                    committee_code=code,
                    committee_name=name,
                    chamber="house",
                    parent_code=parent_code,
                    parent_name=parent_name,
                    rank=_rank(item.attrib.get("rank")),
                    role=_role(item.attrib.get("leadership", "")),
                    party_side=party_side,
                    source_code=canonical_source_code,
                )
            )
    if not assignments:
        raise CommitteeRosterError("House roster contains no committee assignments")
    return CommitteeRosterSnapshot(
        congress=congress,
        chamber="house",
        published_at=published_at,
        source_url=source_url,
        source_hash=hashlib.sha256(raw).hexdigest(),
        assignments=tuple(assignments),
    )


def parse_senate_committee_roster(
    raw: bytes, *, congress: int, source_url: str
) -> CommitteeRosterSnapshot:
    """Parse Senate.gov's current-senator feed, which includes Bioguide IDs."""

    root = _parse_xml(raw)
    if root.tag != "senators":
        raise CommitteeRosterError("Senate roster has an unexpected root element")
    assignments: list[CommitteeAssignment] = []
    identities: set[tuple[str, str]] = set()
    for senator in root.findall("./senator"):
        bioguide_id = _text(senator, "bioguideId")
        committees = senator.findall("./committees/committee")
        if not committees:
            continue
        if not bioguide_id:
            raise CommitteeRosterError(
                "Senate roster has an assigned member without a Bioguide ID"
            )
        party = _text(senator, "party")
        for committee in committees:
            raw_code = committee.attrib.get("code", "")
            code = normalize_committee_system_code(
                source="senate", chamber="senate", raw_code=raw_code
            )
            identity = (bioguide_id, code)
            if identity in identities:
                raise CommitteeRosterError(
                    "Senate roster contains a duplicate assignment"
                )
            identities.add(identity)
            assignments.append(
                CommitteeAssignment(
                    bioguide_id=bioguide_id,
                    committee_code=code,
                    committee_name=(committee.text or "").strip() or code,
                    chamber="senate",
                    parent_code=None,
                    rank=None,
                    role="member",
                    party_side=party,
                    source_code=raw_code,
                )
            )
    if not assignments:
        raise CommitteeRosterError("Senate roster contains no committee assignments")
    return CommitteeRosterSnapshot(
        congress=congress,
        chamber="senate",
        published_at=_parse_senate_published_at(root),
        source_url=source_url,
        source_hash=hashlib.sha256(raw).hexdigest(),
        assignments=tuple(assignments),
    )


def _read_xml_response(response) -> bytes:
    if not response.ok:
        error_class = (
            CommitteeRosterTransportError
            if response.status_code >= 500
            else CommitteeRosterError
        )
        raise error_class(
            f"Committee roster source returned HTTP {response.status_code}"
        )
    content_type = (response.headers.get("Content-Type") or "").casefold()
    if "xml" not in content_type:
        raise CommitteeRosterError("Committee roster source did not return XML")
    maximum = getattr(settings, "COMMITTEE_ROSTER_MAX_BYTES", 2 * 1024 * 1024)
    declared_size = response.headers.get("Content-Length")
    try:
        if declared_size and int(declared_size) > maximum:
            raise CommitteeRosterError("Committee roster source exceeds the byte limit")
    except ValueError as exc:
        raise CommitteeRosterError(
            "Committee roster has an invalid Content-Length"
        ) from exc
    chunks = []
    size = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        size += len(chunk)
        if size > maximum:
            raise CommitteeRosterError("Committee roster source exceeds the byte limit")
        chunks.append(chunk)
    if not chunks:
        raise CommitteeRosterError("Committee roster source was empty")
    return b"".join(chunks)


def _download_xml(*, url: str) -> bytes:
    try:
        response = requests.get(
            url,
            timeout=getattr(settings, "COMMITTEE_ROSTER_TIMEOUT_SECONDS", 30),
            stream=True,
        )
    except requests.RequestException as exc:
        raise CommitteeRosterTransportError(
            f"Committee roster request failed: {exc}"
        ) from exc
    try:
        return _read_xml_response(response)
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def fetch_house_committee_roster(*, congress: int) -> CommitteeRosterSnapshot:
    url = settings.HOUSE_COMMITTEE_ROSTER_URL
    snapshot = parse_house_committee_roster(_download_xml(url=url), source_url=url)
    if snapshot.congress != congress:
        raise CommitteeRosterError(
            f"House roster is for Congress {snapshot.congress}, not {congress}"
        )
    return snapshot


def fetch_senate_committee_roster(*, congress: int) -> CommitteeRosterSnapshot:
    # Senate's feed is explicitly current-only and does not include Congress in
    # the XML. Reject historical requests rather than relabel current data.
    if congress != current_congress():
        raise CommitteeRosterError(
            "Senate committee roster is available only for the current Congress"
        )
    url = settings.SENATE_COMMITTEE_ROSTER_URL
    return parse_senate_committee_roster(
        _download_xml(url=url), congress=congress, source_url=url
    )
