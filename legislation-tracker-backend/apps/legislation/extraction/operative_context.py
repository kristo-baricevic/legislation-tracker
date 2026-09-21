"""Source-owned clause context shared by payment extraction and synopses.

Each leaf sentence is visited once. Ancestors supply context, not duplicate
facts. This is a conservative grammar for supported patterns, not general NLP.
"""

import re
from dataclasses import dataclass

from .federal_clauses import _parent_section, _quoted_block_ranges
from .federal_structure import sentence_spans
from .types import SourceSpan, StructuralSection

MODAL = re.compile(r"\b(?:shall|must|may)(?:\s+not)?\b", re.I)
DISCUSSION = re.compile(
    r"\b(?:report|study|recommend|determine)\b.*\b(?:whether|that|to)\b", re.I | re.S
)
COORDINATE = re.compile(
    r"\bexcept that\s+|[,;]?\s+\b(?:and|but)\s+(?=(?:the\s+\w+|an?\s+\w+|applicants|any\s+person|renewing\s+applicants)\b[^.;]*?\b(?:shall|must|may)\b)",
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
    if parent and parent.disposition in {"prohibition", "discussion"}:
        disposition = parent.disposition
    elif DISCUSSION.search(text) or re.search(r"\bwhether\b", text, re.I):
        disposition = "discussion"
    elif modal and (
        "not" in modal.group().lower()
        or re.search(
            r"\b(?:no|neither)\s+(?:agency|person|applicant|alien|individual|entity|department|officer|secretary)\b",
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
            whole = _classify(section, sentence, parent)
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
