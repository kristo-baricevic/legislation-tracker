from dataclasses import dataclass
import re
import unicodedata
from difflib import SequenceMatcher
from .models import ConfirmedCandidate, RepresentativeCandidate
from apps.congress.names import normalize_person_name


def candidate_search_name(rep):
    return normalize_person_name(rep.name)


def name_parts(name):
    normalized = unicodedata.normalize("NFKD", normalize_person_name(name)).casefold()
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


def split_name(name):
    name = normalize_person_name(name)
    if "," in name:
        surname, given = name.split(",", 1)
    else:
        given, _, surname = name.rpartition(" ")
    return surname.strip(), given.strip()


def surname_query(rep):
    surname = rep.last_name or split_name(rep.name)[0]
    return "".join(c for c in unicodedata.normalize("NFKD", surname) if not unicodedata.combining(c))


def review_choices(rep, rows):
    surname = name_parts(surname_query(rep))
    given = name_parts(rep.first_name or split_name(rep.name)[1])
    office = {"senate": "S", "house": "H"}.get(rep.chamber)
    choices = {}
    for row in rows:
        cid = str(row.get("candidate_id", ""))
        if not office or not re.fullmatch(office + r"\d[A-Z]{2}\d{5}", cid):
            continue
        if row.get("office") != office or row.get("state") != rep.state:
            continue
        district = str(row.get("district") or "")
        if office == "H" and (not district.isdigit() or not str(rep.district).isdigit() or int(district) != int(rep.district)):
            continue
        name = normalize_person_name(row.get("name"))
        family, first = split_name(name)
        if not surname or name_parts(family) != surname:
            continue
        if not any(SequenceMatcher(None, a, b).ratio() >= 0.8 for a in given for b in name_parts(first) if min(len(a), len(b)) >= 2):
            continue
        choices[cid] = dict(candidate_id=cid, name=name[:255], state=rep.state, office=office, district=district)
    return sorted(choices.values(), key=lambda choice: (choice["name"], choice["candidate_id"]))


@dataclass(frozen=True)
class IdentityResolution:
    status: str
    candidate_ids: list[str]


def resolve_candidate(representative_id: int, period: int) -> IdentityResolution:
    confirmed = ConfirmedCandidate.objects.filter(representative_id=representative_id, period=period).values_list("candidate_id", flat=True).first()
    # Confirmation identifies the reader's choice. Staff control its validity
    # through the same period-scoped mapping as an exact match.
    rows = [row for row in RepresentativeCandidate.objects.filter(representative_id=representative_id).select_related("candidate") if period in row.periods or period in row.candidate.reporting_periods.get("periods", [])]
    verified = sorted(row.candidate_id for row in rows if row.verified and row.evidence_url)
    if confirmed in verified:
        return IdentityResolution("verified", [confirmed])
    if any(not row.verified or not row.evidence_url for row in rows):
        return IdentityResolution("needs_review", [])
    return IdentityResolution("verified" if verified else "not_found", verified)
