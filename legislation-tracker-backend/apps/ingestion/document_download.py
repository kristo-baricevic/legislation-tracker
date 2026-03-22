"""
Download bill document bytes from source_url, hash, optional text extraction, upload via Django storage.
Supports MinIO (S3-compatible) or local filesystem via STORAGES in settings.
"""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import re
from io import BytesIO
from typing import Optional, Tuple
from urllib.parse import urlparse

import requests
from botocore.exceptions import ClientError
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def guess_extension(url: str, content_type: Optional[str]) -> str:
    path = urlparse(url).path
    ext = ""
    if "." in path:
        ext = path.rsplit(".", 1)[-1].lower()[:10]
        if ext.isalnum():
            return f".{ext}" if not ext.startswith(".") else ext
    if content_type:
        if "pdf" in content_type:
            return ".pdf"
        if "xml" in content_type:
            return ".xml"
        if "html" in content_type:
            return ".html"
    return ".bin"


def download_url(url: str, timeout: int = 120) -> Tuple[bytes, Optional[str]]:
    """GET url; return (body, content-type header value)."""
    headers = {
        "User-Agent": "LegislationTracker/1.0 (document ingestion; +https://github.com/)",
    }
    resp = requests.get(url, timeout=timeout, headers=headers, allow_redirects=True)
    resp.raise_for_status()
    ct = resp.headers.get("Content-Type")
    if ct and ";" in ct:
        ct = ct.split(";")[0].strip()
    return resp.content, ct


def extract_text_from_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.warning("pypdf not installed; PDF text extraction skipped")
        return ""
    try:
        reader = PdfReader(BytesIO(data))
        parts = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                parts.append(t)
        return "\n".join(parts).strip()
    except Exception as e:
        logger.warning("PDF text extraction failed: %s", e)
        return ""


def extract_text_from_xml_or_html(data: bytes, content_type: str | None) -> str:
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        return ""
    if not text.strip():
        return ""
    # Minimal: strip tags for a rough plain text (Phase 5 can refine)
    if content_type and "html" in content_type:
        text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:500_000]


def ensure_s3_bucket_exists() -> None:
    """Create bucket on MinIO/S3 if missing (no-op for filesystem storage)."""
    if getattr(settings, "USE_LOCAL_DOCUMENT_STORAGE", False):
        return
    import boto3

    bucket = settings.AWS_STORAGE_BUCKET_NAME
    endpoint = settings.AWS_S3_ENDPOINT_URL or None
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or None,
        region_name=getattr(settings, "AWS_S3_REGION_NAME", "us-east-1"),
    )
    try:
        client.head_bucket(Bucket=bucket)
        logger.debug("S3 bucket exists: %s", bucket)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchBucket", "NotFound"):
            logger.info("Creating S3 bucket: %s", bucket)
            if endpoint:
                client.create_bucket(Bucket=bucket)
            else:
                client.create_bucket(
                    Bucket=bucket,
                    CreateBucketConfiguration={
                        "LocationConstraint": settings.AWS_S3_REGION_NAME,
                    },
                )
        else:
            raise


def build_object_key(bill_session: int, bill_number: str, version_label: str, ext: str) -> str:
    """bills/{session}/{bill_number}/{version_label}.{ext}"""
    safe_bn = re.sub(r"[^\w\-]+", "_", bill_number.strip())[:80]
    safe_v = re.sub(r"[^\w\-]+", "_", version_label.strip())[:50]
    if not ext.startswith("."):
        ext = "." + ext
    return f"bills/{bill_session}/{safe_bn}/{safe_v}{ext}"


def upload_and_metadata(
    object_key: str,
    data: bytes,
    content_type: Optional[str],
) -> Tuple[str, int]:
    """
    Save to default_storage; return (stored name/key, size in bytes).
    """
    ensure_s3_bucket_exists()
    ct = content_type or mimetypes.guess_type(object_key)[0] or "application/octet-stream"
    saved_name = default_storage.save(object_key, ContentFile(data))
    size = len(data)
    return saved_name, size
