"""Pinned, lossless legal source graph. No generated text is source authority.

Sections are deliberately indivisible until a narrower split can prove preservation
of governing context. This trades throughput for not dropping list conditions.
"""

import hashlib
import re
from dataclasses import replace

from apps.legislation.extraction.federal_structure import parse_federal_structure
from apps.legislation.extraction.types import ExpectedExtractionRejection

from .types import Passage, SourceGraph, SourceUnit

NORMALIZATION_VERSION = "raw-decoded-v1"
REFERENCE = re.compile(
    r"\bsection\s+(\d+[A-Za-z]?)(?:\([A-Za-z0-9]+\))*\s+of\s+(this\s+Act\b|[^.;\n]+)",
    re.I,
)
BARE_REFERENCE = re.compile(r"\bsection\s+(\d+[A-Za-z]?)(?:\([A-Za-z0-9]+\))*", re.I)
FINANCIAL = re.compile(
    r"\$\s*\d|\b(?:appropriat(?:ed|ions?|e\s+funds)|authoriz\w*\s+to\s+be\s+appropriated|fees?|fines?|surcharge|percent)\b",
    re.I,
)


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def has_explainable_text(unit, graph):
    """Can the supplied text describe a rule, without filling in outside law?

    This is generation eligibility, not a finding that the rule was explained
    correctly. Unresolved references remain backend-owned visible limitations.
    """
    if "unrecognized_structure" in unit.unresolved_dependencies:
        return False
    raw = "\n".join(graph.passages[p].text for p in unit.own_passage_ids)
    return not unit.unresolved_dependencies or bool(
        re.search(
            r"\b(?:shall|may|must|means|has the meaning|is repealed|are authorized)\b",
            raw,
            re.I,
        )
    )


def _safe_subsection_starts(raw):
    """Only split large sections at a complete sequence of titled subsections.

    Quoted amendments and operative parent introductions remain indivisible.
    This deliberately does not trust the parser's ambiguous roman-numeral levels.
    """
    if len(raw.encode()) < 80000:
        return []
    markers = list(re.finditer(r"(?m)^ {0,4}\(([a-z])\) [A-Z][^\n]*?\.\s*--", raw))
    if len(markers) < 2 or [m[1] for m in markers] != list(
        "abcdefghijklmnopqrstuvwxyz"[: len(markers)]
    ):
        return []
    prefix = raw[: markers[0].start()]
    # Subsection-level definitions and cross-references can govern siblings.
    # Until that dependency graph is proven, keep their complete parent intact.
    if re.search(
        r"\b(?:definitions?|means|defined|meaning|subsections?|paragraphs?|subparagraphs?|clauses?)\b|\bthis section\b",
        raw,
        re.I,
    ) or re.search(
        r"\b(?:shall|may|must|only|unless|if|except|provided)\b", prefix, re.I
    ):
        return []
    if re.search(r"[a-z]", prefix) or re.search(
        r"\b(?:amend|striking|inserting)\w*\b|``|[‘’“”]", raw, re.I
    ):
        return []
    for previous, following in zip(markers, markers[1:], strict=False):
        tail = raw[previous.end() : following.start()].rstrip()
        if re.search(r"(?:\band|\bor|;|:|--)\s*$", tail, re.I):
            return []
    return [m.start() for m in markers]


def build_source_graph(document_id: str, version: str, text: str) -> SourceGraph:
    fingerprint = _hash(
        f"{document_id}\0{version}\0{NORMALIZATION_VERSION}\0{_hash(text)}"
    )
    try:
        structure = parse_federal_structure(text)
        sections = [s for s in structure if s.level == "section"]
    except ExpectedExtractionRejection:
        structure = []
        sections = []
    # Exclude contents only when an explicit contents heading precedes duplicate
    # section labels and their later operative occurrence. Case alone is not proof.
    toc = re.search(r"(?im)^(?:[ \t]*\([a-z]\)[ \t]*)?[ \t]*TABLE OF CONTENTS\b", text)
    if toc:
        operative = [
            s for s in sections if re.match(r"\s*(?:SEC\.|SECTION)\s", s.span.text)
        ]
        after = [
            s.span.start_char for s in operative if s.span.start_char > toc.start()
        ]
        boundary = min(after) if after else toc.start()
        labels = {s.label.casefold().replace("section", "sec.") for s in operative}
        sections = [
            s
            for s in sections
            if not (
                toc.start() < s.span.start_char < boundary
                and s.label.casefold().replace("section", "sec.") in labels
            )
        ]
    starts = [(s.span.start_char, s.label, s.heading or "") for s in sections]
    recognized = bool(starts)
    if not starts:
        starts = [(0, "Full document", "")]
    passages, units = {}, []
    if starts[0][0] > 0:
        prefix = text[: starts[0][0]]
        pid = _hash(f"{fingerprint}:0:{len(prefix)}")
        passages[pid] = Passage(
            pid, 0, len(prefix), prefix, _hash(prefix), "context", ("Preamble",)
        )
    parents = {}
    expanded = []
    for index, (start, label, heading) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(text)
        cuts = _safe_subsection_starts(text[start:end])
        if cuts:
            prefix_end = start + cuts[0]
            prefix_id = _hash(f"{fingerprint}:{start}:{prefix_end}")
            prefix = text[start:prefix_end]
            passages[prefix_id] = Passage(
                prefix_id,
                start,
                prefix_end,
                prefix,
                _hash(prefix),
                "context",
                (label, heading),
            )
            parent_id = _hash(f"section:{fingerprint}:{start}:{end}")
            boundaries = [start] + [start + cut for cut in cuts[1:]] + [end]
            for left, right in zip(boundaries, boundaries[1:], strict=False):
                expanded.append((left, right, label, heading))
                parents[left] = (parent_id, prefix_id)
        else:
            expanded.append((start, end, label, heading))
    for start, end, label, heading in expanded:
        raw = text[start:end]
        inventory_text = raw
        if toc and start <= toc.start() < end and end <= boundary:
            # This section contains the verified contents preceding the first
            # operative section. Headings about fees are not financial rules.
            inventory_text = text[start : toc.start()]
        pid = _hash(f"{fingerprint}:{start}:{end}")
        role = "definition" if "definition" in heading.casefold() else "operative"
        passages[pid] = Passage(
            pid, start, end, raw, _hash(raw), role, (label, heading)
        )
        uid = _hash(f"unit:{pid}")
        units.append(
            SourceUnit(
                uid,
                (pid,),
                parent_id=parents.get(start, (None, None))[0],
                condition_group_id=(
                    uid
                    if re.search(r"\b(?:if|unless|provided that|only if)\b", raw, re.I)
                    else None
                ),
                inventory_kinds=("financial",)
                if FINANCIAL.search(inventory_text)
                else (),
                unresolved_dependencies=(
                    () if recognized else ("unrecognized_structure",)
                ),
            )
        )
    label_ids = {}
    for u in units:
        p = passages[u.own_passage_ids[0]]
        match = re.search(
            r"(?:Sec\.|Section)\s+(\d+[A-Za-z]?)", p.structural_path[0], re.I
        )
        if match:
            label_ids.setdefault(match[1].casefold(), []).append(p.id)
    definitions = tuple(p.id for p in passages.values() if p.role == "definition")
    governing = {u.id: [] for u in units}
    for container in structure:
        if container.level in {
            "section",
            "subsection",
            "paragraph",
            "subparagraph",
            "clause",
        }:
            continue
        children = [
            u
            for u in units
            if container.span.start_char
            <= passages[u.own_passage_ids[0]].start
            < container.span.end_char
        ]
        if not children:
            continue
        start, end = (
            container.span.start_char,
            min(passages[u.own_passage_ids[0]].start for u in children),
        )
        if end <= start:
            continue
        pid = _hash(f"{fingerprint}:{start}:{end}")
        raw = text[start:end]
        passages[pid] = Passage(
            pid,
            start,
            end,
            raw,
            _hash(raw),
            "context",
            (container.label, container.heading or ""),
        )
        for child in children:
            governing[child.id].append(pid)
    preamble_ids = tuple(
        p.id for p in passages.values() if p.structural_path == ("Preamble",)
    )
    resolved = []
    for unit in units:
        context = set(definitions + preamble_ids + tuple(governing[unit.id])) - set(
            unit.own_passage_ids
        )
        own_start = passages[unit.own_passage_ids[0]].start
        if own_start in parents:
            context.add(parents[own_start][1])
        unresolved = list(unit.unresolved_dependencies)
        pending = list(unit.own_passage_ids)
        visited = set()
        while pending:
            pid = pending.pop()
            if pid in visited:
                continue
            visited.add(pid)
            explicit = list(REFERENCE.finditer(passages[pid].text))
            # In inserted/replaced text an unqualified section number can refer
            # to the amended statute, even if this bill has the same number.
            amended_scope = bool(
                re.search(
                    r"\b(?:amend(?:ed|ment|ing)?|striking|inserting|repeal(?:ed)?)\b",
                    passages[pid].text,
                    re.I,
                )
            )
            for bare in BARE_REFERENCE.finditer(passages[pid].text):
                if not passages[pid].text[: bare.start()].strip() and passages[
                    pid
                ].text[bare.end() :].startswith("."):
                    continue
                if not any(m.start() <= bare.start() < m.end() for m in explicit):
                    targets = label_ids.get(bare[1].casefold(), [])
                    if not amended_scope and len(targets) == 1:
                        if targets[0] not in unit.own_passage_ids:
                            context.add(targets[0])
                        pending.extend(targets)
                    else:
                        unresolved.append(bare[0])
            for match in explicit:
                targets = label_ids.get(match[1].casefold(), [])
                if match[2].casefold() == "this act" and len(targets) == 1:
                    if targets[0] not in unit.own_passage_ids:
                        context.add(targets[0])
                    pending.extend(targets)
                else:
                    unresolved.append(match[0])
        resolved.append(
            replace(
                unit,
                context_passage_ids=tuple(
                    sorted(context, key=lambda p: passages[p].start)
                ),
                unresolved_dependencies=tuple(sorted(set(unresolved))),
            )
        )
    return SourceGraph(
        fingerprint,
        passages,
        tuple(resolved),
        {
            "unit_ids": [u.id for u in resolved],
            "inventory_complete": False,
            "omitted_source_ranges": [],
            "normalization_version": NORMALIZATION_VERSION,
        },
        text,
        str(document_id),
        version,
    )


def audit_graph(graph: SourceGraph, text: str) -> list[str]:
    """Re-derive source ownership/context; catch omissions and corrupted snapshots."""
    expected = build_source_graph(graph.document_id, graph.version, text)
    errors = []
    if graph.document_fingerprint != expected.document_fingerprint:
        errors.append("document_identity")
    if graph.passages != expected.passages:
        errors.append("source_ranges")
    if graph.units != expected.units:
        errors.append("unit_coverage_or_context")
    if graph.coverage != expected.coverage:
        errors.append("coverage_manifest")
    return errors
