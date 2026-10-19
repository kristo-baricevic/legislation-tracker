"""Source-only candidate inventory; mechanical coverage is not semantic approval.

This deliberately reports candidates, not a legally complete inventory. Detection
does not interpret amendments, resolve outside law, or establish entailment.
"""

import hashlib
import re
from decimal import Decimal, InvalidOperation

from apps.legislation.enhancements.citations import citation_spans
from apps.legislation.extraction.federal_structure import (
    SECTION_RE,
    parse_federal_structure,
)
from apps.legislation.extraction.types import ExpectedExtractionRejection

PATTERNS = {
    "fee": r"\b(?:fees?|surcharges?)\b",
    "penalty": r"\b(?:fine[ds]?|penalt(?:y|ies))\b",
    "funding": r"\b(?:appropriat(?:ed|ing|ions?)|allocat(?:ed|ing|ions?)|rescission|set.aside|grant funds|funds available)\b",
    "conditions": r"\b(?:if|unless|provided that)\b[^.;]*?(?:--|[—–:]|$)",
}
AMOUNTS = re.compile(
    r"\$\s*\d[\d,]*(?:\.\d+)?(?:\s+(?:million|billion|trillion))?", re.I
)
CATEGORIES = (
    "overview",
    "key_impacts",
    "obligations",
    "funding_and_timing",
    "uncertain_language",
)


def _runs(sources):
    """Keep gaps as separate runs, never fabricate the contents of omitted text."""
    runs = []
    seen = set()
    for source in sorted(sources, key=lambda s: s["start_char"]):
        text, start, end = (
            source["quoted_text"],
            source["start_char"],
            source["end_char"],
        )
        if hashlib.sha256(text.encode()).hexdigest() != source["text_sha256"]:
            raise ValueError("Source hash mismatch")
        if source["source_ref"] in seen or start < 0 or end - start != len(text):
            raise ValueError("Invalid source identity or offsets")
        seen.add(source["source_ref"])
        if runs and start < runs[-1][0] + len(runs[-1][1]):
            raise ValueError("Overlapping source spans")
        # Whitespace trimmed by source selection is not reconstructible here.
        # Join only exactly adjacent spans; no assumption about missing bytes.
        if runs and start == runs[-1][0] + len(runs[-1][1]):
            runs[-1] = (runs[-1][0], runs[-1][1] + text)
        else:
            runs.append((start, text))
    return runs


def build_inventory(sources, *, document_text=None):
    rows = []
    runs = _runs(sources)
    if document_text is not None:
        for source in sources:
            if (
                document_text[source["start_char"] : source["end_char"]]
                != source["quoted_text"]
            ):
                raise ValueError("Snapshot does not match pinned document")
        runs = [(0, document_text)]
    for offset, text in runs:
        markers = list(SECTION_RE.finditer(text))
        operative = {
            m.group("label"): m.start() for m in markers if m.group("kind").isupper()
        }
        contents = [
            (m.start(), m.end())
            for m in markers
            if not m.group("kind").isupper()
            and m.start() < operative.get(m.group("label"), -1)
        ]
        try:
            sections = parse_federal_structure(text)
        except ExpectedExtractionRejection:
            sections = ()
        spans = {}
        for kind, pattern in PATTERNS.items():
            for match in re.finditer(pattern, text, re.I):
                if any(start <= match.start() < end for start, end in contents):
                    continue
                owners = [
                    s
                    for s in sections
                    if s.span.start_char <= match.start() < s.span.end_char
                ]
                if owners:
                    owner = min(
                        owners, key=lambda s: s.span.end_char - s.span.start_char
                    )
                    start, end = owner.span.start_char, owner.span.end_char
                else:
                    start, end = 0, len(text)
                spans.setdefault((start, end), set()).add(kind)
        for (start, end), kinds in sorted(spans.items()):
            raw = text[start:end]
            absolute_start, absolute_end = offset + start, offset + end
            rows.append(
                {
                    "id": "cov_"
                    + hashlib.sha256(
                        f"{absolute_start}:{absolute_end}:{raw}".encode()
                    ).hexdigest()[:16],
                    "kinds": sorted(kinds),
                    "start_char": absolute_start,
                    "end_char": absolute_end,
                    "source_text": raw,
                    "source_refs": [
                        s["source_ref"]
                        for s in sources
                        if s["start_char"] < absolute_end
                        and absolute_start < s["end_char"]
                    ],
                    "amounts": list(
                        dict.fromkeys(m.group() for m in AMOUNTS.finditer(raw))
                    ),
                    "inventory_status": "candidate_requires_review",
                }
            )
    return rows


def assess_inventory(inventory, output, sources, *, mapping=None):
    by_ref = {s["source_ref"]: s for s in sources}
    claims = []
    for category in CATEGORIES:
        for index, item in enumerate(output.get(category, [])):
            ranges = []
            for quote in item.get("source_quotes", []):
                source = by_ref.get(quote.get("source_ref"))
                if not source or quote["source_ref"] not in item.get("source_refs", []):
                    continue
                matches = citation_spans(source["quoted_text"], quote.get("quote", ""))
                if len(matches) == 1:
                    start, end = matches[0]
                    ranges.append(
                        (source["start_char"] + start, source["start_char"] + end)
                    )
            prose = " ".join(
                str(item.get(k) or "")
                for k in ("text", "actor", "action", "conditions", "why_it_matters")
            )
            claims.append((f"{category}/{index}", prose, ranges))
    reports = []
    for row in inventory:
        linked = [
            (path, prose)
            for path, prose, ranges in claims
            if (mapping is None or path in mapping.get(row["id"], []))
            and any(
                start < row["end_char"] and row["start_char"] < end
                for start, end in ranges
            )
        ]
        prose = " ".join(p for _, p in linked)

        def normalize(value):
            value = value.lower().replace(",", "").replace("$", "").strip()
            parts = value.split()
            try:
                return (Decimal(parts[0]), tuple(parts[1:]))
            except InvalidOperation:
                return value

        mentioned = {normalize(m.group()) for m in AMOUNTS.finditer(prose)}
        missing = [
            amount for amount in row["amounts"] if normalize(amount) not in mentioned
        ]
        meaning_errors = []
        if (
            "penalty" in row["kinds"]
            and re.search(r"\bshall\s+be\s+fined\b", row["source_text"], re.I)
            and re.search(r"\b(?:may|might|could)\s+be\s+fined\b", prose, re.I)
        ):
            meaning_errors.append("mandatory_fine_described_as_optional")
        reports.append(
            {
                "id": row["id"],
                "status": "meaning_conflict"
                if meaning_errors
                else "missing_explanation"
                if not linked
                else "missing_amount"
                if missing
                else "needs_semantic_review",
                "output_paths": [path for path, _ in linked],
                "missing_amounts": missing,
                "semantic_verified": False,
                "meaning_errors": meaning_errors,
            }
        )
    return reports
