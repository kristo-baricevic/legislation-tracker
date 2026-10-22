import hashlib
import re
import io
import warnings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from .models import ResearchSource, RepresentativePortrait, ResearchSourcePolicy


def may_serve_portrait(portrait):
    return ResearchSourcePolicy.objects.filter(
        representative_id=portrait.representative_id, kind="portrait",
        url=portrait.image_url, approved=True, license=portrait.source.license,
        attribution=portrait.source.attribution,
    ).exists()


def official_portrait_url(url):
    if isinstance(url, str) and re.fullmatch(r"https://www\.congress\.gov/img/member/[a-z]\d{6}(?:_\d+)?\.(?:jpg|jpeg|png)", url):
        return url
    return None


def sanitize_portrait(body):
    from PIL import Image, ImageOps, UnidentifiedImageError
    if len(body) > 4_000_000:
        raise ValueError("portrait_size_limit")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(body), formats=["PNG", "JPEG"]) as source:
                if source.width * source.height > 8_000_000 or max(source.size) > 8000:
                    raise ValueError("portrait_dimensions_limit")
                source.load()
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((800, 800))
                # New pixels only: no EXIF, XMP, ICC or source metadata survives.
                clean = Image.new("RGB", image.size)
                clean.paste(image)
                output = io.BytesIO()
                clean.save(output, format="PNG")
                return output.getvalue(), clean.width, clean.height
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError("invalid_portrait") from None


def prepare_portrait(policy):
    from .sources import fetch_bytes
    if not policy.approved or not policy.license:
        return None
    policy.full_clean()
    return sanitize_portrait(fetch_bytes(policy.url, "www.congress.gov", 4_000_000, {"image/png", "image/jpeg"}))


def save_portrait(rep, depiction, prepared=None, policy=None):
    url = official_portrait_url(depiction.get("imageUrl"))
    if not url or url.split("/member/")[1][:7] != rep.bioguide_id.lower():
        return None
    approved = policy and policy.approved and policy.url == url and policy.representative_id == rep.pk
    if approved:
        policy.full_clean()
    body = prepared[0] if prepared and approved else None
    digest = hashlib.sha256(body if body else url.encode()).hexdigest()
    old = RepresentativePortrait.objects.filter(representative=rep, content_hash=digest).order_by("-id").first()
    if old:
        return old
    key = ""
    if body:
        key = f"research/portraits/{rep.bioguide_id}/{digest}.png"
        if not default_storage.exists(key):
            key = default_storage.save(key, ContentFile(body))
    source = ResearchSource.objects.create(provider="congress", url=url, content_hash=digest, attribution=policy.attribution if approved else depiction.get("attribution", "Congress.gov member portrait"), license=policy.license if approved else "")
    return RepresentativePortrait.objects.create(representative=rep, source=source, image_url=url, object_key=key, content_hash=digest, mime_type="image/png" if body else "", width=prepared[1] if body else None, height=prepared[2] if body else None)
