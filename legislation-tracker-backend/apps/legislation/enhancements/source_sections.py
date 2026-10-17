"""Exact-offset section groups and explicit coverage for AI source packets."""

import hashlib
import re

from apps.legislation.extraction.federal_structure import SECTION_RE


def document_groups(text, version_label):
    from .source_packet import MAX_SOURCE_TEXT_LENGTH

    markers = list(SECTION_RE.finditer(text))
    # GovInfo prints operative headings in uppercase and contents entries as
    # "Sec.". Never treat those contents entries as the referenced rule itself.
    uppercase = [m for m in markers if m.group("kind").isupper()]
    if uppercase:
        markers = uppercase
    starts = [
        (m.start(), f"Sec. {m.group('label')}", m.group("label")) for m in markers
    ]
    if not starts or text[: starts[0][0]].strip():
        starts.insert(0, (0, "Preamble" if starts else "Full document", None))
    groups = []
    for index, (start, label, number) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(text)
        sources = []
        cursor = start
        while cursor < end:
            stop = min(cursor + MAX_SOURCE_TEXT_LENGTH, end)
            if stop < end:
                boundary = max(
                    text.rfind("\n", cursor, stop), text.rfind(". ", cursor, stop)
                )
                if boundary > cursor + MAX_SOURCE_TEXT_LENGTH // 2:
                    stop = boundary + 1
            chunk = text[cursor:stop].strip()
            if chunk:
                offset = text.find(chunk, cursor, stop)
                sources.append(
                    {
                        "kind": "document_chunk",
                        "field_path": None,
                        "section_label": version_label,
                        "quoted_text": chunk,
                        "start_char": offset,
                        "end_char": offset + len(chunk),
                        "text_sha256": hashlib.sha256(chunk.encode()).hexdigest(),
                        "contract_value": None,
                    }
                )
            cursor = stop
        if sources:
            groups.append(
                {
                    "label": label,
                    "number": number,
                    "start_char": start,
                    "end_char": end,
                    "sources": sources,
                    "references": sorted(
                        set(
                            re.findall(
                                r"\bsection\s+(\d+[A-Z]?)\b", text[start:end], re.I
                            )
                        )
                    ),
                }
            )
    return groups


def section_coverage(groups, selected, sources):
    numbers = [g["number"] for g in groups]
    available = {
        g["number"]
        for index, g in enumerate(groups)
        if index in selected and numbers.count(g["number"]) == 1
    }
    selected_rows, omitted_rows = [], []
    for index, group in enumerate(groups):
        row = {k: group[k] for k in ("label", "start_char", "end_char")}
        if index in selected:
            row["source_refs"] = [
                s["source_ref"]
                for s in sources
                if group["start_char"] <= s["start_char"] < group["end_char"]
            ]
            # Lexical references, not proof of legal resolution of another law.
            row["unresolved_section_references"] = [
                r for r in group["references"] if r not in available
            ]
            selected_rows.append(row)
        else:
            omitted_rows.append(row)
    return {
        "complete_document": len(selected) == len(groups),
        "selected_sections": selected_rows,
        "omitted_sections": omitted_rows,
        "total_chunks": sum(len(g["sources"]) for g in groups),
    }
