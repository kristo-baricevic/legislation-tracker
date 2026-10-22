import hashlib
import re
from .models import ResearchSource, RepresentativePortrait


def official_portrait_url(url):
    if isinstance(url, str) and re.fullmatch(r"https://www\.congress\.gov/img/member/[a-z]\d{6}(?:_\d+)?\.(?:jpg|jpeg|png)", url):
        return url
    return None


def save_portrait(rep, depiction):
    url = official_portrait_url(depiction.get("imageUrl"))
    if not url or url.split("/member/")[1][:7] != rep.bioguide_id.lower():
        return None
    source = ResearchSource.objects.create(provider="congress", url=url, content_hash=hashlib.sha256(url.encode()).hexdigest(), attribution=depiction.get("attribution", "Congress.gov member portrait"))
    # Reference the official image; do not copy a photograph before verifying
    # its individual reuse rights. No backend arbitrary-URL fetch or image proxy.
    return RepresentativePortrait.objects.create(representative=rep, source=source, image_url=url)
