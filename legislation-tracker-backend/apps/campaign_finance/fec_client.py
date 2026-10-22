"""Fixed-host, bounded OpenFEC requests. Exceptions never contain credential URLs."""
import json
import re
import time
import math
from email.utils import parsedate_to_datetime
import requests
from django.conf import settings
from django.utils import timezone


def retry_after(value, now=None):
    if not value:
        return None
    if str(value).isdigit():
        return int(value)
    try:
        instant = parsedate_to_datetime(value)
        if timezone.is_naive(instant):
            return None
        return max(0, math.ceil((instant - (now or timezone.now())).total_seconds()))
    except (ValueError, TypeError, OverflowError):
        return None


class FECError(Exception):
    def __init__(self, reason, status_code=None, retry_after_seconds=None):
        super().__init__(reason)
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


def receipt_parameters(committee_id, period, cursor, schedule="a"):
    if not re.fullmatch(r"C\d{8}", committee_id):
        raise ValueError("invalid_committee")
    if schedule not in {"a", "b", "a_11ai", "a_11b", "a_11c", "b_20a", "b_20b", "b_20c"}:
        raise ValueError("invalid_schedule")
    field = "contribution_receipt_date" if schedule.startswith("a") else "disbursement_date"
    allowed = {"last_index", "last_" + field, "sort_null_only"}
    if not isinstance(cursor, dict) or set(cursor) - allowed:
        raise ValueError("invalid_cursor")
    filters = {"line_number": "F3-" + schedule.split("_")[1].upper()} if "_" in schedule else {}
    return {"committee_id": committee_id, "two_year_transaction_period": period, "per_page": 100, "sort": "-" + field, **filters, **cursor}


def get_page(path, params):
    if not re.fullmatch(r"(?:candidates/search/|candidate/[HSP]\d[A-Z]{2}\d{5}/committees/|schedules/schedule_[ab]/|committee/C\d{8}/totals/)", path):
        raise ValueError("invalid_endpoint")
    key = getattr(settings, "FEC_API_KEY", "")
    if not key:
        raise FECError("missing_fec_key")
    deadline = time.monotonic() + 30
    with requests.Session() as session:
        session.trust_env = False
        try:
            with session.get("https://api.open.fec.gov/v1/" + path, params={**params, "api_key": key}, headers={"Accept": "application/json", "Accept-Encoding": "identity", "User-Agent": "LegislationTrackerResearch/1.0"}, timeout=(5, 10), stream=True, allow_redirects=False) as response:
                if response.status_code != 200:
                    retry = response.headers.get("Retry-After", "")
                    raise FECError("fec_rate_limited" if response.status_code == 429 else "fec_source_unavailable", response.status_code, retry_after(retry))
                if "json" not in response.headers.get("Content-Type", "") or response.headers.get("Content-Encoding", "identity") not in ("", "identity"):
                    raise FECError("invalid_fec_response")
                body = bytearray()
                for chunk in response.iter_content(1):
                    body.extend(chunk)
                    if len(body) > 4_000_000 or time.monotonic() > deadline:
                        raise FECError("fec_response_limit")
                data = json.loads(body)
        except (requests.RequestException, ValueError) as exc:
            raise FECError("fec_request_failed") from None
    if not isinstance(data, dict) or not isinstance(data.get("results"), list) or not isinstance(data.get("pagination"), dict):
        raise FECError("invalid_fec_response")
    return data
