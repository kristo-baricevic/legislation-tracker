"""Project official Congress XML sections onto existing, immutable citation text."""

import re
from dataclasses import dataclass
from hashlib import sha256
from xml.etree.ElementTree import Element
from xml.parsers import expat

from botocore.exceptions import BotoCoreError, ClientError
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from django.conf import settings
from django.core.files.storage import default_storage

from apps.ingestion.document_download import (
    _XML_STRUCTURAL_TAGS,
    DocumentTextLimitExceeded,
    _BoundedTextLines,
    _direct_xml_child_text,
    _render_congress_xml_element,
    _xml_tag,
    extract_text_from_xml_or_html,
)

XML_SECTION_VERSION = 4  # Bump when section alignment or rendering changes.

_BODIES = {"legis-body", "engrossed-amendment-body", "amendment-body"}
_QUOTED = {"quoted-block", "quoted-text"}
_CONTENTS = {"toc", "table-of-contents"}
_TABLE = {"table", "tgroup", "thead", "tbody", "row"}
_PROVISIONS = (
    _XML_STRUCTURAL_TAGS
    | _BODIES
    | _QUOTED
    | _CONTENTS
    | _TABLE
    | {"amendment", "amendment-block"}
)


@dataclass(frozen=True)
class XmlProvision:
    """An XML-owned range in the already stored, immutable citation text.

    ``parent`` indexes the same ``XmlSections.provisions`` tuple. ``section_id``
    identifies the outer operative section even inside quoted old/new law.
    Quoted wrappers and their descendants have positive ``quoted_depth``.
    References belong to this node's own content, not all its descendants.
    """

    start: int
    end: int
    tag: str
    label: str
    heading: str
    parent: int | None
    section_id: str | None
    quoted_depth: int
    identity: str = ""
    references: tuple[str, ...] = ()
    table_label_level: int | None = None
    external_references: tuple[tuple[int, int, str], ...] = ()
    inherited_cell_ranges: tuple[tuple[int, int], ...] = ()


class XmlSections(tuple):
    """Keep the section inventory's five-tuples and expose verified hierarchy."""

    def __new__(cls, sections=(), provisions=()):
        result = super().__new__(cls, sections)
        result.provisions = tuple(provisions)
        return result


def _table_layout(root):
    """Use CALS columns to identify nested table labels, never capitalization.

    A service/account label in an earlier column governs later geographic
    labels. A new label at the same column replaces that level and its children.
    Header rows and amount-only rows are not category labels.
    """
    levels, inherited = {}, {}

    def walk(
        element, columns=None, figure_columns=frozenset(), in_header=False, spans=None
    ):
        tag = _xml_tag(element)
        if tag in {"table", "tgroup"}:
            columns = dict(columns or {})
            figures = set(figure_columns)
            specs = [child for child in element if _xml_tag(child) == "colspec"]
            # OASIS colnum starts at one. Congress also publishes zero-based
            # tgroups. Use zero-based offsets internally in both dialects.
            origin = 0 if any(spec.get("colnum") == "0" for spec in specs) else 1
            next_column = 0
            for spec in specs:
                name = spec.get("colname")
                number = spec.get("colnum", "")
                position = int(number) - origin if number.isdecimal() else next_column
                next_column = position + 1
                if name:
                    columns[name] = position
                if spec.get("coldef", "").startswith("fig"):
                    figures.add(position)
            figure_columns = frozenset(figures)
        if tag in {"table", "tgroup", "thead", "tbody", "tfoot"}:
            spans = {}
        if tag in {"thead", "tfoot"}:
            in_header = True
        if tag == "row":
            entries = [child for child in element if _xml_tag(child) == "entry"]
            if in_header or spans is None:
                return

            def position(name, fallback):
                if name in (columns or {}):
                    return columns[name]
                number = re.fullmatch(r"(?:col|column)(\d+)", name or "", re.I)
                return max(0, int(number[1]) - 1) if number else fallback

            cursor = 0
            # A cell can span both rows and columns. Track occupied intervals
            # without allocating one item per declared row or column.
            occupied = sorted(spans)
            for interval in occupied:
                remaining, cell = spans[interval]
                if cell is not None:
                    inherited.setdefault(element, []).append(cell)
                if remaining > 1:
                    spans[interval] = remaining - 1, cell
                else:
                    del spans[interval]
            filled = []
            for entry in entries:
                for left, right in occupied:
                    if left <= cursor <= right:
                        cursor = right + 1
                namest = entry.get("namest")
                start = position(namest or entry.get("colname"), cursor)
                end = position(entry.get("nameend"), start) if namest else start
                more = entry.get("morerows", "")
                content = "".join(entry.itertext()).strip()
                row_span = int(more) if more.isdecimal() else 0
                if row_span:
                    spans[start, end] = row_span, entry if content else None
                cursor = end + 1
                if content:
                    filled.append((start, content, row_span))
            if len(filled) == 1 and element not in inherited and not filled[0][2]:
                start, content, _ = filled[0]
                if start not in figure_columns and any(c.isalpha() for c in content):
                    levels[element] = start
            return
        for child in element:
            walk(child, columns, figure_columns, in_header, spans)

    walk(root)
    return levels, inherited


def _strip_markers(annotated, marker, *, normalize=False):
    """Remove generated markers while recording their exact clean offsets."""
    pattern = re.compile(re.escape(marker) + r"(\d+):(start|end)")
    clean, offsets, length = [], {}, 0
    for line in annotated.split("\n"):
        matches = list(pattern.finditer(line))
        value = pattern.sub("", line)
        if normalize:
            value = re.sub(r"[ \t]+", " ", value).strip()
        if not value:
            for match in matches:
                offsets[int(match[1]), match[2]] = length + int(
                    match[2] == "start" and bool(clean)
                )
            continue
        base = length + int(bool(clean))
        for match in matches:
            prefix = pattern.sub("", line[: match.start()])
            if normalize:
                prefix = re.sub(r"[ \t]+", " ", prefix).lstrip()
            offsets[int(match[1]), match[2]] = base + min(len(prefix), len(value))
        clean.append(value)
        length = base + len(value)
    rendered = "\n".join(clean)
    for identity, offset in offsets.items():
        if identity[1] == "start":
            while offset < len(rendered) and rendered[offset].isspace():
                offset += 1
        else:
            while offset and rendered[offset - 1].isspace():
                offset -= 1
        offsets[identity] = offset
    return rendered, offsets


def _rendered_spans(bodies, nodes, text, marker):
    """Use ingestion's renderer and observer; never infer hierarchy from text."""
    body = next((b for b in bodies if _xml_tag(b) == "legis-body"), None)
    if body is None:
        return None, {}
    wanted = {node: index for index, (node, *_) in enumerate(nodes)}
    spans, changes = {}, []
    # The renderer observes structural nodes. Quoted wrappers are emitted by
    # their parent, and inline quoted text can be normalized into a text field.
    # Temporary markers make those boundaries observable without changing the
    # persisted rendering. All mutations are restored before the flat fallback.
    for node, *_ in nodes:
        tag = _xml_tag(node)
        index = wanted[node]
        if tag == "quoted-block":
            first = Element("text")
            last = Element("text")
            first.text, last.text = f"{marker}{index}:start", f"{marker}{index}:end"
            node.insert(0, first)
            node.append(last)
            changes.append((node, first, last))
        elif tag in _QUOTED | _CONTENTS | _TABLE | {"external-xref", "entry"}:
            changes.append((node, "text", node.text))
            node.text = f"{marker}{index}:start" + (node.text or "")
            tail_node, attribute = (node[-1], "tail") if len(node) else (node, "text")
            previous = getattr(tail_node, attribute)
            changes.append((tail_node, attribute, previous))
            setattr(tail_node, attribute, (previous or "") + f"{marker}{index}:end")
    lines = _BoundedTextLines(len(text) + len(nodes) * (2 * len(marker) + 60) + 1)

    def observe(element, start, end):
        if element in wanted:
            spans[wanted[element]] = (start, end)

    try:
        for child in body:
            if _xml_tag(child) in _XML_STRUCTURAL_TAGS:
                _render_congress_xml_element(child, lines, observe)
        rendered = lines.render()
    except DocumentTextLimitExceeded:
        return None, {}
    finally:
        for node, attribute, previous in reversed(changes):
            if isinstance(attribute, str):
                setattr(node, attribute, previous)
            else:
                node.remove(attribute)
                node.remove(previous)
    if body in wanted:
        spans[wanted[body]] = (0, len(rendered))
    # Insert observer boundaries into the same stream as inline boundaries so
    # their offsets remain correct when temporary marker lines are removed.
    events = []
    for index, (start, end) in spans.items():
        events.extend(((start, index, "start"), (end, index, "end")))
    pieces, cursor = [], 0
    for position, index, edge in sorted(events):
        pieces.extend((rendered[cursor:position], f"{marker}{index}:{edge}"))
        cursor = position
    pieces.append(rendered[cursor:])
    clean, offsets = _strip_markers("".join(pieces), marker, normalize=True)
    return clean, offsets


def _flat_spans(raw, root, nodes, text, marker):
    # The safe parse has rejected entity declarations before expat sees input.
    order = iter(root.iter())
    wanted = {node: i for i, (node, *_) in enumerate(nodes)}
    stack, events = [], []
    parser = expat.ParserCreate()

    def event(index, edge):
        token = f"{marker}{index}:{edge}".encode()
        events.append((parser.CurrentByteIndex, token))

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
    annotated = extract_text_from_xml_or_html(
        marked,
        "text/html",
        max_text_chars=len(text) + sum(len(t) + 2 for _, t in events) + 1,
    )
    return _strip_markers(annotated, marker, normalize=True)


def xml_boundaries(raw, text, *, row_levels=None):
    root = ElementTree.fromstring(raw)
    if row_levels is None:
        table_row_levels, inherited_cells = _table_layout(root)
    else:
        # Historical charge reconstruction uses the original row-label parser.
        table_row_levels, inherited_cells = row_levels(root), {}


    def outer_bodies(node):
        tag = _xml_tag(node)
        if tag in _CONTENTS | _QUOTED:
            return
        if tag in _BODIES:
            yield node
            return
        for child in node:
            yield from outer_bodies(child)

    bodies = list(outer_bodies(root))
    if not bodies:
        return XmlSections()  # Other vocabularies retain the text parser.
    elements = []

    def collect_sections(element):
        tag = _xml_tag(element)
        if tag in _CONTENTS | _QUOTED:
            return
        if tag == "section":
            children = list(element)
            if (
                children
                and not (element.text or "").strip()
                and all(
                    _xml_tag(child) in _CONTENTS and not (child.tail or "").strip()
                    for child in children
                )
            ):
                return
            elements.append(element)
            return  # Quoted law belongs to the containing operative section.
        for child in element:
            collect_sections(child)

    for body in bodies:
        collect_sections(body)
    if not elements:
        return XmlSections()
    section_ids = {
        element: element.get("id") or f"ordinal:{index}"
        for index, element in enumerate(elements)
    }
    nodes = []

    def collect_nodes(element, parent=None, section_id=None, quoted_depth=0):
        tag = _xml_tag(element)
        quoted_depth += int(tag in _QUOTED)
        section_id = section_ids.get(element, section_id)
        if tag == "external-xref":
            nodes.append((element, parent, section_id, quoted_depth, []))
            return
        if tag in _PROVISIONS:
            index = len(nodes)
            nodes.append((element, parent, section_id, quoted_depth, []))
            parent = index
        if tag == "internal-xref" and parent is not None:
            target = element.get("idref")
            if target:
                nodes[parent][4].append(target)
        if tag in _CONTENTS | {"row"}:
            if parent is not None:
                nodes[parent][4].extend(
                    child.get("idref")
                    for child in element.iter()
                    if _xml_tag(child) == "internal-xref" and child.get("idref")
                )
                for child in element.iter():
                    if _xml_tag(child) == "external-xref":
                        nodes.append((child, parent, section_id, quoted_depth, []))
            return
        for child in element:
            collect_nodes(child, parent, section_id, quoted_depth)

    for body in bodies:
        collect_nodes(body)
    # Observe only carried cells, without turning them into ownership units or
    # changing the identities of the provisions used by historical requests.
    cell_indices = {}
    for row, *_ in nodes.copy():
        for cell in inherited_cells.get(row, ()):
            if cell not in cell_indices:
                cell_indices[cell] = len(nodes)
                nodes.append((cell, None, None, 0, []))
    marker = "XMLBOUNDARY" + sha256(raw).hexdigest() + ":"
    if marker in text:
        raise ValueError("xml_boundary_collision")
    rendered, offsets = _rendered_spans(bodies, nodes, text, marker)
    if rendered != text:
        rendered, offsets = _flat_spans(raw, root, nodes, text, marker)
    if rendered != text:
        raise ValueError("xml_text_mismatch")
    cell_ranges = {}
    for cell, index in cell_indices.items():
        left, right = offsets.get((index, "start")), offsets.get((index, "end"))
        if left is None or right is None or not 0 <= left < right <= len(text):
            raise ValueError("xml_spanning_cell_unavailable")
        cell_ranges[cell] = (left, right)
    external = {}
    for index, (element, parent, *_rest) in enumerate(nodes):
        if _xml_tag(element) == "external-xref" and (index, "start") in offsets:
            left, right = offsets[index, "start"], offsets[index, "end"]
            if right > left:
                citation = element.get("parsable-cite") or " ".join(
                    text[left:right].split()
                )
                external.setdefault(parent, []).append((left, right, citation))
    by_element = {node: index for index, (node, *_) in enumerate(nodes)}
    rows, previous, seen = [], 0, set()
    for element in elements:
        index = by_element[element]
        left, right = offsets[index, "start"], offsets[index, "end"]
        identity = section_ids[element]
        if identity in seen or not previous <= left < right <= len(text):
            raise ValueError("xml_section_identity")
        seen.add(identity)
        label = _direct_xml_child_text(element, "enum").rstrip(".")
        rows.append(
            (
                identity,
                left,
                right,
                f"Sec. {label}" if label else "Unnumbered section",
                _direct_xml_child_text(element, "header"),
            )
        )
        previous = right
    provisions, indices = [], {}
    for index, (element, parent, section_id, quoted_depth, references) in enumerate(
        nodes
    ):
        if _xml_tag(element) in {"external-xref", "entry"}:
            continue
        left, right = offsets.get((index, "start")), offsets.get((index, "end"))
        # Empty/unsupported nodes have no immutable stored text to invent.
        if left is None or right is None or left >= right:
            continue
        if not 0 <= left < right <= len(text):
            raise ValueError("xml_provision_range")
        while parent is not None and parent not in indices:
            parent = nodes[parent][1]
        parent_index = indices.get(parent)
        if parent_index is not None:
            ancestor = provisions[parent_index]
            if not ancestor.start <= left < right <= ancestor.end:
                raise ValueError("xml_provision_containment")
        indices[index] = len(provisions)
        provisions.append(
            XmlProvision(
                start=left,
                end=right,
                tag=_xml_tag(element),
                label=_direct_xml_child_text(element, "enum").rstrip("."),
                heading=_direct_xml_child_text(element, "header"),
                parent=parent_index,
                section_id=section_id,
                quoted_depth=quoted_depth,
                identity=element.get("id") or f"provision:{index}",
                references=tuple(dict.fromkeys(references)),
                table_label_level=table_row_levels.get(element),
                external_references=tuple(external.get(index, ())),
                inherited_cell_ranges=tuple(
                    cell_ranges[cell] for cell in inherited_cells.get(element, ())
                ),
            )
        )
    return XmlSections(rows, provisions)


def read_stored_xml(document):
    key = getattr(document, "object_storage_key", "") or ""
    if not key or not (
        key.lower().endswith(".xml") or "xml" in (document.content_type or "").lower()
    ):
        return None, None
    from .source_packet import PreflightUnavailable

    try:
        limit = settings.DOCUMENT_DOWNLOAD_MAX_BYTES
        if limit <= 0 or (document.file_size_bytes or 0) > limit:
            raise ValueError("xml_byte_limit")
        with default_storage.open(key, "rb") as source:
            raw = source.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("xml_byte_limit")
        digest = sha256(raw).hexdigest()
        if document.content_hash and digest != document.content_hash:
            raise ValueError("xml_hash_mismatch")
        return raw, digest
    except (ValueError, KeyError, OSError, BotoCoreError, ClientError) as exc:
        raise PreflightUnavailable(
            "Stored XML could not be read or verified", reason="source_unavailable"
        ) from exc


def aligned_xml_sections(raw, text, *, row_levels=None):
    if raw is None:
        return ()
    from .source_packet import PreflightUnavailable

    try:
        return xml_boundaries(raw, text, row_levels=row_levels)
    except (ValueError, KeyError, ElementTree.ParseError, DefusedXmlException) as exc:
        raise PreflightUnavailable(
            "Stored XML could not be aligned with the bill text",
            reason="source_unavailable",
        ) from exc


def stored_xml_sections(document, text, *, row_levels=None):
    raw, digest = read_stored_xml(document)
    if raw is None:
        return ()
    if text is None:
        text = document.extracted_text or document.raw_text or ""
    sections = aligned_xml_sections(raw, text, row_levels=row_levels)
    sections.xml_sha256 = digest
    return sections
