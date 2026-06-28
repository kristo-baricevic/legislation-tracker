"""
Congress.gov API v3 client for ingestion.
Uses CONGRESS_API_KEY from Django settings. Base URL: https://api.congress.gov/v3.
"""
import logging
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class CongressAPIError(Exception):
    """Raised when Congress API returns non-2xx. Celery can retry on this."""

    def __init__(self, message, status_code=None, response_text=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


def _get_api_key():
    return getattr(settings, "CONGRESS_API_KEY", "") or ""


def _request(method, path, params=None):
    base = "https://api.congress.gov/v3"
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    api_key = _get_api_key()
    if not api_key:
        logger.warning(
            "CONGRESS_API_KEY is not set. Set it in legislation-tracker-backend/.env and restart the Celery worker."
        )
    if api_key:
        params = dict(params or {})
        params.setdefault("api_key", api_key)
    logger.debug("Congress API request: %s %s (params keys: %s)", method, path, list(params.keys()) if params else [])
    resp = requests.request(method, url, params=params, timeout=30)
    if not resp.ok:
        logger.error(
            "Congress API error: %s %s -> %s %s",
            method, path, resp.status_code, (resp.text[:200] if resp.text else ""),
        )
        raise CongressAPIError(
            f"Congress API error: {resp.status_code}",
            status_code=resp.status_code,
            response_text=resp.text[:500] if resp.text else None,
        )
    return resp.json()


def _throttle():
    """Optional: small delay between requests to avoid rate limits."""
    time.sleep(0.3)


def bill_list(congress, bill_type, from_date_time=None, limit=250, offset=0):
    """
    GET /bill/{congress}/{billType}?sort=updateDate+desc&limit=...&offset=...&fromDateTime=...
    Returns list of items with congress, type, number, updateDate (for cursor).
    """
    bill_type = (bill_type or "hr").lower()
    params = {"sort": "updateDate desc", "limit": limit, "offset": offset}
    if from_date_time:
        params["fromDateTime"] = from_date_time
    data = _request("GET", f"bill/{congress}/{bill_type}", params=params)
    _throttle()
    bills = data.get("bills") or []
    out = []
    for b in bills:
        # API can return flat or nested (bill.number, bill.updateDate)
        inner = b.get("bill", b)
        num = inner.get("number")
        if num is None:
            num = b.get("number")
        update_date = inner.get("updateDateIncludingText") or inner.get("updateDate") or b.get("updateDateIncludingText") or b.get("updateDate")
        out.append({
            "congress": congress,
            "type": bill_type,
            "number": str(num) if num is not None else "",
            "updateDate": update_date,
        })
    logger.info(
        "bill_list: congress=%s bill_type=%s offset=%s from_date_time=%s -> %s bills (raw response had %s items)",
        congress, bill_type, offset, from_date_time, len(out), len(bills),
    )
    if bills and not out:
        logger.warning("bill_list: API returned %s raw items but parsed 0; check response shape.", len(bills))
    return out


def bill_detail(congress, bill_type, bill_number):
    """GET /bill/{congress}/{billType}/{billNumber}. Returns full bill object."""
    bill_type = (bill_type or "hr").lower()
    logger.debug("bill_detail: congress=%s bill_type=%s bill_number=%s", congress, bill_type, bill_number)
    data = _request("GET", f"bill/{congress}/{bill_type}/{bill_number}")
    _throttle()
    return data.get("bill") or data


def bill_text_list(congress, bill_type, bill_number):
    """
    GET /bill/{congress}/{billType}/{billNumber}/text.
    Returns list of text versions with labels and URLs for BillDocument.
    """
    bill_type = (bill_type or "hr").lower()
    data = _request("GET", f"bill/{congress}/{bill_type}/{bill_number}/text")
    _throttle()
    # API may return { "textVersions": [ { "type": "...", "url": "..." }, ... ] }
    versions = data.get("textVersions") or data.get("text") or []
    if isinstance(versions, dict):
        versions = versions.get("count", []) or []
    result = []
    for v in versions if isinstance(versions, list) else []:
        label = v.get("type") or v.get("version") or v.get("label") or "unknown"
        url = v.get("url")
        if not url and isinstance(v.get("format"), dict):
            url = v.get("format", {}).get("url")
        if not url and isinstance(v.get("formats"), list):
            for f in v.get("formats", []):
                if f.get("url"):
                    url = f["url"]
                    break
        result.append({"version_label": str(label), "url": url or ""})
    logger.info(
        "bill_text_list: congress=%s bill_type=%s bill_number=%s -> %s versions",
        congress, bill_type, bill_number, len(result),
    )
    return result


def vote_detail(congress, chamber, roll_number):
    """GET /vote/{congress}/{chamber}/{rollNumber}. Returns vote and member positions."""
    chamber = (chamber or "house").lower()
    logger.debug("vote_detail: congress=%s chamber=%s roll_number=%s", congress, chamber, roll_number)
    data = _request("GET", f"vote/{congress}/{chamber}/{roll_number}")
    _throttle()
    return data.get("vote") or data
