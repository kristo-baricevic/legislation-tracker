"""Descriptive representative metrics backed by persisted roll-call data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from django.db.models import Max, Min, Q

from .current import congress_date_bounds, current_congress, current_congress_session
from .models import BillCosponsor, CommitteeMembership, Representative, Vote, VoteRecord

CAST_POSITIONS = {"yes", "no", "present", "other"}


@dataclass(frozen=True)
class ServiceScope:
    chamber: str
    session_number: int
    start_at: datetime
    end_at: datetime
    full_session: bool


@dataclass(frozen=True)
class RepresentativeInsight:
    representative_id: int
    congress: int
    total_roll_calls: int
    ingested_roll_calls: int
    participation_numerator: int
    participation_denominator: int
    participation_rate: float | None
    position_counts: dict[str, int]
    first_vote_at: object | None
    last_vote_at: object | None
    coverage_complete: bool
    coverage_reason: str | None
    discovered_roll_calls: int
    sponsored_bill_count: int
    active_cosponsored_bill_count: int
    committee_count: int


@dataclass(frozen=True)
class RepresentativeComparison:
    left_representative_id: int
    right_representative_id: int
    congress: int
    shared_vote_count: int
    agree_count: int
    disagreement_count: int
    excluded_shared_vote_count: int
    agreement_rate: float | None
    coverage_complete: bool
    reason: str | None
    shared_votes: tuple[dict, ...]
    returned_shared_vote_count: int
    shared_votes_truncated: bool


def _service_scopes(*, representative: Representative, congress: int):
    congress_start, congress_end = congress_date_bounds(congress)
    terms = list(
        representative.service_terms.filter(start_date__lt=congress_end)
        .filter(Q(end_date__isnull=True) | Q(end_date__gt=congress_start))
        .order_by("start_date", "id")
    )
    if not terms and representative.is_current and congress == current_congress():
        terms = [
            type(
                "CurrentService",
                (),
                {
                    "chamber": representative.chamber,
                    "start_date": congress_start,
                    "end_date": congress_end,
                },
            )()
        ]
    session_boundaries = (
        (1, congress_start, congress_start.replace(year=congress_start.year + 1)),
        (2, congress_start.replace(year=congress_start.year + 1), congress_end),
    )
    scopes = []
    for term in terms:
        term_end = term.end_date or congress_end
        for session_number, session_start, session_end in session_boundaries:
            start = max(term.start_date, session_start)
            end = min(term_end, session_end)
            if start >= end:
                continue
            scopes.append(
                ServiceScope(
                    chamber=term.chamber,
                    session_number=session_number,
                    start_at=datetime.combine(start, datetime.min.time(), tzinfo=UTC),
                    end_at=datetime.combine(end, datetime.min.time(), tzinfo=UTC),
                    full_session=start == session_start and end == session_end,
                )
            )
    return tuple(scopes)


def _votes_for_scopes(*, congress: int, scopes: tuple[ServiceScope, ...]):
    filters = Q(pk__in=[])
    for scope in scopes:
        filters |= Q(
            chamber=scope.chamber,
            vote_date__gte=scope.start_at,
            vote_date__lt=scope.end_at,
        )
    return Vote.objects.filter(filters, congress=congress)


def _coverage(
    *,
    representative: Representative,
    congress: int,
    votes,
    scopes: tuple[ServiceScope, ...],
) -> tuple[bool, str | None, int]:
    """Only exhausted authoritative source state makes a claim complete."""

    from apps.ingestion.models import (
        IngestionWorkItem,
        IngestionWorkStatus,
        RollCallIngestionState,
    )

    active_congress = current_congress()
    if congress > active_congress:
        return False, "Roll-call discovery cannot cover a future Congress.", 0
    if not scopes:
        return False, "Service-term history is unavailable for this Congress.", 0
    active_session = (
        current_congress_session() if congress == active_congress else 2
    )
    applicable = {
        (scope.chamber, scope.session_number)
        for scope in scopes
        if scope.session_number <= active_session
    }
    state_filter = Q(pk__in=[])
    for chamber, session_number in applicable:
        state_filter |= Q(chamber=chamber, session_number=session_number)
    states = RollCallIngestionState.objects.filter(state_filter, congress=congress)
    state_rows = list(
        states.values(
            "chamber",
            "session_number",
            "discovered_roll_count",
            "source_exhausted_at",
        )
    )
    if {
        (row["chamber"], row["session_number"]) for row in state_rows
    } != applicable:
        return (
            False,
            "Roll-call discovery has not started for every applicable session.",
            sum(row["discovered_roll_count"] for row in state_rows),
        )
    discovered = sum(row["discovered_roll_count"] for row in state_rows)
    if any(row["source_exhausted_at"] is None for row in state_rows):
        return False, "Roll-call discovery has not reached the source end.", discovered
    persisted = votes.count()
    work_filter = Q(pk__in=[])
    for chamber, session_number in applicable:
        work_filter |= Q(
            payload_json__chamber=chamber,
            payload_json__session_number=session_number,
        )
    open_work = IngestionWorkItem.objects.filter(
        work_filter,
        kind="roll_call_vote",
        congress=congress,
        status__in=[
            IngestionWorkStatus.PENDING,
            IngestionWorkStatus.DISPATCHED,
            IngestionWorkStatus.PROCESSING,
            IngestionWorkStatus.BLOCKED,
            IngestionWorkStatus.DEAD,
        ],
    ).exists()
    covers_full_sessions = all(
        any(
            scope.chamber == chamber
            and scope.session_number == session_number
            and scope.full_session
            for scope in scopes
        )
        for chamber, session_number in applicable
    )
    if covers_full_sessions and persisted != discovered:
        return False, "Persisted roll calls do not match the discovered source total.", discovered
    if open_work:
        return False, "Some discovered roll calls are still unresolved.", discovered
    return True, None, discovered


def representative_summary(*, representative: Representative, congress: int) -> RepresentativeInsight:
    scopes = _service_scopes(representative=representative, congress=congress)
    votes = _votes_for_scopes(congress=congress, scopes=scopes)
    records = VoteRecord.objects.filter(vote__in=votes, representative=representative)
    total = votes.count()
    position_counts = {
        position: records.filter(position=position).count()
        for position in ("yes", "no", "present", "not_voting", "other")
    }
    participation = sum(position_counts[position] for position in CAST_POSITIONS)
    date_bounds = records.aggregate(first=Min("vote__vote_date"), last=Max("vote__vote_date"))
    sponsored = representative.sponsored_bills.filter(session=congress).count()
    cosponsored = BillCosponsor.objects.filter(
        representative=representative,
        bill__session=congress,
        withdrawn_at__isnull=True,
    ).count()
    committees = CommitteeMembership.objects.filter(
        representative=representative,
        congress=congress,
        is_current=True,
    ).count()
    coverage_complete, coverage_reason, discovered_roll_calls = _coverage(
        representative=representative,
        congress=congress,
        votes=votes,
        scopes=scopes,
    )
    return RepresentativeInsight(
        representative_id=representative.id,
        congress=congress,
        total_roll_calls=total,
        ingested_roll_calls=total,
        participation_numerator=participation,
        participation_denominator=total,
        participation_rate=round(participation / total, 4) if total else None,
        position_counts=position_counts,
        first_vote_at=date_bounds["first"],
        last_vote_at=date_bounds["last"],
        coverage_complete=coverage_complete,
        coverage_reason=coverage_reason,
        discovered_roll_calls=discovered_roll_calls,
        sponsored_bill_count=sponsored,
        active_cosponsored_bill_count=cosponsored,
        committee_count=committees,
    )


def compare_representatives(*, left: Representative, right: Representative, congress: int) -> RepresentativeComparison:
    if left.id == right.id:
        raise ValueError("Choose two different representatives.")
    left_scopes = _service_scopes(representative=left, congress=congress)
    right_scopes = _service_scopes(representative=right, congress=congress)
    if not ({scope.chamber for scope in left_scopes} & {scope.chamber for scope in right_scopes}):
        return RepresentativeComparison(
            left_representative_id=left.id,
            right_representative_id=right.id,
            congress=congress,
            shared_vote_count=0,
            agree_count=0,
            disagreement_count=0,
            excluded_shared_vote_count=0,
            agreement_rate=None,
            coverage_complete=False,
            reason="Representatives serve in different chambers.",
            shared_votes=(),
            returned_shared_vote_count=0,
            shared_votes_truncated=False,
        )
    left_positions = dict(
        VoteRecord.objects.filter(
            representative=left,
            vote__in=_votes_for_scopes(congress=congress, scopes=left_scopes),
        ).values_list("vote_id", "position")
    )
    right_positions = dict(
        VoteRecord.objects.filter(
            representative=right,
            vote__in=_votes_for_scopes(congress=congress, scopes=right_scopes),
        ).values_list("vote_id", "position")
    )
    shared = sorted(set(left_positions) & set(right_positions))
    eligible = [
        vote_id
        for vote_id in shared
        if left_positions[vote_id] in {"yes", "no"}
        and right_positions[vote_id] in {"yes", "no"}
    ]
    agree = sum(left_positions[vote_id] == right_positions[vote_id] for vote_id in eligible)
    left_summary = representative_summary(representative=left, congress=congress)
    right_summary = representative_summary(representative=right, congress=congress)
    shared_vote_rows = list(
        Vote.objects.filter(pk__in=eligible).order_by("-vote_date", "-id")[:100]
    )
    return RepresentativeComparison(
        left_representative_id=left.id,
        right_representative_id=right.id,
        congress=congress,
        shared_vote_count=len(eligible),
        agree_count=agree,
        disagreement_count=len(eligible) - agree,
        excluded_shared_vote_count=len(shared) - len(eligible),
        agreement_rate=round(agree / len(eligible), 4) if eligible else None,
        coverage_complete=left_summary.coverage_complete and right_summary.coverage_complete,
        reason=None if eligible else "No shared yes/no roll calls are available.",
        shared_votes=tuple(
            {
                "vote_id": vote.id,
                "bill_id": vote.bill_id,
                "vote_date": vote.vote_date,
                "question": vote.question,
                "result": vote.result,
                "left_position": left_positions[vote.id],
                "right_position": right_positions[vote.id],
            }
            for vote in shared_vote_rows
        ),
        returned_shared_vote_count=len(shared_vote_rows),
        shared_votes_truncated=len(eligible) > len(shared_vote_rows),
    )
