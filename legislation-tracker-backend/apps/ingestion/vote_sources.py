"""Official complete roll-call discovery adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from apps.ingestion.congress_client import (
    CongressAPIError,
    _request,
    _request_senate_xml,
)

SENATE_ROLL_LIST_URL = "https://www.senate.gov/legislative/LIS/roll_call_lists/vote_menu_{congress}_{session}.xml"


@dataclass(frozen=True)
class RollCallRef:
    congress: int
    chamber: str
    session_number: int
    roll_number: int
    source_updated_at: datetime
    source_url: str


@dataclass(frozen=True)
class RollCallPage:
    refs: tuple[RollCallRef, ...]
    next_cursor: str | None


def _date(value) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return (
                parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            )
        except ValueError:
            pass
    return datetime(1970, 1, 1, tzinfo=UTC)


class HouseVoteSource:
    page_size = 250

    def discover_page(
        self, *, congress: int, session_number: int, cursor: str = ""
    ) -> RollCallPage:
        try:
            offset = int(cursor or "0")
        except ValueError as exc:
            raise CongressAPIError(
                "House roll-call cursor must be an integer offset"
            ) from exc
        if offset < 0:
            raise CongressAPIError("House roll-call cursor must not be negative")
        data = _request(
            "GET",
            f"house-vote/{congress}/{session_number}",
            params={"limit": self.page_size, "offset": offset},
        )
        votes = data.get("houseRollCallVotes") or data.get("houseVotes") or []
        if not isinstance(votes, list):
            raise CongressAPIError("House roll-call list returned an invalid payload")
        refs = []
        seen_roll_numbers = set()
        for vote in votes:
            if not isinstance(vote, dict):
                raise CongressAPIError("House roll-call list contains an invalid item")
            try:
                roll_number = int(vote.get("rollNumber") or vote.get("roll_number"))
            except (TypeError, ValueError) as exc:
                raise CongressAPIError(
                    "House roll-call item is missing rollNumber"
                ) from exc
            if roll_number in seen_roll_numbers:
                raise CongressAPIError(
                    "House roll-call list page contains a duplicate roll"
                )
            seen_roll_numbers.add(roll_number)
            refs.append(
                RollCallRef(
                    congress,
                    "house",
                    session_number,
                    roll_number,
                    _date(vote.get("updateDate") or vote.get("startDate")),
                    str(vote.get("url") or ""),
                )
            )
        return RollCallPage(
            refs=tuple(refs),
            next_cursor=(
                str(offset + self.page_size) if len(votes) == self.page_size else None
            ),
        )

    def discover(self, *, congress: int, session_number: int) -> list[RollCallRef]:
        """Return all pages for administrative callers; durable ingestion uses pages."""

        cursor = ""
        seen_cursors = set()
        refs = []
        while True:
            if cursor in seen_cursors:
                raise CongressAPIError("House roll-call list repeated a page cursor")
            seen_cursors.add(cursor)
            page = self.discover_page(
                congress=congress, session_number=session_number, cursor=cursor
            )
            refs.extend(page.refs)
            if page.next_cursor is None:
                return refs
            cursor = page.next_cursor


class SenateVoteSource:
    def discover_page(
        self, *, congress: int, session_number: int, cursor: str = ""
    ) -> RollCallPage:
        if cursor:
            raise CongressAPIError(
                "Senate roll-call source does not support pagination"
            )
        return RollCallPage(
            refs=tuple(self.discover(congress=congress, session_number=session_number)),
            next_cursor=None,
        )

    def discover(self, *, congress: int, session_number: int) -> list[RollCallRef]:
        url = SENATE_ROLL_LIST_URL.format(congress=congress, session=session_number)
        root = _request_senate_xml(url)
        refs = []
        for vote in root.findall(".//vote"):
            raw_number = vote.findtext("vote_number") or vote.findtext(
                "roll_call_vote_number"
            )
            try:
                roll_number = int((raw_number or "").strip())
            except ValueError as exc:
                raise CongressAPIError(
                    "Senate roll-call list has an invalid vote number"
                ) from exc
            refs.append(
                RollCallRef(
                    congress,
                    "senate",
                    session_number,
                    roll_number,
                    _date(vote.findtext("vote_date")),
                    url,
                )
            )
        return refs
