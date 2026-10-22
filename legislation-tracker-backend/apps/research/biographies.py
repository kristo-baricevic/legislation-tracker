import hashlib
import re
from apps.ingestion.congress_client import STATE_CODES
from .models import ResearchSource, RepresentativeBiography


def save_official_biography(rep):
    state = next((name.title() for name, code in STATE_CODES.items() if code == rep.state), rep.state)
    role = "senator" if rep.chamber == "senate" else "representative"
    verb = "is" if rep.is_current else "was"
    text = f"{rep.name} {verb} a U.S. {role} from {state}."
    if rep.chamber == "house" and rep.district:
        text += f" The recorded House district is {rep.district}."
    if rep.party:
        text += f" The member's recorded party is {rep.party}."
    source = ResearchSource.objects.create(provider="congress", url=f"https://bioguide.congress.gov/search/bio/{rep.bioguide_id}", content_hash=hashlib.sha256(text.encode()).hexdigest(), attribution="Biographical Directory of the United States Congress")
    return RepresentativeBiography.objects.create(representative=rep, source=source, text=text, evidence={"kind": "official_service_facts", "bioguide_id": rep.bioguide_id})


def save_excerpt(rep, excerpt):
    # Keep complete sentences rather than making a truncated sentence look whole.
    text = excerpt.get("text") or ""
    sentences = re.findall(r"[^.!?]+[.!?](?:\s|$)", text)
    text = " ".join(s.strip() for s in sentences[:4]).strip()
    if not text:
        return None
    source = ResearchSource.objects.create(provider="wikipedia", url=excerpt["observed_revision_url"], revision=str(excerpt["observed_revision_id"]), content_hash=hashlib.sha256(text.encode()).hexdigest(), attribution=excerpt["attribution"], license=excerpt["license"])
    return RepresentativeBiography.objects.create(representative=rep, source=source, text=text, evidence={"kind": "source_excerpt", "wikidata_id": excerpt["wikidata_id"], "source_snapshot": excerpt})
