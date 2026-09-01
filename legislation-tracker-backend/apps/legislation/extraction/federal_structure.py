import re
from dataclasses import dataclass

from .types import (
    ExpectedExtractionRejection,
    SectionPathItem,
    SourceSpan,
    StructuralSection,
)

SECTION_RE = re.compile(
    r"(?im)^(?P<indent>[ \t]*)(?P<kind>SEC\.|SECTION)[ \t]+"
    r"(?P<label>[0-9]+[A-Z]?(?:-[0-9A-Z]+)*)\.[ \t]*(?P<heading>[^\n]*)$"
)
CONTAINER_RE = re.compile(
    r"(?im)^[ \t]*(?P<kind>DIVISION|TITLE|SUBTITLE|CHAPTER|SUBCHAPTER|PART|"
    r"SUBPART|ACCOUNT|SUBACCOUNT|SUBSUBACCOUNT|SUBSUBSUBACCOUNT|ARTICLE|"
    r"SUBDIVISION)[ \t]+"
    r"(?P<label>[IVXLCDM0-9A-Z-]+)"
    r"(?:(?:[.—-][ \t]*|[ \t]+)(?P<heading>[^\n]*))?[ \t]*$"
)
SUBDIVISION_RE = re.compile(r"(?m)^[ \t]*(?P<label>\([a-z0-9A-Zivxlcdm]+\))\s*")

CONTAINER_RANKS = {
    "division": 0,
    "title": 10,
    "subtitle": 20,
    "chapter": 30,
    "subchapter": 40,
    "part": 50,
    "subpart": 60,
    "account": 70,
    "subaccount": 80,
    "subsubaccount": 81,
    "subsubsubaccount": 82,
    "article": 90,
    "subdivision": 100,
}
_SECTION_RANK = 110
_SUBSECTION_RANK = 120
_PARAGRAPH_RANK = 130
_SUBPARAGRAPH_RANK = 140
_CLAUSE_RANK = 150
_HEADING_SEPARATOR_RE = re.compile(r"^(?P<heading>[^\n]{1,160}?)(?:\.—|\.—|—|\. -|\.―)")
_SENTENCE_BOUNDARY_RE = re.compile(r"[.!?](?=\s|$)")
_STATUTORY_ABBREVIATION_RE = re.compile(
    r"\b(?:U\.S\.C|U\.S|Sec|No|e\.g|i\.e)\.$",
    re.IGNORECASE,
)


@dataclass
class _Marker:
    start: int
    rank: int
    level: str
    label: str
    heading: str | None


def _line_end(source_text: str, start: int) -> int:
    newline = source_text.find("\n", start)
    return len(source_text) if newline == -1 else newline + 1


def _looks_like_next_line_heading(value: str) -> bool:
    heading = value.strip()
    if not heading or len(heading) > 160 or len(heading.split()) > 18:
        return False
    if (
        SECTION_RE.fullmatch(heading)
        or CONTAINER_RE.fullmatch(heading)
        or SUBDIVISION_RE.match(heading)
    ):
        return False
    if heading.endswith((".", ";", ":", "?", "!")):
        return False
    lowered = heading.casefold()
    return not any(modal in lowered for modal in (" shall ", " may ", " must "))


def _next_line_heading(source_text: str, line_end: int) -> tuple[str | None, int]:
    if line_end >= len(source_text):
        return None, line_end
    next_end = _line_end(source_text, line_end)
    candidate = source_text[line_end:next_end].strip()
    if _looks_like_next_line_heading(candidate):
        return candidate, next_end
    return None, line_end


def _subdivision_rank(label: str, prior_markers: list[_Marker]) -> int:
    token = label[1:-1]
    if token.isdigit():
        return _PARAGRAPH_RANK
    if token.isupper():
        return _SUBPARAGRAPH_RANK
    if re.fullmatch(r"[ivxlcdm]+", token) and any(
        marker.rank >= _SUBPARAGRAPH_RANK for marker in prior_markers[-3:]
    ):
        return _CLAUSE_RANK
    return _SUBSECTION_RANK


def _provision_level(rank: int) -> str:
    return {
        _SUBSECTION_RANK: "subsection",
        _PARAGRAPH_RANK: "paragraph",
        _SUBPARAGRAPH_RANK: "subparagraph",
        _CLAUSE_RANK: "clause",
    }[rank]


def _container_markers(source_text: str) -> list[_Marker]:
    markers = []
    for match in CONTAINER_RE.finditer(source_text):
        kind = match.group("kind").lower()
        line_end = _line_end(source_text, match.start())
        heading = (match.group("heading") or "").strip() or None
        if heading is None:
            heading, _ = _next_line_heading(source_text, line_end)
        markers.append(
            _Marker(
                start=match.start(),
                rank=CONTAINER_RANKS[kind],
                level=kind,
                label=f"{kind.title()} {match.group('label').upper()}",
                heading=heading,
            )
        )
    return markers


def _section_markers(source_text: str) -> list[_Marker]:
    markers = []
    for match in SECTION_RE.finditer(source_text):
        line_end = _line_end(source_text, match.start())
        heading = match.group("heading").strip() or None
        if heading is None:
            heading, _ = _next_line_heading(source_text, line_end)
        label_prefix = "Sec." if match.group("kind").upper() == "SEC." else "Section"
        markers.append(
            _Marker(
                start=match.start(),
                rank=_SECTION_RANK,
                level="section",
                label=f"{label_prefix} {match.group('label').upper()}",
                heading=heading,
            )
        )
    return markers


def _subdivision_markers(source_text: str, prior: list[_Marker]) -> list[_Marker]:
    markers = []
    for match in SUBDIVISION_RE.finditer(source_text):
        line_end = _line_end(source_text, match.start())
        remainder_start = match.end()
        remainder = source_text[remainder_start:line_end].rstrip("\r\n")
        separator = _HEADING_SEPARATOR_RE.match(remainder)
        heading = separator.group("heading").strip() if separator else None
        rank = _subdivision_rank(match.group("label"), prior + markers)
        markers.append(
            _Marker(
                start=match.start(),
                rank=rank,
                level=_provision_level(rank),
                label=match.group("label"),
                heading=heading,
            )
        )
    return markers


def parse_federal_structure(source_text: str) -> tuple[StructuralSection, ...]:
    container_markers = _container_markers(source_text)
    section_markers = _section_markers(source_text)
    if not section_markers:
        raise ExpectedExtractionRejection("unrecognized_federal_structure")

    markers = sorted(
        container_markers + section_markers, key=lambda marker: marker.start
    )
    subdivisions = _subdivision_markers(source_text, markers)
    markers = sorted(markers + subdivisions, key=lambda marker: marker.start)

    sections = []
    stack: list[tuple[_Marker, str]] = []
    for index, marker in enumerate(markers):
        while stack and stack[-1][0].rank >= marker.rank:
            stack.pop()
        parent_label = stack[-1][1] if stack else None

        end = len(source_text)
        for later_marker in markers[index + 1 :]:
            if later_marker.rank <= marker.rank:
                end = later_marker.start
                break
        span = SourceSpan(source_text[marker.start : end], marker.start, end)
        path = tuple(
            SectionPathItem(
                label=ancestor.label,
                heading=ancestor.heading,
                level=ancestor.level,
            )
            for ancestor, _ in stack
        ) + (
            SectionPathItem(
                label=marker.label,
                heading=marker.heading,
                level=marker.level,
            ),
        )
        section = StructuralSection(
            label=marker.label,
            heading=marker.heading,
            level=marker.level,
            span=span,
            parent_label=parent_label,
            source_id=f"section-{marker.start}",
            path=path,
        )
        sections.append(section)
        stack.append((marker, marker.label))

    return tuple(sections)


def _content_start(section: StructuralSection, source_text: str) -> int:
    local_text = source_text[section.span.start_char : section.span.end_char]
    if section.level in {"subsection", "paragraph", "subparagraph", "clause"}:
        match = SUBDIVISION_RE.match(local_text)
        if match is None:
            return section.span.start_char
        remainder = local_text[match.end() : _line_end(local_text, 0)]
        separator = _HEADING_SEPARATOR_RE.match(remainder)
        local_start = match.end() + (separator.end() if separator else 0)
        return section.span.start_char + local_start

    first_line_end = _line_end(local_text, 0)
    local_start = first_line_end
    if section.heading and local_start < len(local_text):
        next_line_end = _line_end(local_text, local_start)
        if local_text[local_start:next_line_end].strip() == section.heading:
            local_start = next_line_end
    return section.span.start_char + local_start


def sentence_spans(
    section: StructuralSection, source_text: str
) -> tuple[SourceSpan, ...]:
    start = _content_start(section, source_text)
    end = section.span.end_char
    nested_marker = SUBDIVISION_RE.search(source_text, start, end)
    if nested_marker is not None:
        end = nested_marker.start()
    sentences = []
    cursor = start

    for boundary in _SENTENCE_BOUNDARY_RE.finditer(source_text, start, end):
        preceding_text = source_text[max(start, boundary.end() - 16) : boundary.end()]
        if _STATUTORY_ABBREVIATION_RE.search(preceding_text):
            continue
        sentence_start = cursor
        sentence_end = boundary.end()
        while sentence_start < sentence_end and source_text[sentence_start].isspace():
            sentence_start += 1
        while sentence_end > sentence_start and source_text[sentence_end - 1].isspace():
            sentence_end -= 1
        if sentence_start < sentence_end:
            sentences.append(
                SourceSpan(
                    source_text[sentence_start:sentence_end],
                    sentence_start,
                    sentence_end,
                )
            )
        cursor = boundary.end()

    terminal_start = cursor
    while terminal_start < end and source_text[terminal_start].isspace():
        terminal_start += 1
    terminal_end = end
    while terminal_end > terminal_start and source_text[terminal_end - 1].isspace():
        terminal_end -= 1
    if terminal_start < terminal_end:
        sentences.append(
            SourceSpan(
                source_text[terminal_start:terminal_end],
                terminal_start,
                terminal_end,
            )
        )

    return tuple(sentences)
