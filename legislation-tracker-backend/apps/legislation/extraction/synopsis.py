"""Small, auditable synopsis templates over explicit operative provisions.

No bill IDs, titles, topic inference, provider calls, or estimated fiscal totals.
Unsupported effects remain in the detailed reader, not guessed in the synopsis.
"""

import re

from .federal_clauses import _quoted_block_ranges
from .operative_context import has_nonoperative_prefix
from .types import SourceSpan


def structured_synopsis(sections, claims, source_text):
    sentences = []
    evidence = []
    owner = None
    seen = set()
    quoted = _quoted_block_ranges(source_text)

    def add(key, text, section, spans):
        nonlocal owner
        if key in seen:
            return
        seen.add(key)
        owner = owner or section
        sentences.append(text)
        evidence.extend(spans)

    for section in sections:
        if section.level != "section":
            continue
        raw = section.span.text
        if any(start <= section.span.start_char < end for start, end in quoted):
            continue
        # Mask quoted amendment bodies without changing character offsets.
        masked = list(raw)
        for start, end in _quoted_block_ranges(raw):
            masked[start:end] = " " * (end - start)
        text = "".join(masked)
        heading = section.heading or ""

        def span_for(match, text=text, raw=raw, section=section):
            start = text.rfind("\n", 0, match.start()) + 1
            end = text.find("\n", match.end())
            if end < 0:
                end = len(text)
            return SourceSpan(
                raw[start:end],
                section.span.start_char + start,
                section.span.start_char + end,
            )

        heading_end = raw.find("\n")
        heading_span = (
            SourceSpan(
                raw[:heading_end],
                section.span.start_char,
                section.span.start_char + heading_end,
            )
            if heading_end > 0
            else section.span
        )
        residence = re.search(
            r"\bshall adjust to the status of an alien lawfully admitted for permanent residence\b",
            text,
            re.I,
        )
        if residence:
            if has_nonoperative_prefix(text, residence.start()):
                residence = None
        if (
            residence
            and re.search(r"entered the United States as children", heading, re.I)
            and re.search(r"on a conditional basis", heading, re.I)
        ):
            summary = "Provides a path to conditional permanent residence (a green card with conditions) for eligible long-term residents who entered the United States as children."
            spans = [heading_span, span_for(residence)]
            presence = re.search(
                r"\bhas been continuously physically present in the United States since ([A-Za-z]+ \d{1,2}, \d{4})",
                text,
            )
            if presence:
                summary += f" Residence requirements include continuous presence since {presence.group(1)}."
                spans.append(span_for(presence))
            summary += " Eligibility is subject to the conditions in the bill."
            add("conditional_residence", summary, section, spans)
        elif (
            residence
            and re.search(r"temporary protected status", heading, re.I)
            and re.search(r"deferred enforced departure", heading, re.I)
        ):
            add(
                "protected_residence",
                "Provides a path to permanent residence for eligible people covered by temporary protected status or deferred enforced departure, subject to the bill’s eligibility requirements.",
                section,
                [heading_span, span_for(residence)],
            )

        grant = re.search(
            r"\bshall establish(?:,\s*within[^,\n]+,)?\s+a program to award grants\b[^\n]*\beligible nonprofit organizations\b[^\n]*\bassist eligible applicants\b",
            text,
            re.I,
        )
        if grant:
            if has_nonoperative_prefix(text, grant.start()):
                continue
            add(
                "application_grants",
                "Creates a grant program for nonprofit organizations to help eligible applicants.",
                section,
                [heading_span, span_for(grant)],
            )

    # Financial categories are already classified, with their original evidence.
    # Summarize their presence, never add unlike amounts or imply appropriation.
    labels = {
        "appropriation": "appropriations",
        "authorization": "funding authorizations",
        "allocation": "funding allocations",
        "transfer": "transfers between accounts",
        "rescission": "cancellation of previously approved funding",
        "reduction": "funding reductions",
        "cancellation": "funding cancellations",
        "set_aside": "funding set-asides",
        "limitation": "funding limits",
        "fee": "application or processing fees",
        "fee_exemption": "fee exemptions",
        "surcharge": "surcharges",
        "penalty": "fines or penalties",
        "account_rule": "rules for holding or using funds",
    }
    financial = {}
    for claim in claims:
        action = claim.fields.get("financial_action")
        if claim.category == "financial_items" and action in labels:
            financial.setdefault(action, claim)
    if financial:
        names = [labels[action] for action in financial]
        listed = (
            names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        )
        first = next(iter(financial.values()))
        section = next((s for s in sections if s.source_id == first.section_id), None)
        if section:
            add(
                "money",
                "The bill includes "
                + listed
                + ". The money section below gives the amounts, purposes, and conditions separately.",
                section,
                [span for claim in financial.values() for span in claim.evidence],
            )
    if not sentences:
        return None
    unique = {(span.start_char, span.end_char): span for span in evidence}
    return (
        " ".join(sentences),
        owner,
        tuple(sorted(unique.values(), key=lambda span: span.start_char)),
    )
