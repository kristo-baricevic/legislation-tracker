from dataclasses import dataclass
from .models import RepresentativeCandidate


@dataclass(frozen=True)
class IdentityResolution:
    status: str
    candidate_ids: list[str]


def resolve_candidate(representative_id: int, period: int) -> IdentityResolution:
    rows = [row for row in RepresentativeCandidate.objects.filter(representative_id=representative_id).select_related("candidate") if period in row.periods]
    verified = sorted(row.candidate_id for row in rows if row.verified and row.evidence_url)
    if any(not row.verified or not row.evidence_url for row in rows):
        return IdentityResolution("needs_review", [])
    return IdentityResolution("verified" if verified else "not_found", verified)
