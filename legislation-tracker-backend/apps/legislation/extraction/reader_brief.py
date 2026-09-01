"""Build a complete, source-ordered reader projection from extracted claims."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from .display_text import normalize_reader_fragment
from .reader_renderer import render_reader_claim
from .types import (
    ExtractedClaim,
    ExtractionWarning,
    IdentifiedClaim,
    ReaderBrief,
    ReaderLineItem,
    ReaderOrientation,
    ReaderSectionGroup,
    ReaderStats,
    RenderedReaderClaim,
    SectionPathItem,
    SourceSpan,
    StructuralSection,
)

_PREFIX_BY_CATEGORY = {
    "requirements": "requirement",
    "amendment_operations": "amendment",
    "applicability": "applicability",
    "financial_items": "financial",
    "timeline_items": "timeline",
    "definitions": "definition",
}
_CATEGORY_ORDER = {
    "requirements": 0,
    "amendment_operations": 1,
    "applicability": 2,
    "financial_items": 3,
    "timeline_items": 4,
    "definitions": 5,
}
_OPERATIVE_CATEGORIES = {"requirements", "amendment_operations", "applicability"}


@dataclass
class _LineDraft:
    id: str
    source_id: str
    section_id: str
    section_path: tuple[SectionPathItem, ...]
    rendered: RenderedReaderClaim
    claim_refs: tuple[str, ...]
    evidence: tuple[SourceSpan, ...]
    exact_financial_refs: list[str] = field(default_factory=list)
    timeline_refs: list[str] = field(default_factory=list)
    definition_refs: list[str] = field(default_factory=list)


def _identified_claims(claims: Sequence[ExtractedClaim]) -> tuple[IdentifiedClaim, ...]:
    supported = [claim for claim in claims if claim.category in _PREFIX_BY_CATEGORY]
    ordered = sorted(
        supported,
        key=lambda claim: (
            claim.evidence[0].start_char,
            _CATEGORY_ORDER[claim.category],
        ),
    )
    ordinals: dict[tuple[str, int], int] = defaultdict(int)
    identified = []
    for claim in ordered:
        prefix = _PREFIX_BY_CATEGORY[claim.category]
        offset = claim.evidence[0].start_char
        ordinals[(prefix, offset)] += 1
        identified.append(
            IdentifiedClaim(
                id=f"{prefix}-{offset}-{ordinals[(prefix, offset)]}",
                claim=claim,
            )
        )
    return tuple(identified)


def _section_id(claim: ExtractedClaim) -> str:
    return (
        claim.section_id or claim.source_id or f"section-{claim.evidence[0].start_char}"
    )


def _same_evidence(left: Sequence[SourceSpan], right: Sequence[SourceSpan]) -> bool:
    left_offsets = {(item.start_char, item.end_char) for item in left}
    return any((item.start_char, item.end_char) in left_offsets for item in right)


def _normalized(value: str) -> str:
    return normalize_reader_fragment(value).casefold().strip()


def _line_reference_text(line: _LineDraft) -> str:
    values = (
        line.rendered.actor,
        line.rendered.action,
        line.rendered.effect,
        *(span.text for span in line.evidence),
    )
    return _normalized(" ".join(value for value in values if value))


def _explicit_financial_candidates(
    item: IdentifiedClaim, lines: Sequence[_LineDraft]
) -> list[_LineDraft]:
    references = [
        _normalized(value)
        for key in ("purpose", "source_account", "destination_account")
        if (value := item.claim.fields.get(key)) and isinstance(value, str)
    ]
    if not references:
        return []
    return [
        line
        for line in lines
        if line.section_id == _section_id(item.claim)
        and any(reference in _line_reference_text(line) for reference in references)
    ]


def _definition_occurs(term: object, line: _LineDraft) -> bool:
    if not isinstance(term, str) or not (normalized_term := _normalized(term)):
        return False
    source = _normalized(" ".join(span.text for span in line.evidence))
    return re.search(rf"(?<!\w){re.escape(normalized_term)}(?!\w)", source) is not None


def _standalone_line(item: IdentifiedClaim) -> _LineDraft | ExtractionWarning:
    rendered = render_reader_claim(item.claim)
    if isinstance(rendered, ExtractionWarning):
        return rendered
    financial_refs = [item.id] if item.claim.category == "financial_items" else []
    timeline_refs = [item.id] if item.claim.category == "timeline_items" else []
    return _LineDraft(
        id=f"line-{item.id}",
        source_id=item.id,
        section_id=_section_id(item.claim),
        section_path=item.claim.section_path,
        rendered=rendered,
        claim_refs=(item.id,),
        evidence=item.claim.evidence,
        exact_financial_refs=financial_refs,
        timeline_refs=timeline_refs,
    )


def _reader_line(line: _LineDraft) -> ReaderLineItem:
    return ReaderLineItem(
        id=line.id,
        source_id=line.source_id,
        section_id=line.section_id,
        section_path=line.section_path,
        kind=line.rendered.kind,
        display_text=line.rendered.display_text,
        actor=line.rendered.actor,
        action=line.rendered.action,
        effect=line.rendered.effect,
        claim_refs=line.claim_refs,
        exact_financial_refs=tuple(line.exact_financial_refs),
        timeline_refs=tuple(line.timeline_refs),
        definition_refs=tuple(line.definition_refs),
        evidence=line.evidence,
    )


def _coverage_note(stats: ReaderStats) -> str:
    financial_label = (
        "financial provision"
        if stats.financial_item_count == 1
        else "financial provisions"
    )
    timeline_label = (
        "deadline or effective date"
        if stats.timeline_item_count == 1
        else "deadlines or effective dates"
    )
    line_label = "line item" if stats.line_item_count == 1 else "line items"
    section_label = "section" if stats.section_group_count == 1 else "sections"
    return (
        "The breakdown below contains "
        f"{stats.line_item_count} recognized operative {line_label} across "
        f"{stats.section_group_count} {section_label}, including "
        f"{stats.financial_item_count} {financial_label} and "
        f"{stats.timeline_item_count} {timeline_label}."
    )


def build_reader_brief(
    claims: Sequence[ExtractedClaim], sections: Sequence[StructuralSection]
) -> ReaderBrief:
    warnings = []
    rendered_by_claim: dict[int, RenderedReaderClaim] = {}
    renderable_claims = []
    for claim in claims:
        if claim.category not in _PREFIX_BY_CATEGORY:
            continue
        rendered = render_reader_claim(claim)
        if isinstance(rendered, ExtractionWarning):
            warnings.append(rendered)
            continue
        renderable_claims.append(claim)
        rendered_by_claim[id(claim)] = rendered

    identified = _identified_claims(renderable_claims)
    financial_items = tuple(
        item for item in identified if item.claim.category == "financial_items"
    )
    timeline_items = tuple(
        item for item in identified if item.claim.category == "timeline_items"
    )
    definition_items = tuple(
        item for item in identified if item.claim.category == "definitions"
    )
    lines = []

    for item in identified:
        if item.claim.category not in _OPERATIVE_CATEGORIES:
            continue
        rendered = rendered_by_claim[id(item.claim)]
        lines.append(
            _LineDraft(
                id=f"line-{item.id}",
                source_id=item.id,
                section_id=_section_id(item.claim),
                section_path=item.claim.section_path,
                rendered=rendered,
                claim_refs=(item.id,),
                evidence=item.claim.evidence,
            )
        )

    operative_lines = tuple(lines)

    section_financial_refs: dict[str, list[str]] = defaultdict(list)
    for item in financial_items:
        same_section = [
            line
            for line in operative_lines
            if line.section_id == _section_id(item.claim)
        ]
        exact = [
            line
            for line in same_section
            if _same_evidence(line.evidence, item.claim.evidence)
        ]
        if len(exact) != 1:
            exact = []
            candidates = _explicit_financial_candidates(item, same_section)
            exact = candidates if len(candidates) == 1 else []
        if exact:
            for line in exact:
                line.exact_financial_refs.append(item.id)
        elif same_section:
            section_financial_refs[_section_id(item.claim)].append(item.id)
        else:
            standalone = _standalone_line(item)
            if isinstance(standalone, ExtractionWarning):
                warnings.append(standalone)
            else:
                lines.append(standalone)

    section_timeline_refs: dict[str, list[str]] = defaultdict(list)
    for item in timeline_items:
        same_section = [
            line
            for line in operative_lines
            if line.section_id == _section_id(item.claim)
        ]
        exact = [
            line
            for line in same_section
            if line.source_id != item.id
            and _same_evidence(line.evidence, item.claim.evidence)
        ]
        if len(exact) == 1:
            exact[0].timeline_refs.append(item.id)
        elif same_section:
            section_timeline_refs[_section_id(item.claim)].append(item.id)
        else:
            standalone = _standalone_line(item)
            if isinstance(standalone, ExtractionWarning):
                warnings.append(standalone)
            else:
                lines.append(standalone)

    lines.sort(key=lambda line: line.evidence[0].start_char)
    for definition in definition_items:
        for line in lines:
            if _definition_occurs(definition.claim.fields.get("term"), line):
                line.definition_refs.append(definition.id)

    line_items = tuple(_reader_line(line) for line in lines)
    section_by_id = {section.source_id: section for section in sections}
    relevant_section_ids = {
        *(line.section_id for line in lines),
        *section_financial_refs.keys(),
        *section_timeline_refs.keys(),
    }

    def section_start(section_id: str) -> int:
        section = section_by_id.get(section_id)
        if section is not None:
            return section.span.start_char
        offsets = [
            line.evidence[0].start_char
            for line in lines
            if line.section_id == section_id
        ]
        return min(offsets, default=0)

    section_groups = []
    for section_id in sorted(relevant_section_ids, key=section_start):
        section_lines = [line for line in lines if line.section_id == section_id]
        section = section_by_id.get(section_id)
        path = (
            section.path
            if section is not None
            else (section_lines[0].section_path if section_lines else ())
        )
        section_groups.append(
            ReaderSectionGroup(
                source_id=section_id,
                section_path=path,
                line_item_ids=tuple(line.id for line in section_lines),
                section_financial_refs=tuple(section_financial_refs[section_id]),
                section_timeline_refs=tuple(section_timeline_refs[section_id]),
            )
        )

    stats = ReaderStats(
        line_item_count=len(line_items),
        financial_item_count=len(financial_items),
        timeline_item_count=len(timeline_items),
        definition_item_count=len(definition_items),
        section_group_count=len(section_groups),
    )
    return ReaderBrief(
        coverage_note=_coverage_note(stats),
        orientation=ReaderOrientation(None, None),
        reader_stats=stats,
        section_groups=tuple(section_groups),
        line_items=line_items,
        identified_claims=identified,
        financial_items=financial_items,
        timeline_items=timeline_items,
        definition_items=definition_items,
        warnings=tuple(warnings),
    )
