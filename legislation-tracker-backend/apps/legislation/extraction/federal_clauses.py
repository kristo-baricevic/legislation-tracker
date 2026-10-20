"""Deterministic clause boundaries for flattened Congress XML text."""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from functools import lru_cache

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
_OPERATIVE_LEVELS = {"section", "subsection", "paragraph", "subparagraph", "clause", "subclause", "item", "subitem"}

_CALENDAR_DATE = re.compile(
    r"\b(?:May\s+(?:\d{4}|\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*\d{4})?)|"
    r"\d{1,2}(?:st|nd|rd|th)?\s+(?:day\s+of\s+)?May(?:\s*,?\s*\d{4})?)\b",
    re.I,
)


def grammar_text(text):
    """Mask calendar dates for modal recognition without changing offsets."""
    return _CALENDAR_DATE.sub(lambda m: " " * len(m.group()), text)


@dataclass(frozen=True)
class ModalContext:
    modal: str
    actor: str
    evidence: SourceSpan
    conditions: tuple[str, ...] = ()
    inherited: bool = False


def _strip(value: str) -> str:
    return value.strip().rstrip(".;:—–-").strip()


@lru_cache(maxsize=2)
def _quoted_block_ranges(source_text: str) -> tuple[tuple[int, int], ...]:
    """Ranges of nonoperative quotations, not explicitly inserted new law.

    Classify the immediately preceding instruction, never a distant occurrence
    of "insert". Nested background/deleted quotations remain excluded. An
    unclosed block is conservatively excluded even with an insertion instruction.
    Offsets always refer to the untouched source.
    """
    ranges = []
    stack = []
    sections = None
    inserted_tail = r"the following(?: new)?(?: (?:subclauses?|clauses?|subparagraphs?|paragraphs?|subsections?|sections?|sentences?|items?|subtitles?|titles?|subchapters?|chapters?|subparts?|parts?|divisions?))?"
    marker = re.compile(
        re.escape(_QUOTED_BLOCK_START) + "|" + re.escape(_QUOTED_BLOCK_END)
    )
    for match in marker.finditer(source_text):
        if match.group() == _QUOTED_BLOCK_START:
            prefix = source_text[:match.start()].rstrip()
            instruction = prefix.rsplit("\n", 1)[-1]
            # Classify the terminal operation, not the name of the added
            # structural unit. Ignore verbs inside inline quoted old wording.
            grammar = re.sub(r'''"[^"\n]*"|“[^”\n]*”|(?<!\w)'[^'\n]*'(?!\w)|‘[^’\n]*’''', ' ', instruction)
            grammar = re.sub(
                r'\(and\s+(?:amending|conforming)\s+the\s+table\s+of\s+(?:sections|contents)\b[^()\n]*\)',
                ' ', grammar, flags=re.I,
            )
            grammar = re.sub(r',?\s+and redesignating succeeding (?:paragraphs|subsections|sections) accordingly(?=[:—–-]?$)', '', grammar, flags=re.I)
            amended = re.search(r'\b(?:is|are)(?: further)? amended\b|\band amended(?= to read\b)', grammar, re.I)
            operations = list(re.finditer(
                r'\b(?:by|and)\s+(?:by\s+)?(?P<verb>adding|inserting|striking|repealing|redesignating|amending)\b|\b(?P<replace>to read(?: as follows)?)\b',
                grammar[amended.end():] if amended else '', re.I,
            ))
            has_payload_boundary = grammar.rstrip().endswith((':','—','–','-')) or bool(re.search(r'\b(?:adding|inserting) at the end$', grammar, re.I))
            inserted = bool(amended and operations and has_payload_boundary and (
                operations[-1].group('replace') or operations[-1].group('verb').lower() in {'adding','inserting'}
            ))
            if not inserted and re.fullmatch(
                rf"\([A-Za-z0-9]+\)\s+by\s+(?:inserting|adding)\b[^\n]*\b{inserted_tail}\s*[:—–-]",
                instruction, re.I,
            ):
                # A child instruction inherits only an actual structural
                # ancestor's amendment, never an unrelated earlier section.
                from .federal_structure import parse_federal_structure
                if sections is None:
                    sections = parse_federal_structure(source_text)
                offset = len(prefix) - len(instruction)
                owners = [s for s in sections if s.span.start_char <= offset < s.span.end_char]
                owner = max(owners, key=lambda s: s.span.start_char) if owners else None
                parent = _parent_section(owner, sections) if owner else None
                while parent is not None:
                    parent_sentences = sentence_spans(parent, source_text)
                    if parent_sentences and re.search(r"\bis amended\s*[:—–-]$", parent_sentences[-1].text, re.I):
                        inserted = True
                        break
                    parent = _parent_section(parent, sections)
            stack.append((match.start(), inserted))
        elif stack:
            start, inserted = stack.pop()
            if not inserted:
                ranges.append((start, match.end()))
    ranges.extend((start, len(source_text)) for start, _ in stack)
    return tuple(sorted(ranges))


def _intersects_quoted_block(
    span: SourceSpan, ranges: Sequence[tuple[int, int]]
) -> bool:
    return any(span.start_char < end and start < span.end_char for start, end in ranges)


def _actor_and_conditions(
    value: str, *, reader_mode=False
) -> tuple[str, tuple[str, ...]]:
    candidate = _strip(value)
    leading = (
        re.match(
            r"^(?P<condition>(?:if|when|unless|subject\s+to|for\s+fiscal\s+years?)\b.*),\s*(?P<actor>[^,]+)$",
            candidate,
            re.I | re.S,
        )
        if reader_mode
        else _LEADING_CONDITION_RE.match(candidate)
    )
    if leading is None:
        return candidate, ()
    return _strip(leading.group("actor")), (_strip(leading.group("condition")),)


def _explicit_actor_boundary(
    sentence: SourceSpan,
    previous: re.Match[str],
    current: re.Match[str],
    *,
    reader_mode=False,
) -> tuple[int, int] | None:
    between = sentence.text[previous.end() : current.start()]
    connectors = "and|or|but" if reader_mode else "and|or"
    match = re.search(
        rf"(?P<connector>\s+(?:{connectors})\s+)(?P<actor>\S(?:.*\S)?)\s*$",
        between,
        re.IGNORECASE | (re.DOTALL if reader_mode else 0),
    )
    if match is None:
        return None
    return (
        previous.end() + match.start("connector"),
        previous.end() + match.start("actor"),
    )


def _split_modal_clauses(
    sentence: SourceSpan,
    *,
    reader_mode=False,
) -> tuple[tuple[SourceSpan, ModalContext | None], ...]:
    such_sums = tuple(
        re.finditer(r"\bsuch sums as may be necessary\b", sentence.text, re.I)
    )
    matches = [
        m
        for m in _MODAL_RE.finditer(
            grammar_text(sentence.text) if reader_mode else sentence.text
        )
        if not any(s.start() <= m.start() < s.end() for s in such_sums)
    ]
    if len(matches) < 2 or _AMENDMENT_INSTRUCTION_RE.search(sentence.text):
        return ((sentence, None),)

    actor, conditions = _actor_and_conditions(
        sentence.text[: matches[0].start()], reader_mode=reader_mode
    )
    active_actor = actor
    active_conditions = conditions
    boundaries = [
        (
            _explicit_actor_boundary(
                sentence, matches[index - 1], match, reader_mode=reader_mode
            )
            if index > 0
            else None
        )
        for index, match in enumerate(matches)
    ]
    clauses = []
    for index, match in enumerate(matches):
        prior_boundary = boundaries[index]
        if prior_boundary is not None:
            explicit_actor, explicit_conditions = _actor_and_conditions(
                sentence.text[prior_boundary[1] : match.start()],
                reader_mode=reader_mode,
            )
            if explicit_actor:
                active_actor = explicit_actor
            if explicit_conditions:
                active_conditions = explicit_conditions
        start = (
            0
            if index == 0
            else (prior_boundary[1] if prior_boundary else match.start())
        )
        next_boundary = boundaries[index + 1] if index + 1 < len(matches) else None
        end = (
            len(sentence.text)
            if index + 1 == len(matches)
            else (next_boundary[0] if next_boundary else matches[index + 1].start())
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
            if index == 0
            or (prior_boundary is not None and not reader_mode)
            or not active_actor
            else ModalContext(
                modal=matches[index - 1].group("modal").casefold(),
                actor=active_actor,
                evidence=sentence,
                conditions=active_conditions,
            )
        )
        clauses.append((span, context))
    return tuple(clauses)


def _parent_section(
    section: StructuralSection, sections: Sequence[StructuralSection]
) -> StructuralSection | None:
    parents = getattr(sections, "parents", {})
    if id(section) in parents:
        return parents[id(section)]
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
    *,
    reader_mode=False,
) -> ModalContext | None:
    parent = _parent_section(section, sections)
    while parent is not None:
        for sentence in reversed(sentence_spans(parent, source_text)):
            if _intersects_quoted_block(sentence, quoted_ranges):
                continue
            matches = list(
                _MODAL_RE.finditer(
                    grammar_text(sentence.text) if reader_mode else sentence.text
                )
            )
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
    source_text: str,
    sections: Sequence[StructuralSection],
    *,
    reader_mode=False,
) -> Iterator[tuple[StructuralSection, SourceSpan, ModalContext | None]]:
    """Yield raw, source-offset-preserving clauses outside quoted amendment text."""

    quoted_ranges = _quoted_block_ranges(source_text)
    for section in sections:
        if section.level not in _OPERATIVE_LEVELS:
            continue
        inherited = _ancestor_modal_context(
            source_text,
            section,
            sections,
            quoted_ranges,
            reader_mode=reader_mode,
        )
        for sentence in sentence_spans(section, source_text):
            if _intersects_quoted_block(sentence, quoted_ranges):
                continue
            matches = list(
                _MODAL_RE.finditer(
                    grammar_text(sentence.text) if reader_mode else sentence.text
                )
            )
            if matches:
                yield from (
                    (section, clause, context)
                    for clause, context in _split_modal_clauses(
                        sentence, reader_mode=reader_mode
                    )
                )
            else:
                yield section, sentence, inherited
