from dataclasses import dataclass
import re
import unicodedata
from .models import RepresentativeCandidate


def candidate_search_name(rep):
    name = re.sub(r"\s*\[[^\]]*\]\s*$", "", rep.name).strip()
    return re.sub(r"^(?:Rep\.?|Sen\.?|Representative|Senator|Del\.?|Delegate|Resident Commissioner)\s+", "", name, flags=re.I).strip()


def name_parts(name):
    normalized = unicodedata.normalize("NFKD", name).casefold()
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    return sorted(re.findall(r"[a-z]+", normalized))


def verified_match(rep, rows, period, current_period):
    # Current affiliations are not proof of a historical candidate identity.
    if period != current_period or not rep.is_current:
        return None
    matches = []
    for row in rows:
        fec_id = str(row.get("candidate_id", ""))
        if not re.fullmatch(r"[HS]\d[A-Z]{2}\d{5}", fec_id):
            continue
        if name_parts(candidate_search_name(rep)) != name_parts(str(row.get("name", ""))):
            continue
        office = "S" if rep.chamber == "senate" else "H" if rep.chamber == "house" else None
        if not office or row.get("office") != office or row.get("state") != rep.state:
            continue
        if office == "H" and (not str(rep.district).isdigit() or not str(row.get("district", "")).isdigit() or int(rep.district) != int(row["district"])):
            continue
        matches.append(fec_id)
    return matches[0] if len(set(matches)) == 1 else None


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
