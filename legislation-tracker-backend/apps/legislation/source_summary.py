"""Source-only summaries for documents not covered by paraphrase rules."""

import re

from .extraction.display_text import normalize_reader_fragment
from .extraction.federal_clauses import _quoted_block_ranges
from .extraction.federal_structure import parse_federal_structure
from .extraction.types import ExpectedExtractionRejection

_BOILERPLATE = re.compile(
    r"^(?:short title(?:; table of contents)?|table of contents)$", re.I
)


def purpose_summary(purpose):
    """Describe stated intent, without presenting it as an achieved legal effect."""
    purpose = re.sub(r"\s+", " ", purpose or "").strip()
    if len(purpose.split()) < 3:
        return None
    purpose = re.sub(r",?\s+and for (?:other|related) purposes\.?$", ".", purpose, flags=re.I)
    infinitive = re.match(r"^(?:(?:An Act|A bill)\s+)?To\s+(.+)$", purpose, re.I)
    if infinitive:
        text = infinitive[1]
        return "This bill aims to " + text[0].lower() + text[1:]
    # Do not rewrite unfamiliar grammar or guess an effect from a short title.
    if re.match(r"^(?:Making|Providing|Protecting|For the relief of|An Act to|Joint resolution)\b", purpose, re.I):
        return "Stated purpose: " + purpose
    return None


def source_summary(text):
    """An explicitly extractive overview; never an inferred legal effect.

    Short sections are quoted in full, keeping conditions and exceptions.
    Large bills get a source-ordered heading overview, not a partial sentence
    masquerading as a complete rule. Callers must link to this exact document.
    """
    if not text or not text.strip():
        return None
    # Some appropriations documents have numbered sections without headings.
    # Their opening appropriation statement supplies the scope verbatim.
    preamble = text.strip().partition("\n")[0]
    if (re.fullmatch(
            r"That the following sums are appropriated, out of any money in the Treasury "
            r"not otherwise appropriated, for .+?, namely:", preamble)
            and len(preamble.split()) <= 160):
        return "Bill-text overview: " + preamble + " Read the source for the amounts and restrictions."
    excluded = _quoted_block_ranges(text)
    try:
        sections = parse_federal_structure(text)
    except ExpectedExtractionRejection:
        sections = ()
    candidates = [
        section for section in sections
        if section.level == "section"
        and not _BOILERPLATE.fullmatch((section.heading or "").strip())
        and not any(start <= section.span.start_char < end for start, end in excluded)
    ]
    # Use each source region once when inserted sections overlap an outer
    # amendment section. Headings remain available for the overview below.
    roots = [
        s for s in candidates
        if not any(other.span.start_char < s.span.start_char < other.span.end_char
                   for other in candidates)
    ]
    excerpts = []
    for section in roots:
        if any(section.span.start_char < end and start < section.span.end_char
               for start, end in excluded):
            continue
        body = section.span.text.partition("\n")[2].strip()
        body = normalize_reader_fragment(body)
        if body and len(body.split()) <= 250 and body.endswith((".", "!", "?")):
            excerpts.append(body)
    if excerpts and len(excerpts) == len(roots) and len(" ".join(excerpts).split()) <= 250:
        return "Bill text: " + " ".join(excerpts)
    # Share the same source-backed synopsis rules used by stored analysis.
    # A table of contents is only a last-resort index, not a successful synopsis.
    from .extraction.synopsis import structured_synopsis, _source_provision_synopsis
    synopsis = structured_synopsis(sections, (), text) or _source_provision_synopsis(sections, text)
    if synopsis:
        return synopsis[0]
    headings = list(dict.fromkeys(
        normalize_reader_fragment(s.heading).strip().rstrip(".")
        for s in candidates if s.heading
    ))
    selected = []
    for heading in headings:
        if len(selected) >= 6 or sum(len(h) for h in selected) + len(heading) > 700:
            break
        selected.append(heading)
    if selected:
        remainder = len(headings) - len(selected)
        return (
            "Bill-text overview — sections cover: " + "; ".join(selected) + "."
            + (f" There are {remainder} additional section topics." if remainder else "")
            + " Read the source for the requirements, exceptions, and complete wording."
        )
    # Unstructured short documents can still be shown faithfully. Do not turn
    # title-only text or truncated passages into a claim about the bill.
    cleaned = normalize_reader_fragment(text)
    if not sections and not excluded and len(cleaned.split()) <= 160 and cleaned.endswith("."):
        return "Bill text: " + cleaned
    return None
