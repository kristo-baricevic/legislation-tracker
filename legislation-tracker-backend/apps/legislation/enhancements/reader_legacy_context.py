"""Rebuild pre-v6 dependency metadata only when checking an ambiguous old charge.

Older reservations hashed planning-only fields, even though the provider never
received them. Reconstruct those fields over the original ownership intervals.
This inventory is used only for matching a reservation, never for generation.
"""

from bisect import bisect_right

from django.conf import settings

from .reader_capacity import capacity
from .reader_chunking import _attach_context
from .reader_dependencies import QUALIFICATION, DependencyIndex
from .xml_sections import stored_xml_sections


class _PreviousIndex(DependencyIndex):
    inherited_definition_levels = (
        "Act|division|title|subtitle|chapter|section|subsection"
    )
    definition_levels = inherited_definition_levels + "|paragraph"
    scope_candidate = QUALIFICATION
    use_external_markup = False
    resolve_missing_scope = False

    def _retain_incoming_reference(self, origin, target):
        if (
            origin != target
            and self.quote_scope(origin) == self.quote_scope(target)
            and self.scope(origin, "section") == self.scope(target, "section")
        ):
            self.links[target].add(origin)


def historical_page_sources(preflight, page_sources):
    from ..models import BillDocument

    scans = [
        s.copy() for s in preflight.source_snapshot if s.get("context_planner_version")
    ]
    if not scans:
        return page_sources
    text = "".join(s["quoted_text"] for s in scans)
    manifest = preflight.source_manifest
    document = BillDocument.objects.filter(
        pk=manifest.get("document_id"),
        content_hash=manifest.get("document_content_hash"),
    ).first()
    sections = stored_xml_sections(document, text) if document else ()
    index = _PreviousIndex(text, sections)
    ends = [s["end_char"] for s in scans]
    owners = [[] for _ in scans]
    for left, right, unit in index.ownership_units():
        pos = bisect_right(ends, left)
        while pos < len(scans) and scans[pos]["start_char"] < right:
            owners[pos].append((left, right, unit))
            pos += 1
    limits = capacity()
    ceiling = min(
        settings.LLM_ENHANCEMENT_MAX_REQUEST_BYTES,
        settings.LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS,
        limits["context_tokens"]
        - min(limits["output_tokens"], settings.LLM_READER_MAX_OUTPUT_TOKENS)
        - 1024,
    )
    selected = {s["source_ref"] for s in page_sources}
    rows = _attach_context(
        index,
        scans,
        owners,
        [len(s["quoted_text"].encode()) for s in scans],
        ceiling,
        selected,
    )
    historic = {s["source_ref"]: s for s in rows}
    return [{**s, **historic.get(s["source_ref"], {})} for s in page_sources]
