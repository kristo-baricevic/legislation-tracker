"""Source-owned clause context shared by payment extraction and synopses.

Each leaf sentence is visited once. Ancestors supply context, not duplicate
facts. This is a conservative grammar for supported patterns, not general NLP.
"""

import re
from dataclasses import dataclass, replace

from .federal_clauses import _parent_section, _quoted_block_ranges
from .federal_structure import sentence_spans
from .types import SourceSpan, StructuralSection

MODAL = re.compile(r"\b(?:shall|must|may)(?:\s+not)?\b", re.I)
DISCUSSION = re.compile(
    r"\b(?:report|study|recommend|determine)\b.*\b(?:whether|that|to)\b", re.I | re.S
)
COORDINATE = re.compile(
    r"\bexcept that\s+|[,;]?\s+\b(?:and|but)\s+(?=(?:shall|must|may)\s+(?:pay|be exempted)\b|(?:the\s+\w+|an?\s+\w+|applicants|any\s+person|renewing\s+applicants)\b[^.;]*?\b(?:shall|must|may)\b)",
    re.I,
)


@dataclass(frozen=True)
class OperativeClause:
    section: StructuralSection
    span: SourceSpan
    actor: str
    modality: str | None
    action: str
    disposition: str
    context: tuple[SourceSpan, ...] = ()

    @property
    def asserted(self):
        return self.disposition == "operative"

    @property
    def evidence(self):
        return (*self.context, self.span)


def _classify(section, span, parent=None):
    text = span.text
    modal = MODAL.search(text)
    actor = text[: modal.start()].strip() if modal else ""
    action = text[modal.end() :].strip() if modal else text
    disposition = "operative"
    if parent and parent.disposition in {"prohibition", "discussion", "uncertain"}:
        disposition = parent.disposition
    elif modal and (
        re.search(r"\b(?:who|which|that)\b", actor, re.I)
        and len(list(MODAL.finditer(text))) > 1
    ):
        # A modal inside a relative clause is not necessarily the governing verb.
        disposition = "uncertain"
    elif DISCUSSION.search(text) or re.match(r"establish\s+whether\b", action, re.I):
        disposition = "discussion"
    elif (
        len(list(MODAL.finditer(text))) > 1
        and re.search(
            r"\b(?:which|that)\b.*\b(?:shall|must|may)\b",
            re.sub(r"\bexcept that\b", "except", action, flags=re.I),
            re.I | re.S,
        )
        and not re.search(r"\b(?:shall|must)\s+not\s+exceed\b", action, re.I)
    ):
        disposition = "uncertain"
    elif modal and (
        "not" in modal.group().lower()
        or re.search(
            r"(?:^|,\s*)(?:no(?!\s+later\b)|neither)\b",
            actor,
            re.I,
        )
    ):
        disposition = "prohibition"
    elif not modal and parent is None:
        disposition = "unasserted"
    return OperativeClause(
        section,
        span,
        actor or (parent.actor if parent else ""),
        modal.group().lower() if modal else (parent.modality if parent else None),
        action,
        disposition,
        parent.evidence if parent else (),
    )


def parse_operative_clauses(source, sections):
    quoted = _quoted_block_ranges(source)
    introductions = {}
    clauses = []
    for section in sections:
        parent_section = _parent_section(section, sections)
        parent = None
        while parent_section is not None:
            if parent_section.source_id in introductions:
                parent = introductions[parent_section.source_id]
                break
            parent_section = _parent_section(parent_section, sections)
        for sentence in sentence_spans(section, source):
            if any(
                sentence.start_char < end and start < sentence.end_char
                for start, end in quoted
            ):
                continue
            # Explicit exceptions are a supported boundary: classify each side
            # before attempting to interpret nested modals across that boundary.
            exception_parts = list(
                re.finditer(r"\bexcept that\s+", sentence.text, re.I)
            )
            whole = _classify(section, sentence, parent)
            first_modal = MODAL.search(sentence.text)
            if whole.disposition == "discussion" and re.search(
                r"[,;]\s*(?:and|but)\b.*\b(?:shall|must|may)\b",
                sentence.text[first_modal.end() :] if first_modal else "",
                re.I | re.S,
            ):
                # Coordination after a discussion may be inside or outside its
                # scope. Preserve the whole source rather than guessing.
                whole = replace(whole, disposition="uncertain")
            if whole.disposition == "uncertain" and (
                not exception_parts or DISCUSSION.search(sentence.text)
            ):
                clauses.append(whole)
                if sentence.text.rstrip().endswith(("—", "–", ":")):
                    introductions[section.source_id] = whole
                continue
            separators = (
                []
                if whole.disposition == "discussion"
                else list(COORDINATE.finditer(sentence.text))
            )
            starts = [0] + [
                m.start() if m.group().lower().startswith("except that") else m.end()
                for m in separators
            ]
            ends = [m.start() for m in separators] + [len(sentence.text)]
            for start, end in zip(starts, ends, strict=True):
                while start < end and sentence.text[start].isspace():
                    start += 1
                while end > start and sentence.text[end - 1].isspace():
                    end -= 1
                span = SourceSpan(
                    sentence.text[start:end],
                    sentence.start_char + start,
                    sentence.start_char + end,
                )
                clause = _classify(section, span, parent)
                clauses.append(clause)
                if span.text.rstrip().endswith(("—", "–", ":")):
                    introductions[section.source_id] = clause
    return tuple(clauses)
