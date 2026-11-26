"""Rebuild pre-v6 dependency metadata only when checking an ambiguous old charge.

Older reservations hashed planning-only fields, even though the provider never
received them. Reconstruct those fields over the original ownership intervals.
This inventory is used only for matching a reservation, never for generation.
"""

import re
from bisect import bisect_right
from functools import cached_property, partial

from django.conf import settings
from django.db.models import Q

from apps.ingestion.document_download import _xml_tag

from .providers.base import ProviderError
from .reader_capacity import capacity
from .reader_chunking import _attach_context, planned_sources
from .reader_dependencies import QUALIFICATION, DependencyIndex
from .xml_sections import stored_xml_sections


def _historical_table_row_levels(root):
    """Recreate the 2327c54 table metadata used in pre-v15 charge keys."""
    levels = {}

    def walk(element, columns=None, figure_columns=frozenset(), in_header=False):
        tag = _xml_tag(element)
        if tag in {"table", "tgroup"}:
            inherited = columns or {}
            columns = dict(inherited)
            figures = set(figure_columns)
            for ordinal, spec in enumerate(
                child for child in element if _xml_tag(child) == "colspec"
            ):
                name = spec.get("colname")
                position = spec.get("colnum", "")
                position = int(position) if position.isdigit() else ordinal
                if name:
                    columns[name] = position
                    if spec.get("coldef", "").startswith("fig"):
                        figures.add(position)
            figure_columns = frozenset(figures)
        if tag in {"thead", "tfoot"}:
            in_header = True
        if tag == "row":
            entries = [child for child in element if _xml_tag(child) == "entry"]
            nonempty = [entry for entry in entries if "".join(entry.itertext()).strip()]
            if in_header or len(nonempty) != 1:
                return
            content = " ".join("".join(nonempty[0].itertext()).split())
            if not any(character.isalpha() for character in content):
                return

            def position(name, fallback):
                if name in (columns or {}):
                    return columns[name]
                number = re.fullmatch(r"(?:col|column)(\d+)", name or "", re.I)
                return int(number[1]) if number else fallback

            cursor = 0
            for entry in entries:
                start = position(entry.get("namest") or entry.get("colname"), cursor)
                if entry is nonempty[0]:
                    if start not in figure_columns:
                        levels[element] = start
                    return
                cursor = position(entry.get("nameend"), start) + 1
            return
        for child in element:
            walk(child, columns, figure_columns, in_header)

    walk(root)
    return levels


class _PreviousIndex(DependencyIndex):
    table_scopes = {"table"}
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


class HistoricalReaderSources:
    def __init__(self, preflight):
        self.preflight = preflight

    @cached_property
    def saved_plans(self):
        from ..models import BillEnhancement

        manifest = self.preflight.source_manifest
        if not manifest.get("document_id") or not manifest.get("document_content_hash"):
            return None
        # Surviving plans contain the exact source metadata under their
        # original limits, including older parsers' interpretation of the XML.
        bill_id = self.preflight.request_envelope.get("bill", {}).get("id")
        plans = BillEnhancement.objects.filter(
            provider=self.preflight.provider,
            output_schema_version="1.4",
            source_manifest_json__document_content_hash=manifest[
                "document_content_hash"
            ],
        )
        if bill_id:
            # A re-import may assign the same rendered bill a new document ID.
            # The envelope and selected passages still have to match exactly.
            plans = plans.filter(bill_id=bill_id)
        else:
            plans = plans.filter(
                source_manifest_json__document_id=manifest["document_id"]
            )
        return (
            plans.filter(
                Q(
                    source_manifest_json__execution_settings__reader_execution_version__lt=15
                )
                | Q(
                    source_manifest_json__execution_settings__reader_execution_version__isnull=True
                )
            )
            .order_by("pk")
            .values_list("source_snapshot_json", flat=True)
        )

    @cached_property
    def rebuilt(self):
        from ..models import BillDocument
        from .reader_batches import build_reader_preflight
        from .source_packet import PreflightUnavailable, _text_hash

        manifest = self.preflight.source_manifest
        doc = BillDocument.objects.filter(pk=manifest.get("document_id")).first()
        text = (doc.extracted_text or doc.raw_text or "") if doc else ""
        if doc and _text_hash(text) == manifest.get("document_content_hash"):
            # The manifest identifies rendered text. The storage reader checks
            # the *file* digest independently and aligns XML to that text.
            pinned_xml = manifest.get("document_xml_sha256")
            try:
                sections = stored_xml_sections(
                    doc, text, row_levels=_historical_table_row_levels
                )
                if (
                    manifest.get("source_kind") == "xml_full_review" and not sections
                ) or (
                    pinned_xml and getattr(sections, "xml_sha256", None) != pinned_xml
                ):
                    raise ProviderError("source_unavailable")
                plan = build_reader_preflight(
                    doc,
                    xml_sections=sections,
                    reuse_publication=False,
                    source_planner=partial(planned_sources, index_class=_PreviousIndex),
                )
            except PreflightUnavailable as error:
                # No usable original plan means no permission to dispatch.
                raise ProviderError(error.reason) from error
            return {s["source_ref"]: s for s in plan.source_snapshot}
        if manifest.get("source_kind") == "xml_full_review":
            raise ProviderError("source_unavailable")
        # Older in-memory/text-only plans have no immutable XML to reopen.
        return _rebuild_text_context(self.preflight)


def _rebuild_text_context(preflight):
    scans = [
        s.copy() for s in preflight.source_snapshot if s.get("context_planner_version")
    ]
    if not scans:
        return {}
    text = "".join(s["quoted_text"] for s in scans)
    index = _PreviousIndex(text, ())
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
    rows = _attach_context(
        index,
        scans,
        owners,
        [len(s["quoted_text"].encode()) for s in scans],
        ceiling,
    )
    return {s["source_ref"]: s for s in rows}


def _project(inventory, page_sources, *, summary):
    from .reader_citations import citation_passages
    from .reader_summary import summary_source

    rows = []
    for current in page_sources:
        prior = inventory.get(current["source_ref"])
        if prior is None:
            return None
        ids = current["allowed_quote_ids"]
        if prior.get("quoted_text") != current.get("quoted_text"):
            # A differently sized owner can still supply exactly the same
            # selected passages. Source numbers alone do not identify evidence.
            def quotes(source, ids):
                return {
                    p["quote_id"]: p["text"]
                    for p in citation_passages(source)
                    if p["quote_id"] in ids
                }

            before, now = quotes(prior, ids), quotes(current, ids)
            if not ids or set(before) != set(ids) or before != now:
                return None
        row = summary_source(prior) if summary else prior
        rows.append({**row, "allowed_quote_ids": ids})
    return rows


def historical_page_sources(preflight, page_sources, mode, *, summary=False):
    history = preflight.historical_reader_sources
    if mode == "saved":
        plans = history.saved_plans
        if plans is None:
            return
        refs = {s["source_ref"] for s in page_sources}
        inventories = (
            {s["source_ref"]: s for s in rows if s["source_ref"] in refs}
            for rows in plans.iterator(chunk_size=1)
            if rows
        )
    else:
        inventories = [history.rebuilt]
    for inventory in inventories:
        projected = _project(inventory, page_sources, summary=summary)
        if projected is not None:
            yield projected
