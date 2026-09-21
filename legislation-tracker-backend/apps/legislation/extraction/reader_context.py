"""V2.1-only resolution of explicit definitions and enumerated requirements.

Keep original spans. Never fill in cross-referenced law that is not in the source.
"""

import re

from .federal_clauses import _quoted_block_ranges
from .federal_structure import sentence_spans
from .legal_rules import MODAL_RE
from .types import ExtractedClaim, SourceSpan


def _clean(text):
    text = re.sub(r"(?m)^\s*\([A-Za-z0-9]+\)\s*", "", text)
    return re.sub(r"\s+", " ", text).strip().rstrip(".;:,—–- ")


def enrich_reader_claims(source, sections, claims):
    additions = []
    replaced_ranges = []
    quoted_ranges = _quoted_block_ranges(source)
    by_path = {
        tuple((p.level, p.label) for p in section.path): section for section in sections
    }
    children = {}
    for section in sections:
        parent = by_path.get(tuple((p.level, p.label) for p in section.path[:-1]))
        if parent:
            children.setdefault(parent.source_id, []).append(section)

    def make(section, category, fields, evidence, rule):
        return ExtractedClaim(
            category,
            fields,
            section.label,
            tuple(evidence),
            rule,
            section.source_id,
            section.source_id,
            section.path,
        )

    for section in sections:
        if any(start <= section.span.start_char < end for start, end in quoted_ranges):
            continue
        if any("definition" in (p.heading or "").lower() for p in section.path):
            # XML often removes typographic quotation marks around defined terms.
            text = section.span.text
            match = re.search(
                r"\bThe term ([^\n]{1,120}?) (means|includes|has the meaning given)\b",
                text,
                re.I,
            )
            if not match or match.group(1).startswith(('"', "“", "'", "‘")):
                continue
            # Only this provision's own definition; do not capture a descendant twice.
            own = sentence_spans(section, source)
            if not own or match.start() >= own[-1].end_char - section.span.start_char:
                continue
            start = section.span.start_char + match.start()
            raw = source[start : section.span.end_char].rstrip()
            definition = _clean(raw[match.end() - match.start() :].lstrip("—–- :"))
            if match.group(2).lower() == "has the meaning given":
                definition = "the meaning given " + definition
            if definition:
                additions.append(
                    make(
                        section,
                        "definitions",
                        {
                            "term": match.group(1),
                            "definition": definition,
                            "definition_type": "includes"
                            if match.group(2).lower() == "includes"
                            else "means",
                        },
                        [SourceSpan(raw, start, start + len(raw))],
                        "reader.definition.v1",
                    )
                )
            continue

        direct = children.get(section.source_id, [])
        spans = sentence_spans(section, source)
        if not direct or not spans:
            continue
        introduction = spans[-1]
        if not introduction.text.rstrip().endswith((":", "—", "–", "-")):
            continue
        modal = MODAL_RE.search(introduction.text)
        if not modal:
            continue
        # Process the highest modal list once; nested leaves retain every parent.
        if any(a <= section.span.start_char < b for a, b in replaced_ranges):
            continue
        actor = _clean(introduction.text[: modal.start()])
        action = _clean(introduction.text[modal.end() :])
        if not actor or modal.group().lower() not in {"shall", "must", "may"}:
            continue
        replaced_ranges.append((section.span.start_char, section.span.end_char))
        optional = re.search(r"\bmay include\b", action, re.I)
        if optional:
            # Preserve the compulsory lead separately from its optional examples.
            lead = action[: optional.start()].rstrip()
            lead = re.sub(r"\s+(?:that|which)$", "", lead)
            additions.append(
                make(
                    section,
                    "requirements",
                    {
                        "modality": "permitted"
                        if modal.group().lower() == "may"
                        else "required",
                        "actor": actor,
                        "action": lead,
                        "object": None,
                        "conditions": [],
                    },
                    [introduction],
                    "reader.list.duty.v1",
                )
            )
        prefix = re.sub(r"\s+(?:the )?following$", "", action, flags=re.I)
        if optional:
            prefix = (
                "use grant funds for"
                if re.match(r"use (?:the )?grant funds\b", action, re.I)
                else f"{lead}, including"
            )

        def walk(
            node,
            parents,
            evidence,
            *,
            optional=optional,
            modal=modal,
            actor=actor,
            prefix=prefix,
        ):
            if any(
                start < node.span.end_char and node.span.start_char < end
                for start, end in quoted_ranges
            ):
                return
            own_spans = sentence_spans(node, source)
            if not own_spans:
                return
            raw = " ".join(s.text for s in own_spans)
            phrase = _clean(raw)
            phrase = re.sub(r";?\s+(?:and|or)$", "", phrase).rstrip(";")
            descendants = children.get(node.source_id, [])
            if descendants:
                for child in descendants:
                    walk(child, parents + [phrase], evidence + list(own_spans))
                return
            joined = "; ".join(parents + [phrase])
            joined = re.sub(r"\bwhich may include\b", "including", joined, flags=re.I)
            joined = re.sub(
                r"\bmay include the following\b", "including", joined, flags=re.I
            )
            # Do not turn an optional example into a compulsory activity.
            mode = (
                "permitted"
                if optional or modal.group().lower() == "may"
                else "required"
            )
            additions.append(
                make(
                    node,
                    "requirements",
                    {
                        "modality": mode,
                        "actor": actor,
                        "action": f"{prefix} {joined}",
                        "object": None,
                        "conditions": [],
                    },
                    evidence + list(own_spans),
                    "reader.list.leaf.v1",
                )
            )

        for child in direct:
            walk(child, [], [introduction])

    retained = [
        c
        for c in claims
        if not (
            c.category == "requirements"
            and any(a <= c.evidence[-1].start_char < b for a, b in replaced_ranges)
        )
    ]
    # Avoid duplicates where the quoted-term extractor already recognized a term.
    existing = {
        (c.category, c.section_id) for c in retained if c.category == "definitions"
    }
    return tuple(
        retained + [c for c in additions if (c.category, c.section_id) not in existing]
    )
