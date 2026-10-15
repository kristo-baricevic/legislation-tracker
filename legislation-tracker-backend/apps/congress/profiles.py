"""Neutral profiles over stored evidence; no enrichment or inferred election dates."""

from dataclasses import asdict

from django.db.models import Q

from .current import congress_date_bounds
from .insights import _coverage, _service_scopes, _votes_for_scopes
from .models import VoteRecord
from .profile_sources import bioguide_url


def recorded_votes(representative, congress, chamber=None):
    records = VoteRecord.objects.filter(
        representative=representative, vote__congress=congress
    )
    if chamber:
        records = records.filter(vote__chamber=chamber)
    return (
        records.select_related("vote", "vote__bill", "vote__bill__sponsor")
        .prefetch_related("vote__bill__bill_topics__topic")
        .order_by("-vote__vote_date", "-vote_id", "-id")
    )


def vote_coverage(representative, congress, chamber=None):
    records = recorded_votes(representative, congress, chamber)
    scopes = _service_scopes(representative=representative, congress=congress)
    legacy_votes = _votes_for_scopes(congress=congress, scopes=scopes)
    complete, reason, discovered = _coverage(
        representative=representative,
        congress=congress,
        votes=legacy_votes,
        scopes=scopes,
    )
    chambers = (
        {chamber}
        if chamber
        else set(records.values_list("vote__chamber", flat=True).distinct())
        | {scope.chamber for scope in scopes}
    )
    providers = []
    if "house" in chambers:
        providers.append(
            {
                "chamber": "house",
                "description": "House API: legislation-linked votes in Congresses 118 and 119 only; other House votes are outside this provider's documented scope.",
                "source_url": "https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/HouseRollCallVoteEndpoint.md#coverage",
                "historical_availability": (
                    "known" if congress in (118, 119) else "unknown"
                ),
            }
        )
    if "senate" in chambers:
        providers.append(
            {
                "chamber": "senate",
                "description": "Official Senate session-list roll calls, including votes without bills. Historical source availability and member-position completeness have not been verified.",
                "source_url": "https://www.senate.gov/legislative/votes_new.htm",
                "historical_availability": "unknown",
            }
        )
    return {
        "scope": {"congress": congress, "chamber": chamber},
        "stored_record_count": records.count(),
        "member_position_completeness": "unknown",
        "unknown_session_record_count": records.filter(
            vote__session_number__isnull=True
        ).count(),
        "provider_scopes": providers,
        "legacy_ingestion_check": {
            "scopes": [asdict(scope) for scope in scopes[:200]],
            "coverage_complete": complete,
            "reason": reason,
            "discovered_count": discovered,
            "persisted_count": legacy_votes.count(),
            "notice": "These service-window ingestion checks do not establish member-position or full provider completeness."
            + (
                " Only the first 200 derived service windows are shown."
                if len(scopes) > 200
                else ""
            ),
        },
    }


def unavailable_fact(reason):
    return {
        "status": "unavailable",
        "value": None,
        "precision": None,
        "reason": reason,
        "source_url": None,
        "retrieved_at": None,
    }


def representative_profile(representative, congress, chamber=None):
    start, end = congress_date_bounds(congress)
    terms = (
        representative.service_terms.filter(start_date__year__lte=end.year)
        .filter(Q(end_date__isnull=True) | Q(end_date__year__gte=start.year))
        .order_by("start_date", "id")
    )
    if chamber:
        terms = terms.filter(chamber=chamber)
    bounded_terms = list(terms[:101])
    observations = [
        {
            "id": term.id,
            "chamber": term.chamber,
            "state": term.state or None,
            "district": term.district,
            "start_year": term.start_date.year,
            "end_year": term.end_date.year if term.end_date else None,
            "source_url": bioguide_url(representative.bioguide_id),
            "retrieved_at": None,
        }
        for term in bounded_terms[:100]
    ]
    chambers = (
        [chamber]
        if chamber
        else sorted({term["chamber"] for term in observations}) or [None]
    )
    return {
        "schema_version": "legislator-profile-v1",
        "scope": {"congress": congress, "chamber": chamber},
        "identity": {
            "id": representative.id,
            "bioguide_id": representative.bioguide_id,
            "name": representative.name,
            "is_current": representative.is_current,
            "latest_affiliation": {
                "chamber": representative.chamber,
                "party": representative.party,
                "state": representative.state,
                "district": representative.district,
            },
            "last_seen_at": representative.last_seen_at,
            "source_url": bioguide_url(representative.bioguide_id),
        },
        "service": {
            "status": "available" if observations else "unavailable",
            "precision": "year",
            "observations": observations,
            "notice": "Stored service years may overlap the selected Congress, including uncertain boundary years. Exact election, appointment and term-start dates and historical completeness are unverified."
            + (
                " Only the first 100 service observations are shown."
                if len(bounded_terms) > 100
                else ""
            ),
        },
        "elections": [
            {
                "chamber": value,
                "first_elected": unavailable_fact(
                    "official_election_source_not_connected"
                ),
                "most_recent_election_won": unavailable_fact(
                    "official_election_source_not_connected"
                ),
                "term_start": unavailable_fact("exact_official_term_start_unverified"),
            }
            for value in chambers
        ],
        "donors": {
            "status": "unavailable",
            "reason": "source_not_configured",
            "cycle": None,
            "reporting_period": None,
            "currency": None,
            "source_url": None,
            "methodology": None,
            "donors": [],
        },
        "coverage": vote_coverage(representative, congress, chamber),
    }
