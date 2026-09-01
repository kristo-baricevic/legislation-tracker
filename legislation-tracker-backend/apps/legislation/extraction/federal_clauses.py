"""Deterministic clause boundaries for flattened Congress XML text."""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from .federal_structure import sentence_spans
from .types import SourceSpan, StructuralSection

_MODAL_RE = re.compile(
    r"\b(?P<modal>shall not|may not|is prohibited from|is required to|"
    r"is authorized to|shall|must|may)\b",
    re.IGNORECASE,
)
_LEADING_CONDITION_RE = re.compile(
    r"^(?P<condition>(?:if|when|unless|subject\s+to)\b.*?),\s*(?P<actor>.+)$",
    re.IGNORECASE,
)
_AMENDMENT_INSTRUCTION_RE = re.compile(
    r"\b(?:strik(?:e|ing)|insert(?:ing)?|replac(?:e|ing)|redesignat(?:e|ing)|"
    r"repeal(?:ing)?|amend(?:ing)?)\b",
    re.IGNORECASE,
)
_QUOTED_BLOCK_START = "[[QUOTED_BLOCK_START]]"
_QUOTED_BLOCK_END = "[[QUOTED_BLOCK_END]]"
_OPERATIVE_LEVELS = {"section", "subsection", "paragraph", "subparagraph", "clause"}


@dataclass(frozen=True)
class ModalContext:
    modal: str
    actor: str
    evidence: SourceSpan
    conditions: tuple[str, ...] = ()
    inherited: bool = False


def _strip(value: str) -> str:
    return value.strip().rstrip(".;:—–-").strip()


def _quoted_block_ranges(source_text: str) -> tuple[tuple[int, int], ...]:
    ranges = []
    cursor = 0
    while (start := source_text.find(_QUOTED_BLOCK_START, cursor)) >= 0:
        end = source_text.find(_QUOTED_BLOCK_END, start + len(_QUOTED_BLOCK_START))
        end = len(source_text) if end < 0 else end + len(_QUOTED_BLOCK_END)
        ranges.append((start, end))
        cursor = end
    return tuple(ranges)


def _intersects_quoted_block(
    span: SourceSpan, ranges: Sequence[tuple[int, int]]
) -> bool:
    return any(span.start_char < end and start < span.end_char for start, end in ranges)


def _actor_and_conditions(value: str) -> tuple[str, tuple[str, ...]]:
    candidate = _strip(value)
    leading = _LEADING_CONDITION_RE.match(candidate)
    if leading is None:
        return candidate, ()
    return _strip(leading.group("actor")), (_strip(leading.group("condition")),)


def _split_modal_clauses(
    sentence: SourceSpan,
) -> tuple[tuple[SourceSpan, ModalContext | None], ...]:
    matches = list(_MODAL_RE.finditer(sentence.text))
    if len(matches) < 2 or _AMENDMENT_INSTRUCTION_RE.search(sentence.text):
        return ((sentence, None),)

    actor, conditions = _actor_and_conditions(sentence.text[: matches[0].start()])
    clauses = []
    for index, match in enumerate(matches):
        start = 0 if index == 0 else match.start()
        end = (
            len(sentence.text)
            if index + 1 == len(matches)
            else matches[index + 1].start()
        )
        if index + 1 < len(matches):
            connector = re.search(
                r"\s+(?:and|or)\s+$", sentence.text[start:end], re.IGNORECASE
            )
            if connector is not None:
                end = start + connector.start()
        while end > start and sentence.text[end - 1].isspace():
            end -= 1
        span = SourceSpan(
            sentence.text[start:end],
            sentence.start_char + start,
            sentence.start_char + end,
        )
        context = (
            None
            if index == 0 or not actor
            else ModalContext(
                modal=matches[index - 1].group("modal").casefold(),
                actor=actor,
                evidence=sentence,
                conditions=conditions,
            )
        )
        clauses.append((span, context))
    return tuple(clauses)


def _parent_section(
    section: StructuralSection, sections: Sequence[StructuralSection]
) -> StructuralSection | None:
    candidates = [
        candidate
        for candidate in sections
        if candidate.span.start_char < section.span.start_char
        and section.span.end_char <= candidate.span.end_char
    ]
    return max(
        candidates, key=lambda candidate: candidate.span.start_char, default=None
    )


def _ancestor_modal_context(
    source_text: str,
    section: StructuralSection,
    sections: Sequence[StructuralSection],
    quoted_ranges: Sequence[tuple[int, int]],
) -> ModalContext | None:
    parent = _parent_section(section, sections)
    while parent is not None:
        for sentence in reversed(sentence_spans(parent, source_text)):
            if _intersects_quoted_block(sentence, quoted_ranges):
                continue
            matches = list(_MODAL_RE.finditer(sentence.text))
            if not matches:
                continue
            match = matches[-1]
            actor, conditions = _actor_and_conditions(sentence.text[: match.start()])
            action = _strip(sentence.text[match.end() :])
            if actor and not action:
                return ModalContext(
                    modal=match.group("modal").casefold(),
                    actor=actor,
                    evidence=sentence,
                    conditions=conditions,
                    inherited=True,
                )
        parent = _parent_section(parent, sections)
    return None


def iter_operative_clauses(
    source_text: str, sections: Sequence[StructuralSection]
) -> Iterator[tuple[StructuralSection, SourceSpan, ModalContext | None]]:
    """Yield raw, source-offset-preserving clauses outside quoted amendment text."""

    quoted_ranges = _quoted_block_ranges(source_text)
    for section in sections:
        if section.level not in _OPERATIVE_LEVELS:
            continue
        inherited = _ancestor_modal_context(
            source_text, section, sections, quoted_ranges
        )
        for sentence in sentence_spans(section, source_text):
            if _intersects_quoted_block(sentence, quoted_ranges):
                continue
            matches = list(_MODAL_RE.finditer(sentence.text))
            if matches:
                yield from (
                    (section, clause, context)
                    for clause, context in _split_modal_clauses(sentence)
                )
            else:
                yield section, sentence, inherited
