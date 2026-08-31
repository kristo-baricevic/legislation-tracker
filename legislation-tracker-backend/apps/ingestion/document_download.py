"""
Download bill document bytes from source_url, hash, optional text extraction, upload via Django storage.
Supports MinIO (S3-compatible) or local filesystem via STORAGES in settings.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import re
from dataclasses import dataclass
from html import unescape
from io import BytesIO
from tempfile import SpooledTemporaryFile
from typing import BinaryIO
from urllib.parse import urlparse
from xml.etree import ElementTree

import requests
from boto3.exceptions import S3UploadFailedError
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.core.files.base import ContentFile, File
from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)

_STRUCTURAL_MARKUP_TAG_RE = re.compile(
    r"</?(?:account|appropriations-para|article|body|br|chapter|clause|"
    r"constitution-article|div|division|header|item|li|p|paragraph|part|"
    r"section|subaccount|subchapter|subclause|subdivision|subitem|"
    r"subparagraph|subpart|subsection|subsubaccount|subsubsubaccount|"
    r"subtitle|table|td|text|th|title|tr)\b[^>]*>",
    re.IGNORECASE,
)
_MARKUP_TAG_RE = re.compile(r"<[^>]+>")
_XML_CONTAINER_TAGS = {
    "account",
    "chapter",
    "constitution-article",
    "division",
    "part",
    "subaccount",
    "subchapter",
    "subdivision",
    "subpart",
    "subsubaccount",
    "subsubsubaccount",
    "subtitle",
    "title",
}
_XML_PROVISION_TAGS = {
    "appropriations-para",
    "clause",
    "item",
    "paragraph",
    "section",
    "subclause",
    "subitem",
    "subparagraph",
    "subsection",
}
_XML_STRUCTURAL_TAGS = _XML_CONTAINER_TAGS | _XML_PROVISION_TAGS
_XML_TEXT_TAGS = {
    "after-quoted-block",
    "continuation-text",
    "quoted-block-continuation-text",
    "text",
}
_QUOTED_BLOCK_START = "[[QUOTED_BLOCK_START]]"
_QUOTED_BLOCK_END = "[[QUOTED_BLOCK_END]]"


class RetryableDocumentStorageError(Exception):
    """A transient object-storage failure that should use the Celery retry policy."""


class DocumentValidationError(ValueError):
    """Terminal validation failure retained by durable ingestion for replay."""


class DocumentByteLimitExceeded(DocumentValidationError):
    """The decoded response exceeded the configured document byte limit."""


class DocumentPageLimitExceeded(DocumentValidationError):
    """A PDF exceeded the configured page limit."""


class DocumentTextLimitExceeded(DocumentValidationError):
    """Extracted text exceeded the configured character limit."""


class MalformedDocumentError(DocumentValidationError):
    """A recognized document type could not be parsed safely."""


@dataclass
class DownloadedDocument:
    file: BinaryIO
    content_type: str | None
    size: int
    checksum: str

    def __enter__(self):
        self.file.seek(0)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.file.close()


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
    if (
        status_code == 429
        or status_code >= 500
        or error_code in _RETRYABLE_STORAGE_ERROR_CODES
    ):
        return RetryableDocumentStorageError(str(exc))
    return None


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def guess_extension(url: str, content_type: str | None) -> str:
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


def download_url(
    url: str,
    timeout: int | float | None = None,
    *,
    max_bytes: int | None = None,
    spool_max_bytes: int | None = None,
) -> DownloadedDocument:
    """Stream a remote document into a bounded, checksum-tracked spool file."""
    headers = {
        "User-Agent": "LegislationTracker/1.0 (document ingestion; +https://github.com/)",
    }
    timeout = (
        timeout
        if timeout is not None
        else getattr(settings, "DOCUMENT_DOWNLOAD_TIMEOUT_SECONDS", 120)
    )
    max_bytes = (
        max_bytes
        if max_bytes is not None
        else getattr(settings, "DOCUMENT_DOWNLOAD_MAX_BYTES", 50 * 1024 * 1024)
    )
    spool_max_bytes = (
        spool_max_bytes
        if spool_max_bytes is not None
        else getattr(settings, "DOCUMENT_DOWNLOAD_SPOOL_MAX_BYTES", 5 * 1024 * 1024)
    )
    response = requests.get(
        url,
        timeout=timeout,
        headers=headers,
        allow_redirects=True,
        stream=True,
    )
    try:
        response.raise_for_status()
        declared_length = response.headers.get("Content-Length")
        if declared_length not in (None, ""):
            try:
                declared_bytes = int(declared_length)
            except (TypeError, ValueError) as exc:
                raise MalformedDocumentError(
                    f"Invalid Content-Length header: {declared_length!r}"
                ) from exc
            if declared_bytes < 0:
                raise MalformedDocumentError(
                    f"Invalid Content-Length header: {declared_length!r}"
                )
            if declared_bytes > max_bytes:
                raise DocumentByteLimitExceeded(
                    f"Document declares {declared_bytes} bytes; limit is {max_bytes}"
                )

        spool = SpooledTemporaryFile(max_size=spool_max_bytes, mode="w+b")
        checksum = hashlib.sha256()
        size = 0
        try:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > max_bytes:
                    raise DocumentByteLimitExceeded(
                        f"Document contains more than {max_bytes} decoded bytes"
                    )
                checksum.update(chunk)
                spool.write(chunk)
            spool.seek(0)
            content_type = response.headers.get("Content-Type")
            if content_type and ";" in content_type:
                content_type = content_type.split(";", 1)[0].strip()
            return DownloadedDocument(
                file=spool,
                content_type=content_type,
                size=size,
                checksum=checksum.hexdigest(),
            )
        except Exception:
            spool.close()
            raise
    finally:
        response.close()


def _configured_positive_limit(name: str, fallback: int, override: int | None) -> int:
    value = override if override is not None else getattr(settings, name, fallback)
    return max(int(value), 1)


def extract_text_from_pdf(
    data: bytes | BinaryIO,
    *,
    max_pages: int | None = None,
    max_text_chars: int | None = None,
) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is required for PDF document extraction") from exc
    max_pages = _configured_positive_limit(
        "DOCUMENT_PDF_MAX_PAGES",
        1000,
        max_pages,
    )
    max_text_chars = _configured_positive_limit(
        "DOCUMENT_EXTRACTED_TEXT_MAX_CHARS",
        5_000_000,
        max_text_chars,
    )
    if hasattr(data, "seek"):
        data.seek(0)
        stream = data
    else:
        stream = BytesIO(data)
    try:
        reader = PdfReader(stream)
        page_count = len(reader.pages)
        if page_count > max_pages:
            raise DocumentPageLimitExceeded(
                f"PDF contains {page_count} pages; limit is {max_pages}"
            )
        parts = _BoundedTextLines(max_text_chars)
        for page in reader.pages:
            text = page.extract_text()
            if text:
                parts.append(text)
        return parts.render().strip()
    except DocumentValidationError:
        raise
    except Exception as exc:
        raise MalformedDocumentError(f"Malformed PDF: {exc}") from exc


class _BoundedTextLines:
    def __init__(self, max_chars: int):
        self.max_chars = max_chars
        self.parts: list[str] = []
        self.length = 0

    def append(self, value: str) -> None:
        separator_length = 1 if self.parts else 0
        next_length = self.length + separator_length + len(value)
        if next_length > self.max_chars:
            raise DocumentTextLimitExceeded(
                f"Extracted document text exceeds {self.max_chars} characters"
            )
        self.parts.append(value)
        self.length = next_length

    def render(self) -> str:
        return "\n".join(self.parts)


def _xml_tag(element: ElementTree.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].casefold()


def _normalized_inline_text(element: ElementTree.Element) -> str:
    return re.sub(r"\s+", " ", "".join(element.itertext())).strip()


def _direct_xml_child_text(element: ElementTree.Element, tag: str) -> str:
    child = next((item for item in element if _xml_tag(item) == tag), None)
    return _normalized_inline_text(child) if child is not None else ""


def _render_congress_xml_element(
    element: ElementTree.Element, lines: _BoundedTextLines
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
        if child_tag in _XML_STRUCTURAL_TAGS:
            _render_congress_xml_element(child, lines)
        elif child_tag == "quoted-block":
            lines.append(_QUOTED_BLOCK_START)
            for quoted_child in child:
                if _xml_tag(quoted_child) in _XML_STRUCTURAL_TAGS:
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


def _extract_congress_xml(text: str, max_text_chars: int) -> str | None:
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise MalformedDocumentError(f"Malformed XML: {exc}") from exc
    legislative_body = next(
        (element for element in root.iter() if _xml_tag(element) == "legis-body"),
        None,
    )
    if legislative_body is None:
        return None
    lines = _BoundedTextLines(max_text_chars)
    for child in legislative_body:
        if _xml_tag(child) in _XML_STRUCTURAL_TAGS:
            _render_congress_xml_element(child, lines)
    return lines.render().strip()


def extract_text_from_xml_or_html(
    data: bytes,
    content_type: str | None,
    *,
    max_text_chars: int | None = None,
) -> str:
    max_text_chars = _configured_positive_limit(
        "DOCUMENT_EXTRACTED_TEXT_MAX_CHARS",
        5_000_000,
        max_text_chars,
    )
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        return ""
    content_type = (content_type or "").casefold()
    if not text.strip():
        if "xml" in content_type:
            raise MalformedDocumentError("Malformed XML: document is empty")
        return ""
    if "xml" in content_type:
        structured_text = _extract_congress_xml(text, max_text_chars)
        if structured_text:
            return structured_text
    if "xml" in content_type or "html" in content_type:
        text = _STRUCTURAL_MARKUP_TAG_RE.sub("\n", text)
        text = _MARKUP_TAG_RE.sub("", text)
        text = unescape(text)

    lines = _BoundedTextLines(max_text_chars)
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(r"[\t\f\v ]+", " ", raw_line).strip()
        if line:
            lines.append(line)
    return lines.render()


def _read_document_bytes(data: bytes | BinaryIO) -> bytes:
    if isinstance(data, bytes):
        return data
    data.seek(0)
    payload = data.read()
    data.seek(0)
    return payload


def extract_document_text(
    data: bytes | BinaryIO,
    content_type: str | None,
    source_url: str | None,
    *,
    max_pdf_pages: int | None = None,
    max_text_chars: int | None = None,
) -> str:
    """Extract text using the document type, with extension fallback for bad MIME."""
    ext = guess_extension(source_url or "", content_type)
    normalized_content_type = (content_type or "").casefold()
    if "pdf" in normalized_content_type or ext == ".pdf":
        return extract_text_from_pdf(
            data,
            max_pages=max_pdf_pages,
            max_text_chars=max_text_chars,
        )
    if not (
        any(kind in normalized_content_type for kind in ("xml", "html", "text/plain"))
        or ext in {".xml", ".html", ".htm", ".txt"}
    ):
        return ""

    extraction_content_type = content_type
    if "xml" not in normalized_content_type and ext == ".xml":
        extraction_content_type = "application/xml"
    elif "html" not in normalized_content_type and ext in {".html", ".htm"}:
        extraction_content_type = "text/html"
    elif "text/plain" not in normalized_content_type and ext == ".txt":
        extraction_content_type = "text/plain"
    return extract_text_from_xml_or_html(
        _read_document_bytes(data),
        extraction_content_type,
        max_text_chars=max_text_chars,
    )


def reextract_stored_document_text(document) -> str:
    """Rebuild text from a stored source, falling back to legacy raw XML text."""
    if document.object_storage_key:
        with default_storage.open(document.object_storage_key, "rb") as stored_file:
            data = stored_file.read()
    else:
        raw_source = document.raw_text or document.extracted_text or ""
        data = raw_source.encode("utf-8")

    extracted = extract_document_text(
        data,
        document.content_type,
        document.source_url,
    )
    return extracted or (document.extracted_text or "")


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


def build_object_key(
    bill_session: int, bill_number: str, version_label: str, ext: str
) -> str:
    """bills/{session}/{bill_number}/{version_label}.{ext}"""
    safe_bn = re.sub(r"[^\w\-]+", "_", bill_number.strip())[:80]
    safe_v = re.sub(r"[^\w\-]+", "_", version_label.strip())[:50]
    if not ext.startswith("."):
        ext = "." + ext
    return f"bills/{bill_session}/{safe_bn}/{safe_v}{ext}"


def upload_and_metadata(
    object_key: str,
    data: bytes | BinaryIO,
    content_type: str | None,
    *,
    size: int | None = None,
) -> tuple[str, int]:
    """
    Save to default_storage; return (stored name/key, size in bytes).
    """
    ensure_s3_bucket_exists()
    ct = (
        content_type
        or mimetypes.guess_type(object_key)[0]
        or "application/octet-stream"
    )
    if isinstance(data, bytes):
        content = ContentFile(data)
        content_size = len(data)
    else:
        data.seek(0)
        content = File(data, name=object_key)
        content_size = size if size is not None else getattr(content, "size", None)
        if content_size is None:
            data.seek(0, 2)
            content_size = data.tell()
            data.seek(0)
    content.content_type = ct
    saved_name = default_storage.save(object_key, content)
    return saved_name, int(content_size)
