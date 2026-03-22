"""
Canonical JSON serialization for BillContract.contract_hash stability.
Same logical content → same string → same hash (ignores key order and extra whitespace in strings).
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any


def normalize_value(obj: Any) -> Any:
    """Recursively normalize for stable hashing."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {k: normalize_value(obj[k]) for k in sorted(obj.keys())}
    if isinstance(obj, list):
        return [normalize_value(x) for x in obj]
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return round(obj, 10)
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, str):
        return " ".join(obj.split())
    return str(obj)


def canonical_json_string(data: dict) -> str:
    """
    Return a deterministic string for hashing contract_json.

    Uses sorted keys at every object level, compact separators, UTF-8,
    and normalized whitespace in string values.
    """
    normalized = normalize_value(data)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def contract_hash_from_dict(data: dict) -> str:
    """SHA-256 hex digest of canonical JSON bytes."""
    import hashlib

    s = canonical_json_string(data)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()
