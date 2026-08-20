"""
Download bill document bytes from source_url, hash, optional text extraction, upload via Django storage.
Supports MinIO (S3-compatible) or local filesystem via STORAGES in settings.
"""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import re
from html import unescape
from io import BytesIO
from typing import Optional, Tuple
from urllib.parse import urlparse
from xml.etree import ElementTree

import requests
from boto3.exceptions import S3UploadFailedError
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)

_STRUCTURAL_MARKUP_TAG_RE = re.compile(
    r"</?(?:article|body|br|chapter|div|header|item|li|p|paragraph|part|"
    r"section|subsection|table|td|text|th|title|tr)\b[^>]*>",
    re.IGNORECASE,
)
_MARKUP_TAG_RE = re.compile(r"<[^>]+>")
_XML_CONTAINER_TAGS = {"chapter", "part", "subpart", "subtitle", "title"}
_XML_PROVISION_TAGS = {
    "clause",
    "item",
    "paragraph",
    "section",
    "subclause",
    "subparagraph",
    "subsection",
}
_XML_TEXT_TAGS = {"after-quoted-block", "continuation-text", "text"}
_QUOTED_BLOCK_START = "[[QUOTED_BLOCK_START]]"
_QUOTED_BLOCK_END = "[[QUOTED_BLOCK_END]]"


class RetryableDocumentStorageError(Exception):
    """A transient object-storage failure that should use the Celery retry policy."""


_RETRYABLE_STORAGE_ERROR_CODES = {
    "InternalError",
    "RequestLimitExceeded",
    "RequestTimeout",
    "RequestTimeoutException",
    "ServiceUnavailable",
    "SlowDown",
    "Throttling",
    "ThrottlingException",
}


def retryable_storage_error(exc: Exception) -> RetryableDocumentStorageError | None:
    """Return a retry marker for transient Boto errors, otherwise ``None``."""
    if isinstance(exc, (BotoCoreError, S3UploadFailedError)):
        return RetryableDocumentStorageError(str(exc))
    if not isinstance(exc, ClientError):
        return None

    response = exc.response or {}
    error_code = response.get("Error", {}).get("Code", "")
    status_code = response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
    if status_code == 429 or status_code >= 500 or error_code in _RETRYABLE_STORAGE_ERROR_CODES:
        return RetryableDocumentStorageError(str(exc))
    return None


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


def _xml_tag(element: ElementTree.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].casefold()


def _normalized_inline_text(element: ElementTree.Element) -> str:
    return re.sub(r"\s+", " ", "".join(element.itertext())).strip()


def _direct_xml_child_text(element: ElementTree.Element, tag: str) -> str:
    child = next((item for item in element if _xml_tag(item) == tag), None)
    return _normalized_inline_text(child) if child is not None else ""


def _render_congress_xml_element(
    element: ElementTree.Element, lines: list[str]
) -> None:
    tag = _xml_tag(element)
    enum = _direct_xml_child_text(element, "enum")
    heading = _direct_xml_child_text(element, "header")
    direct_text = " ".join(
        value
        for child in element
        if _xml_tag(child) in _XML_TEXT_TAGS
        and (value := _normalized_inline_text(child))
    )

    if tag in _XML_CONTAINER_TAGS:
        label = enum or tag.upper()
        if not label.casefold().startswith(tag):
            label = f"{tag.upper()} {label}"
        lines.append(" ".join(part for part in (label, heading) if part))
    elif tag == "section":
        label = enum.rstrip(".")
        if label:
            lines.append(f"SEC. {label}." + (f" {heading}" if heading else ""))
        if direct_text:
            lines.append(direct_text)
    elif tag in _XML_PROVISION_TAGS:
        marker = enum
        if marker:
            if heading:
                lines.append(
                    f"{marker} {heading}.—" + (direct_text if direct_text else "")
                )
                direct_text = ""
            elif direct_text:
                lines.append(f"{marker} {direct_text}")
                direct_text = ""
            else:
                lines.append(marker)
        if direct_text:
            lines.append(direct_text)

    for child in element:
        child_tag = _xml_tag(child)
        if child_tag in _XML_CONTAINER_TAGS or child_tag in _XML_PROVISION_TAGS:
            _render_congress_xml_element(child, lines)
        elif child_tag == "quoted-block":
            lines.append(_QUOTED_BLOCK_START)
            for quoted_child in child:
                if _xml_tag(quoted_child) in _XML_PROVISION_TAGS:
                    _render_congress_xml_element(quoted_child, lines)
                elif _xml_tag(quoted_child) in _XML_TEXT_TAGS:
                    value = _normalized_inline_text(quoted_child)
                    if value:
                        lines.append(value)
            lines.append(_QUOTED_BLOCK_END)
        elif child_tag in _XML_TEXT_TAGS and tag not in _XML_PROVISION_TAGS:
            value = _normalized_inline_text(child)
            if value:
                lines.append(value)


def _extract_congress_xml(text: str) -> str | None:
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return None
    legislative_body = next(
        (element for element in root.iter() if _xml_tag(element) == "legis-body"),
        None,
    )
    if legislative_body is None:
        return None
    lines: list[str] = []
    for child in legislative_body:
        if _xml_tag(child) in _XML_CONTAINER_TAGS or _xml_tag(child) in _XML_PROVISION_TAGS:
            _render_congress_xml_element(child, lines)
    return "\n".join(line for line in lines if line).strip()


def extract_text_from_xml_or_html(data: bytes, content_type: str | None) -> str:
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        return ""
    if not text.strip():
        return ""
    content_type = (content_type or "").casefold()
    if "xml" in content_type:
        structured_text = _extract_congress_xml(text)
        if structured_text:
            return structured_text[:500_000]
    if "xml" in content_type or "html" in content_type:
        text = _STRUCTURAL_MARKUP_TAG_RE.sub("\n", text)
        text = _MARKUP_TAG_RE.sub("", text)
        text = unescape(text)

    lines = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(r"[\t\f\v ]+", " ", raw_line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)[:500_000]


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
            elif settings.AWS_S3_REGION_NAME == "us-east-1":
                # S3's default region rejects an explicit LocationConstraint.
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
