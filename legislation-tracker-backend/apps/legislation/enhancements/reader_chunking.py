"""Bounded source ownership with exact, citeable legal dependencies."""

import hashlib
import re
from bisect import bisect_left, bisect_right

from django.conf import settings

from .reader_capacity import capacity
from .reader_citations import citation_passages
from .reader_dependencies import CONTEXT_PLANNER_VERSION, DependencyIndex


def owned_spans(text, left, right, target):
    if target < 4:
        raise ValueError("Target must fit a UTF-8 code point")
    while left < right:
        candidate = text[left : min(left + target, right)]
        prefix = candidate.encode()[:target].decode(errors="ignore")
        end = left + len(prefix)
        if end < right:
            for pattern in (r"\n(?=\s*\()", r"\n", r"[.!?]\s+", r"\s+"):
                matches = list(re.finditer(pattern, prefix))
                if matches and matches[-1].end() >= len(prefix) // 2:
                    end = left + matches[-1].end()
                    break
        yield left, end
        left = end


def _citable_owners(sources, owners, first_ref):
    """Give repeated nonblank passages their own exact, unambiguous source.

    Quote matching remains strict. A repeated passage cannot be selected inside
    its larger owner, but the exact same passage is unique when it is the whole
    owner. Split before assigning final references or building dependency edges,
    preserving all structural owners that overlap each new source interval.
    """
    selected, ownership, sizes = [], [], []
    for source, structural in zip(sources, owners, strict=True):
        passages = citation_passages(source)
        split = any(
            passage["quote_id"] is None and passage["text"].strip()
            for passage in passages
        )
        if not split:
            selected.append(source)
            ownership.append(structural)
            sizes.append(len(source["quoted_text"].encode()))
            continue
        start = source["start_char"]
        for passage in passages:
            quoted = passage["text"]
            end = start + len(quoted)
            selected.append(
                {
                    **source,
                    "start_char": start,
                    "end_char": end,
                    "quoted_text": quoted,
                    "text_sha256": hashlib.sha256(quoted.encode()).hexdigest(),
                }
            )
            ownership.append(
                [owner for owner in structural if owner[0] < end and owner[1] > start]
            )
            sizes.append(len(quoted.encode()))
            start = end
    for number, source in enumerate(selected, first_ref):
        source["source_ref"] = f"src_{number:04d}"
    return selected, ownership, sizes


def planned_sources(
    document, text, first_ref, target, xml_sections, *, index_class=DependencyIndex
):
    index = index_class(text, xml_sections)
    limits = capacity()
    input_ceiling = min(
        settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES,
        settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS,
        limits["context_tokens"]
        - min(limits["output_tokens"], settings.LLM_READER_MAX_OUTPUT_TOKENS)
        - 1024,
    )
    sources, owners, source_sizes = [], [], []
    for left, right, unit in index.ownership_units():
        for start, end in owned_spans(text, left, right, target):
            owned = text[start:end]
            size = len(owned.encode())
            # Pack adjacent siblings, including their separating whitespace.
            # Keep reusable parent introductions separate: otherwise a short
            # governing lead-in would drag a whole neighboring chunk into every
            # child's request. Ownership remains a lossless source partition.
            previous_unit = owners[-1][-1][2] if owners else None
            siblings = (
                unit is not None
                and previous_unit is not None
                and (
                    unit == previous_unit
                    or (
                        index.nodes[unit].parent == index.nodes[previous_unit].parent
                        # A chunk shares its citation context. Keep a covered
                        # project separate from the row where a cell span ends.
                        and index.nodes[unit].inherited_cell_ranges
                        == index.nodes[previous_unit].inherited_cell_ranges
                    )
                )
            )
            complete_unit = unit is not None and (left, right) == (
                index.nodes[unit].start,
                index.nodes[unit].end,
            )
            if (
                sources
                and sources[-1]["end_char"] == start
                and source_sizes[-1] + size <= target
                and (not owned.strip() or (siblings and complete_unit))
            ):
                source = sources[-1]
                source["end_char"] = end
                source["quoted_text"] += owned
                source["text_sha256"] = hashlib.sha256(
                    source["quoted_text"].encode()
                ).hexdigest()
                if owned.strip():
                    owners[-1].append((left, right, unit))
                source_sizes[-1] += size
                continue
            owners.append([(left, right, unit)])
            source_sizes.append(size)
            sources.append(
                {
                    "source_ref": f"src_{first_ref + len(sources):04d}",
                    "kind": "document_chunk",
                    "field_path": None,
                    "section_label": document.version_label,
                    "start_char": start,
                    "end_char": end,
                    "quoted_text": owned,
                    "text_sha256": hashlib.sha256(owned.encode()).hexdigest(),
                    "discovery_source": True,
                    "context_planner_version": CONTEXT_PLANNER_VERSION,
                }
            )
    sources, owners, source_sizes = _citable_owners(sources, owners, first_ref)
    return _attach_context(index, sources, owners, source_sizes, input_ceiling)


def _attach_context(index, sources, owners, sizes, input_ceiling, selected_refs=None):
    text = index.text
    starts = [s["start_char"] for s in sources]
    ends = [s["end_char"] for s in sources]
    catalogs = []
    for source in sources:
        cursor, entries = source["start_char"], []
        for passage in citation_passages(source):
            stop = cursor + len(passage["text"])
            entries.append((cursor, stop, passage))
            cursor = stop
        catalogs.append(entries)
    for number, (source, owned_units) in enumerate(zip(sources, owners, strict=True)):
        if selected_refs is not None and source["source_ref"] not in selected_refs:
            continue
        required, unresolved = set(), set()
        for owner in set(owned_units):
            if not text[owner[0] : owner[1]].strip():
                continue
            ranges, missing = index.required(*owner)
            required.update(ranges)
            unresolved.update(missing)
        required = sorted(required)
        referenced = set()
        for left, right in required:
            referenced.update(
                range(bisect_right(ends, left), bisect_left(starts, right))
            )
        referenced.discard(number)
        dependencies = [sources[i] for i in sorted(referenced)]
        quote_ids = {}
        context_bytes = 0
        for i in sorted(referenced):
            selected = {
                p["quote_id"]
                for a, b, p in catalogs[i]
                if any(a < right and b > left for left, right in required)
            }
            quote_ids[sources[i]["source_ref"]] = sorted(
                selected, key=lambda v: v or ""
            )
            context_bytes += sum(
                len(p["text"].encode())
                for _, _, p in catalogs[i]
                if p["quote_id"] in selected
            )
        total = sizes[number] + context_bytes
        complete_sections = []
        for _, _, unit in owned_units:
            section = index.scope(unit, "section") if unit is not None else None
            if section is not None:
                node = index.nodes[section]
                complete_sections.append(
                    any(a <= node.start and b >= node.end for a, b in required)
                )
        source.update(
            context_source_refs=[s["source_ref"] for s in dependencies],
            context_quote_ids=quote_ids,
            dependencies=[
                {
                    "start": s["start_char"],
                    "end": s["end_char"],
                    "sha256": s["text_sha256"],
                }
                for s in dependencies
            ],
            # The final serialized envelope is checked separately, including
            # citation schemas and output allowance. Never remove dependencies
            # merely to make this cheaper raw-text check pass.
            omitted_dependency_ranges=(list(required) if total > input_ceiling else []),
            unresolved_dependencies=sorted(unresolved),
            section_context_complete=bool(complete_sections)
            and all(complete_sections)
            and not unresolved,
        )
    return sources
