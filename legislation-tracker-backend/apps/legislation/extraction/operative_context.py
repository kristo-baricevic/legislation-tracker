"""Conservative context checks shared by payment and synopsis templates."""

import re


def has_nonoperative_prefix(text: str, position: int) -> bool:
    # A wrapped line is not a new sentence: reporting/negative subjects can
    # govern an action on the following line. Do not inspect amount qualifiers
    # after the action (for example, "not more than $100").
    prefix = re.split(r"[.!?](?:\s|$)", text[:position])[-1]
    # An explicit exception starts a new operative scope, while its conditions
    # remain attached in the original evidence.
    prefix = re.split(r"\bexcept that\b", prefix, flags=re.I)[-1]
    return bool(
        re.search(
            r"\b(?:no|not|neither|whether|report|study|recommend|recommendation)\b",
            prefix,
            re.I,
        )
    )
