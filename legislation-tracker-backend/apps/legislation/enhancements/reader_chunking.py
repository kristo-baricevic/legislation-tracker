"""Experimental source ownership targets measured with a conservative byte estimate."""

import hashlib
import re
from functools import lru_cache

from django.conf import settings

from .reader_capacity import capacity
from .source_graph import build_source_graph


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


def planned_sources(document, text, first_ref, target, xml_sections):
    graph = build_source_graph(
        str(document.pk), document.version_label, text, xml_sections=xml_sections
    )

    @lru_cache(maxsize=4096)
    def dependency(a, b):
        data = text[a:b].encode()
        return {
            "start": a,
            "end": b,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    limits = capacity()
    input_ceiling = min(
        settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES,
        settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS,
        limits["context_tokens"] - 1024,
    )
    by_span = {}
    for unit in graph.units:
        for pid in unit.own_passage_ids:
            passage = graph.passages[pid]
            by_span[passage.start, passage.end] = unit

    # Preamble and inter-section gaps have their own ownership too.
    boundaries = sorted(
        {0, len(text), *(offset for span in by_span for offset in span)}
    )
    sources = []
    for left, right in zip(boundaries, boundaries[1:]):
        unit = by_span.get((left, right))
        for start, end in owned_spans(text, left, right, target):
            owned = text[start:end]
            context = []
            if (start, end) != (left, right):
                context.extend([(left, start), (end, right)])
            if unit:
                context.extend(
                    (graph.passages[pid].start, graph.passages[pid].end)
                    for pid in unit.context_passage_ids
                )
            # Merge overlaps before counting context; preserve independent source offsets.
            fragments = [
                (x, y)
                for a, b in context
                for x, y in ((a, min(start, b)), (max(end, a), b))
                if x < y
            ]
            merged = []
            for x, y in sorted(fragments):
                if merged and x <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], y))
                else:
                    merged.append((x, y))
            remaining = max(0, input_ceiling - len(owned.encode()))
            dependencies, included, missing = [], [], []
            for a, b in merged:
                item = dependency(a, b)
                dependencies.append(item)
                if item["bytes"] <= remaining:
                    included.append(text[a:b])
                    remaining -= item["bytes"]
                else:
                    missing.append([a, b])
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
                    "dependencies": dependencies,
                    "omitted_dependency_ranges": missing,
                    "unresolved_dependencies": (
                        list(unit.unresolved_dependencies) if unit else []
                    ),
                    "section_context": "\n".join(included),
                    "section_context_complete": bool(
                        unit and not unit.unresolved_dependencies and not missing
                    ),
                }
            )
    return sources
