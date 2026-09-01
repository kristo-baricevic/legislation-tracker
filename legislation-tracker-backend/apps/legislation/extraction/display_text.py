"""Controlled, reader-only cleanup for congressional source fragments."""

from __future__ import annotations

import re

_NOTE_RE = re.compile(r"<<NOTE:.*?>>", re.IGNORECASE | re.DOTALL)
_PAGE_RE = re.compile(r"\[\[Page\s+\d+\s+STAT\.\s+\d+\]\]", re.IGNORECASE)
_CONGRESSIONAL_TICKS_RE = re.compile(r"`{2,}")
_ORPHAN_LIST_MARKER_RE = re.compile(r"^\s*\([A-Za-z0-9ivxlcdm]+\)\s+", re.IGNORECASE)


def normalize_reader_fragment(value: str) -> str:
    """Remove known extraction artifacts without altering source evidence."""

    cleaned = _NOTE_RE.sub(" ", value)
    cleaned = _PAGE_RE.sub(" ", cleaned)
    cleaned = _CONGRESSIONAL_TICKS_RE.sub("", cleaned)
    cleaned = re.sub(r"-\s*\n\s*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = _ORPHAN_LIST_MARKER_RE.sub("", cleaned)
    return re.sub(r"\s+([.;:])", r"\1", cleaned).strip()
