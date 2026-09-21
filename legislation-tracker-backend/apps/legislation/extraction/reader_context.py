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


def _is_choice(introduction, children):
    return bool(
        re.search(
            r"\b(?:one|two|three|\d+|any|either)(?:\s+or\s+more)?\s+of\s+(?:the\s+)?following\b",
            introduction,
            re.I,
        )
        or any(
            re.search(r"\bor\s*[.;]?\s*$", child.span.text, re.I)
            for child in children[:-1]
        )
    )


def _has_independent_modal(text):
    return any(
        not re.search(r"\b(?:which|that)\s*$", text[: match.start()], re.I)
        for match in MODAL_RE.finditer(text)
    )


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

    def consume_inherited_fragments(start, end):
        # Only replace leaves borrowing their duty from the list introduction.
        # Explicit child actors/modals remain independently authoritative.
        for claim in claims:
            if claim.category != "requirements":
                continue
            span = claim.evidence[-1]
            if (
                start <= span.start_char
                and span.end_char <= end
                and not _has_independent_modal(span.text)
            ):
                replaced_ranges.append((span.start_char, span.end_char))

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
        if any(
            a <= introduction.start_char and introduction.end_char <= b
            for a, b in replaced_ranges
        ):
            continue
        actor = _clean(introduction.text[: modal.start()])
        action = _clean(introduction.text[modal.end() :])
        if not actor or modal.group().lower() not in {"shall", "must", "may"}:
            continue
        if _is_choice(action, direct):
            # A choice is one obligation, not a required duty for every leaf.
            # Keep its exact source-backed grouping, including cardinality.
            start, end = direct[0].span.start_char, direct[-1].span.end_char
            grouped_action = (
                f"{action + ': ' if action else ''}{_clean(source[start:end])}"
            )
            if len(actor) + len(grouped_action) < 3900 and not any(
                a < end and start < b for a, b in quoted_ranges
            ):
                additions.append(
                    make(
                        section,
                        "requirements",
                        {
                            "modality": "permitted"
                            if modal.group().lower() == "may"
                            else "required",
                            "actor": actor,
                            "action": grouped_action,
                            "object": None,
                            "conditions": [],
                        },
                        [introduction, SourceSpan(source[start:end], start, end)],
                        "reader.list.choice.v1",
                    )
                )
                replaced_ranges.append((introduction.start_char, introduction.end_char))
                consume_inherited_fragments(start, end)
            # If too large or quoted, leave original claims authoritative.
            continue
        addition_start = len(additions)
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
            optional=bool(optional),
            modal=modal,
            actor=actor,
            prefix=prefix,
        ):
            if any(
                start < node.span.end_char and node.span.start_char < end
                for start, end in quoted_ranges
            ):
                return
            own_spans = []
            for span in sentence_spans(node, source):
                # An independent actor/modal is its own duty, not a list
                # fragment. Leave its claims (and any nested list) intact.
                if _has_independent_modal(span.text):
                    break
                own_spans.append(span)
            if not own_spans:
                return
            raw = " ".join(s.text for s in own_spans)
            phrase = _clean(raw)
            phrase = re.sub(r";?\s+(?:and|or)$", "", phrase).rstrip(";")
            descendants = children.get(node.source_id, [])
            local_optional = re.search(
                r"\b(?:which|that)\s+may include\b", phrase, re.I
            )
            if local_optional and not optional and modal.group().lower() != "may":
                # Keep the compulsory category separate from optional examples.
                duty = "; ".join(
                    parents + [phrase[: local_optional.start()].rstrip(" ,")]
                )
                additions.append(
                    make(
                        node,
                        "requirements",
                        {
                            "modality": "required",
                            "actor": actor,
                            "action": f"{prefix} {duty}",
                            "object": None,
                            "conditions": [],
                        },
                        evidence + own_spans,
                        "reader.list.duty.v1",
                    )
                )
            optional = optional or bool(local_optional)
            if descendants and _is_choice(phrase, descendants):
                start, end = (
                    descendants[0].span.start_char,
                    descendants[-1].span.end_char,
                )
                grouped = f"{prefix} {'; '.join(parents + [phrase])}: {_clean(source[start:end])}"
                if len(actor) + len(grouped) >= 3900:
                    return
                additions.append(
                    make(
                        node,
                        "requirements",
                        {
                            "modality": "permitted"
                            if optional or modal.group().lower() == "may"
                            else "required",
                            "actor": actor,
                            "action": grouped,
                            "object": None,
                            "conditions": [],
                        },
                        evidence
                        + own_spans
                        + [SourceSpan(source[start:end], start, end)],
                        "reader.list.choice.v1",
                    )
                )
                replaced_ranges.extend((s.start_char, s.end_char) for s in own_spans)
                consume_inherited_fragments(start, end)
                return
            replaced_ranges.extend((s.start_char, s.end_char) for s in own_spans)
            if descendants:
                for child in descendants:
                    walk(
                        child,
                        parents + [phrase],
                        evidence + own_spans,
                        optional=optional,
                    )
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
        if len(additions) > addition_start:
            replaced_ranges.append((introduction.start_char, introduction.end_char))

    retained = [
        c
        for c in claims
        if not (
            c.category == "requirements"
            and any(
                a <= c.evidence[-1].start_char and c.evidence[-1].end_char <= b
                for a, b in replaced_ranges
            )
        )
    ]
    # Avoid duplicates where the quoted-term extractor already recognized a term.
    existing = {
        (c.category, c.section_id) for c in retained if c.category == "definitions"
    }
    return tuple(
        retained + [c for c in additions if (c.category, c.section_id) not in existing]
    )
