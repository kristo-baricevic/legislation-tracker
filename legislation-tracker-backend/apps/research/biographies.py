import hashlib
import re
from apps.ingestion.congress_client import STATE_CODES
from .models import ResearchSource, RepresentativeBiography


def complete_sentences(text):
    # Protect abbreviations before splitting, never discard characters inside
    # a sentence (e.g. the periods in "U.S."). Keep only complete endings.
    marker = "\ue000"
    text = text.replace(marker, "")
    protected = re.sub(r"\b(?:[A-Za-z]\.){2,}|\b(?:Dr|Mr|Mrs|Ms|Rep|Sen|Jr|Sr)\.|\b[A-Z]\.(?=\s+[A-Z])",
        lambda match: match.group().replace(".", marker), text)
    return [part.strip().replace(marker, ".") for part in re.split(r"(?<=[.!?])\s+", protected)
            if part.strip().endswith((".", "!", "?"))]


def save_official_biography(rep):
    state = next((name.title() for name, code in STATE_CODES.items() if code == rep.state), rep.state)
    role = "senator" if rep.chamber == "senate" else "representative"
    verb = "is" if rep.is_current else "was"
    text = f"{rep.name} {verb} a U.S. {role} from {state}."
    if rep.chamber == "house" and rep.district:
        text += f" The recorded House district is {rep.district}."
    if rep.party:
        text += f" The member's recorded party is {rep.party}."
    digest = hashlib.sha256(text.encode()).hexdigest()
    previous = RepresentativeBiography.objects.filter(representative=rep, source__provider="congress", source__content_hash=digest).first()
    if previous:
        return previous
    source = ResearchSource.objects.create(provider="congress", url=f"https://bioguide.congress.gov/search/bio/{rep.bioguide_id}", content_hash=hashlib.sha256(text.encode()).hexdigest(), attribution="Biographical Directory of the United States Congress")
    return RepresentativeBiography.objects.create(representative=rep, source=source, text=text, evidence={"kind": "official_service_facts", "bioguide_id": rep.bioguide_id})


def save_excerpt(rep, excerpt):
    # Keep complete sentences rather than making a truncated sentence look whole.
    text = excerpt.get("text") or ""
    sentences = complete_sentences(text)
    text = " ".join(s.strip() for s in sentences[:4]).strip()
    if not text:
        return None
    previous = RepresentativeBiography.objects.filter(representative=rep, source__url=excerpt["observed_revision_url"], text=text, source__license=excerpt["license"], source__attribution=excerpt["attribution"]).first()
    if previous:
        return previous
    source = ResearchSource.objects.create(provider="wikipedia", url=excerpt["observed_revision_url"], revision=str(excerpt["observed_revision_id"]), content_hash=hashlib.sha256(text.encode()).hexdigest(), attribution=excerpt["attribution"], license=excerpt["license"])
    return RepresentativeBiography.objects.create(representative=rep, source=source, text=text, evidence={"kind": "source_excerpt", "wikidata_id": excerpt["wikidata_id"], "source_snapshot": excerpt})


def save_official_excerpt(rep, text, policy):
    digest = hashlib.sha256(text.encode()).hexdigest()
    previous = RepresentativeBiography.objects.filter(representative=rep, source__url=policy.url, source__content_hash=digest, source__license=policy.license, source__attribution=policy.attribution).order_by("-id").first()
    if previous:
        return previous
    # Split only at sentence boundaries; retain the full cleaned source evidence.
    complete = complete_sentences(text)
    if len(complete) < 2:
        return None
    source = ResearchSource.objects.create(provider="official_member", url=policy.url, content_hash=digest, attribution=policy.attribution, license=policy.license)
    return RepresentativeBiography.objects.create(representative=rep, source=source, text=" ".join(complete[:4]), evidence={"kind": "official_excerpt", "full_text": text})
