"""Project official Congress XML sections onto existing, immutable citation text."""
from hashlib import sha256
from xml.parsers import expat

from botocore.exceptions import BotoCoreError, ClientError
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from django.conf import settings
from django.core.files.storage import default_storage

from apps.ingestion.document_download import (
    _BoundedTextLines, _direct_xml_child_text, _render_congress_xml_element,
    _XML_STRUCTURAL_TAGS, _xml_tag, extract_text_from_xml_or_html, DocumentTextLimitExceeded,
)


def xml_boundaries(raw, text):
    root = ElementTree.fromstring(raw)
    def outer_bodies(node):
        tag = _xml_tag(node)
        if tag in {"toc", "table-of-contents", "quoted-block", "quoted-text"}:
            return
        if tag in {"legis-body", "engrossed-amendment-body", "amendment-body"}:
            yield node
            return
        for child in node:
            yield from outer_bodies(child)

    bodies = list(outer_bodies(root))
    if not bodies:
        return ()  # Other XML vocabularies retain the text parser.
    elements = []

    def collect(e):
        tag = _xml_tag(e)
        if tag in {"toc", "table-of-contents", "quoted-block", "quoted-text"}:
            return
        if tag == "section":
            elements.append(e)
            return  # Nested quoted and amended law belongs to its parent.
        for child in e:
            collect(child)

    for body in bodies:
        collect(body)
    if not elements:
        return ()
    spans, rendered = {}, None
    if any(_xml_tag(body) == "legis-body" for body in bodies):
        lines = _BoundedTextLines(len(text) + 1)
        wanted = set(elements)

        def observe(element, start, end):
            if element in wanted:
                spans[element] = (start, end)

        body = next(b for b in bodies if _xml_tag(b) == "legis-body")
        try:
            for child in body:
                if _xml_tag(child) in _XML_STRUCTURAL_TAGS:
                    _render_congress_xml_element(child, lines, observe)
            rendered = lines.render()
        except DocumentTextLimitExceeded:
            pass  # Try the historical flat renderer; require exact equality.
    if rendered != text or len(spans) != len(elements):
        # Historical amendment text was flattened by ingestion. Inject boundary
        # markers at parser-reported XML byte offsets, never by matching titles.
        # The verified safe parse above rejects entity declarations before expat.
        order = iter(root.iter())
        wanted = {e: i for i, e in enumerate(elements)}
        stack, events = [], []
        parser = expat.ParserCreate()
        marker = "XMLBOUNDARY" + sha256(raw).hexdigest() + ":"
        if marker in text:
            raise ValueError("xml_boundary_collision")

        def event(index, edge):
            token = f"{marker}{index}:{edge}"
            events.append((parser.CurrentByteIndex, ("\n" + token + "\n").encode()))

        def start(tag, attrs):
            index = wanted.get(next(order))
            stack.append(index)
            if index is not None:
                event(index, "start")

        def end(tag):
            index = stack.pop()
            if index is not None:
                event(index, "end")

        parser.StartElementHandler, parser.EndElementHandler = start, end
        parser.Parse(raw, True)
        pieces, pos = [], 0
        for offset, token in events:
            pieces.extend((raw[pos:offset], token))
            pos = offset
        marked = b"".join([*pieces, raw[pos:]])
        # Invoke exactly the same flat markup normalization used at ingestion.
        annotated = extract_text_from_xml_or_html(marked, "text/html",
            max_text_chars=len(text) + sum(len(t) for _, t in events) + 1)
        clean, offsets, length = [], {}, 0
        for line in annotated.split("\n"):
            if line.startswith(marker):
                index, edge = line[len(marker):].split(":")
                offsets[int(index), edge] = length + int(edge == "start" and bool(clean))
            else:
                length += len(line) + int(bool(clean))
                clean.append(line)
        rendered = "\n".join(clean)
        spans = {e: (offsets[i, "start"], offsets[i, "end"]) for e, i in wanted.items()}

    if rendered != text or len(spans) != len(elements):
        raise ValueError("xml_text_mismatch")
    rows, previous, seen = [], 0, set()
    for i, e in enumerate(elements):
        left, right = spans[e]
        identity = e.get("id") or f"ordinal:{i}"
        if identity in seen or not previous <= left < right <= len(text):
            raise ValueError("xml_section_identity")
        seen.add(identity)
        label = _direct_xml_child_text(e, "enum").rstrip(".")
        rows.append((identity, left, right, f"Sec. {label}" if label else "Unnumbered section",
                     _direct_xml_child_text(e, "header")))
        previous = right
    return tuple(rows)


def stored_xml_sections(document, text):
    key = getattr(document, "object_storage_key", "") or ""
    if not key or not (key.lower().endswith(".xml") or "xml" in (document.content_type or "").lower()):
        return ()
    from .source_packet import PreflightUnavailable
    try:
        limit = settings.DOCUMENT_DOWNLOAD_MAX_BYTES
        if limit <= 0 or (document.file_size_bytes or 0) > limit:
            raise ValueError("xml_byte_limit")
        with default_storage.open(key, "rb") as source:
            raw = source.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("xml_byte_limit")
        if document.content_hash and sha256(raw).hexdigest() != document.content_hash:
            raise ValueError("xml_hash_mismatch")
        return xml_boundaries(raw, text)
    except (ValueError, KeyError, ElementTree.ParseError, DefusedXmlException, OSError,
            BotoCoreError, ClientError) as exc:
        raise PreflightUnavailable("Stored XML could not be aligned with the bill text",
                                   reason="source_unavailable") from exc
