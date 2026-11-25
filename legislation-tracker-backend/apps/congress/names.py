"""Normalize person labels, not donor/committee names or identity keys."""

import re
import unicodedata

_TITLE = (
    r"(?:Rep\.|Sen\.|Del\.|Hon\.|Representative|Senator|Delegate|Resident Commissioner)"
)
_PREFIX = r"(?:Rep\.?|Sen\.?|Del\.?|Hon\.?|Representative|Senator|Delegate|Resident Commissioner)"


def normalize_person_name(value):
    name = unicodedata.normalize("NFC", str(value or ""))
    # Only remove recognizable affiliation metadata, never arbitrary brackets.
    name = re.sub(r"\s*\[[A-Z]+-[A-Z]{2}(?:-\d+)?\]\s*$", "", name, flags=re.I)
    name = re.sub(r"\s*\([A-Z]{2}-(?:house|senate)\)\s*$", "", name, flags=re.I)
    name = re.sub(r"\s*\[[A-Z]+-[A-Z]{2}(?:-\d+)?\]\s*$", "", name, flags=re.I)
    name = re.sub(r"\s+", " ", name).strip()
    previous = None
    while name != previous:
        previous = name
        name = re.sub(rf"^{_PREFIX}\s+", "", name, flags=re.I)
        name = re.sub(rf"(?:\s+|,\s*){_TITLE}$", "", name, flags=re.I).strip()
    return name
