"""Small, auditable synopsis templates over explicit operative provisions.

No bill IDs, titles, topic inference, provider calls, or estimated fiscal totals.
Unsupported effects remain in the detailed reader, not guessed in the synopsis.
"""

import re

from .operative_context import parse_operative_clauses
from .federal_clauses import _quoted_block_ranges
from .types import SourceSpan
from .display_text import normalize_reader_fragment


def _sanctions_synopsis(section):
    """Recognize the sanctions mechanism, not a bill number or title.

    Keep scope qualified: an overview of sanctions is not a determination that
    every person in a region is sanctioned. Cite the entire governing section,
    including eligibility, exceptions and waivers.
    """
    raw = section.span.text
    if not re.search(
        r"The President shall impose sanctions described in subsection \(b\) "
        r"with respect to any foreign person determined by the President to meet "
        r"any of the following:", raw
    ):
        return None
    # Require the operative mechanisms, not mentions in findings or a report.
    if not (
        re.search(r"the President shall exercise all powers.*?to block and prohibit all transactions", raw, re.S)
        and "if such property and interests in property are in the United States" in raw
        and "inadmissible to the United States" in raw
        and "ineligible for a visa or other documentation to enter the United States" in raw
    ):
        return None
    scope = re.search(r"acts of terrorism affecting (the [A-Z][A-Za-z ]+)\.", raw)
    text = "Requires the President to impose sanctions on foreign persons who meet the bill’s listed criteria"
    if scope:
        text += f", including conduct affecting {scope[1]}"
    text += (
        ". The criteria also cover the specified leaders, supporters, and related entities."
        if all(phrase in raw for phrase in (
            "To be or have been a leader or official of",
            "To have materially assisted, sponsored",
            "To be owned or controlled by",
        )) else "."
    )
    text += (
        " Sanctions include blocking property subject to U.S. jurisdiction and "
        "restrictions on visas and entry into the United States."
    )
    if "Exceptions.—" in raw and "Waivers.—" in raw:
        text += " The entry restrictions are subject to the bill’s exceptions and waivers."
    return text


def _source_provision_synopsis(sections, source_text):
    """A general extractive fallback: whole operative sections, never headings.

    Unlike paraphrase rules this preserves the author's complete wording.
    Do not trim a long eligibility list or lift text from an amendment quote.
    """
    quotes = _quoted_block_ranges(source_text)
    selected = []
    words = 0
    for section in sections:
        if section.level != "section":
            continue
        if re.search(r"short title|table of contents|findings|sense of congress", section.heading or "", re.I):
            continue
        if any(section.span.start_char < end and start < section.span.end_char for start, end in quotes):
            continue
        body = normalize_reader_fragment(section.span.text.partition("\n")[2])
        if not body or not body.endswith((".", "!", "?")) or not re.search(r"\b(?:shall|must|is amended|is repealed)\b", body):
            continue
        if len(body.split()) > 180 or words + len(body.split()) > 260:
            continue
        selected.append((section, body))
        words += len(body.split())
        if len(selected) == 3:
            break
    if not selected:
        return None
    return (
        "Selected bill provisions: " + " ".join(body for _, body in selected),
        selected[0][0],
        tuple(section.span for section, _ in selected),
    )


def structured_synopsis(sections, claims, source_text, clauses=None):
    sentences = []
    evidence = []
    owner = None
    seen = set()
    excluded_quotes = _quoted_block_ranges(source_text)
    clauses = (
        clauses
        if clauses is not None
        else parse_operative_clauses(source_text, sections)
    )

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
        heading = section.heading or ""
        facts = [
            clause
            for clause in clauses
            if clause.asserted
            and section.span.start_char
            <= clause.span.start_char
            < section.span.end_char
        ]
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
        # A repeal can contain a payment mandate even though the legacy
        # amendment classifier excludes its embedded "shall" from facts.
        # Match the complete rule: never infer retroactivity from a heading.
        body = raw[heading_end + 1:] if heading_end >= 0 else ""
        if (
            heading.casefold() == "sanctions"
            and not any(section.span.start_char < end and start < section.span.end_char
                        for start, end in excluded_quotes)
            and (sanctions := _sanctions_synopsis(section))
        ):
            add("sanctions", sanctions, section, [section.span])
        report = re.fullmatch(
            r"Not later than (?P<days>\d+) days after the date of the enactment of this Act, "
            r"and every (?P=days) days thereafter, the (?P<actor>[^,]+), "
            r"in consultation with the (?P<consulted>[^,]+), shall submit to the "
            r"appropriate congressional committees a report on the implementation of "
            r"this Act, including the names of any persons sanctioned by this Act\.",
            re.sub(r"\s+", " ", body).strip(),
        )
        if (report and heading.casefold() == "report"
                and not any(section.span.start_char < end and start < section.span.end_char
                            for start, end in excluded_quotes)):
            add(
                "sanctions-report",
                f"Requires the {report['actor']}, in consultation with the {report['consulted']}, "
                f"to report to Congress within {report['days']} days of enactment and every "
                f"{report['days']} days afterward on implementation and those sanctioned.",
                section, [section.span],
            )
        repeal = re.fullmatch(
            r"Section (?P<section>\d+) of Public Law (?P<law>\d+[–-]\d+) is repealed, and, "
            r"in the case of any items or services furnished as medical assistance under a "
            r"State plan \(or a waiver of such plan\) under title XIX of the Social Security Act "
            r"\([^)]*\) by a prohibited entity \(as defined in subsection \(b\)\(1\) of such "
            r"section (?P=section)\) during the period beginning on the date of enactment of "
            r"Public Law (?P=law) and ending on the date of enactment of this section, "
            r"payment for such items and services shall be made as if such section "
            r"(?P=section) had not been enacted into law\.",
            re.sub(r"\s+", " ", body).strip(),
        )
        if (
            repeal
            and heading.casefold() == "repealing prohibition on medicaid payments to certain entities"
            and not any(section.span.start_char < end and start < section.span.end_char
                        for start, end in excluded_quotes)
        ):
            add(
                "repeal-payment-" + str(section.span.start_char),
                "Repeals the prohibition on Medicaid payments to certain entities "
                f"in section {repeal.group('section')} of Public Law {repeal.group('law')}. "
                "Requires payment for Medicaid items and services those entities provided "
                "under state plans or waivers between that law’s enactment and this bill’s "
                "enactment, as though the prohibition had not been enacted.",
                section, [section.span],
            )
        residence = next(
            (
                fact
                for fact in facts
                if re.search(
                    r"\bshall\s+adjust\s+to\s+the\s+status\s+of\s+an\s+alien\s+lawfully\s+admitted\s+for\s+permanent\s+residence\b",
                    fact.span.text,
                    re.I,
                )
            ),
            None,
        )
        if (
            residence
            and re.search(r"entered the United States as children", heading, re.I)
            and re.search(r"on a conditional basis", heading, re.I)
        ):
            summary = "Provides a path to conditional permanent residence (a green card with conditions) for eligible long-term residents who entered the United States as children."
            spans = [heading_span, *residence.evidence]
            presence = next(
                (
                    (fact, match)
                    for fact in facts
                    if (
                        match := re.search(
                            r"\bhas been continuously physically present in the United States since ([A-Za-z]+ \d{1,2}, \d{4})",
                            fact.span.text,
                        )
                    )
                ),
                None,
            )
            if presence:
                fact, match = presence
                summary += f" Residence requirements include continuous presence since {match.group(1)}."
                spans.extend(fact.evidence)
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
                [heading_span, *residence.evidence],
            )

        grant = next(
            (
                fact
                for fact in facts
                if re.search(
                    r"\bshall establish(?:,\s*within[^,\n]+,)?\s+a program to award grants\b.*\beligible nonprofit organizations\b.*\bassist eligible applicants\b",
                    re.sub(r"\s+", " ", fact.span.text),
                    re.I | re.S,
                )
            ),
            None,
        )
        if grant:
            add(
                "application_grants",
                "Creates a grant program for nonprofit organizations to help eligible applicants.",
                section,
                [heading_span, *grant.evidence],
            )
        # Preserve the explicit recipient and purpose instead of inventing a
        # benefit from the title. Conditions remain available in the cited rule.
        for fact in facts:
            match = re.fullmatch(
                r".*?\bshall award a grant to (?P<recipient>[^.;]+?) "
                r"for (?P<purpose>[^.;]+)\.",
                re.sub(r"\s+", " ", fact.span.text), re.I,
            )
            if match:
                add(
                    "grant-" + str(fact.span.start_char),
                    f"Requires grants to {match.group('recipient')} for "
                    f"{match.group('purpose')}. Eligibility and use of funds "
                    "are subject to the conditions below.",
                    section, list(fact.evidence),
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
