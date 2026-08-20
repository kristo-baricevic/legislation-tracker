import re
from collections.abc import Iterator, Sequence

from .federal_structure import sentence_spans
from .types import ExtractedClaim, SourceSpan, StructuralSection

MODAL_RE = re.compile(
    r"\b(?P<modal>shall not|may not|is prohibited from|is required to|"
    r"is authorized to|shall|must|may)\b",
    re.IGNORECASE,
)
_EXPLICIT_DEFINITION_RE = re.compile(
    r"\bThe\s+term\s+[\"“](?P<term>[^\"”]+)[\"”]\s+"
    r"(?P<kind>means|includes)\s+(?P<definition>.+)",
    re.IGNORECASE,
)
_SECTION_DEFINITION_RE = re.compile(
    r"^[\"“](?P<term>[^\"”]+)[\"”]\s+"
    r"(?P<kind>means|includes)\s+(?P<definition>.+)",
    re.IGNORECASE,
)
_QUOTED_RANGE_RE = re.compile(r'“[^”]*”|"[^"]*"|‘[^’]*’|\'[^\']*\'')
_AMENDMENT_INSTRUCTION_RE = re.compile(
    r"^\s*(?:strike|insert|replace|redesignate|repeal|amend)\b", re.IGNORECASE
)
_CONDITION_RE = re.compile(
    r"(?:,\s*|\s+)(?P<condition>(?:if|when|unless|subject\s+to)\b.+)$",
    re.IGNORECASE,
)
_DOES_NOT_APPLY_RE = re.compile(
    r"^(?P<subject>.+?)\s+does\s+not\s+apply\s+to\s+(?P<scope>.+)$",
    re.IGNORECASE,
)
_APPLIES_RE = re.compile(
    r"^(?P<subject>.+?)\s+applies\s+to\s+(?P<scope>.+)$", re.IGNORECASE
)
_ELIGIBLE_RE = re.compile(
    r"^(?:An?\s+)?(?P<subject>eligible\s+(?:entity|applicant))\s+is\s+"
    r"(?P<scope>.+)$",
    re.IGNORECASE,
)
_EXCLUDES_RE = re.compile(
    r"^(?P<subject>.+?)\s+excludes\s+(?P<scope>.+)$", re.IGNORECASE
)

_MODALITY_BY_PHRASE = {
    "shall": "required",
    "must": "required",
    "is required to": "required",
    "shall not": "prohibited",
    "may not": "prohibited",
    "is prohibited from": "prohibited",
    "may": "permitted",
    "is authorized to": "permitted",
}


def _strip_terminal_punctuation(value: str) -> str:
    return value.strip().rstrip(".;:").strip()


def _iter_operative_sentences(
    source_text: str, sections: Sequence[StructuralSection]
) -> Iterator[tuple[StructuralSection, SourceSpan]]:
    for section in sections:
        if section.level not in {"section", "subdivision"}:
            continue
        for sentence in sentence_spans(section, source_text):
            yield section, sentence


def _heading_contains(
    section: StructuralSection,
    phrase: str,
    sections_by_label: dict[str, StructuralSection],
) -> bool:
    current: StructuralSection | None = section
    visited = set()
    while current is not None and current.label not in visited:
        visited.add(current.label)
        if current.heading and phrase in current.heading.casefold():
            return True
        current = (
            sections_by_label.get(current.parent_label)
            if current.parent_label is not None
            else None
        )
    return False


def _is_modal_excluded(
    sentence: SourceSpan,
    modal_start: int,
    section: StructuralSection,
    sections_by_label: dict[str, StructuralSection],
) -> bool:
    if _heading_contains(section, "table of contents", sections_by_label):
        return True
    if _heading_contains(section, "definition", sections_by_label):
        return True
    if _EXPLICIT_DEFINITION_RE.search(sentence.text):
        return True
    if _AMENDMENT_INSTRUCTION_RE.match(sentence.text):
        return True
    return any(
        quoted.start() <= modal_start < quoted.end()
        for quoted in _QUOTED_RANGE_RE.finditer(sentence.text)
    )


def extract_modality_claims(
    source_text: str, sections: Sequence[StructuralSection]
) -> tuple[ExtractedClaim, ...]:
    claims = []
    sections_by_label = {section.label: section for section in sections}
    for section, sentence in _iter_operative_sentences(source_text, sections):
        for modal_match in MODAL_RE.finditer(sentence.text):
            if _is_modal_excluded(
                sentence, modal_match.start(), section, sections_by_label
            ):
                continue

            actor = _strip_terminal_punctuation(sentence.text[: modal_match.start()])
            action = _strip_terminal_punctuation(sentence.text[modal_match.end() :])
            condition_match = _CONDITION_RE.search(action)
            conditions = []
            if condition_match is not None:
                conditions.append(
                    _strip_terminal_punctuation(condition_match.group("condition"))
                )
                action = _strip_terminal_punctuation(action[: condition_match.start()])

            modal = modal_match.group("modal").casefold()
            if modal == "may" and action.casefold().startswith("discuss whether"):
                continue
            if not actor or not action or len(actor) > 300 or len(action) > 1_000:
                continue

            claims.append(
                ExtractedClaim(
                    category="requirements",
                    fields={
                        "modality": _MODALITY_BY_PHRASE[modal],
                        "actor": actor,
                        "action": action,
                        "object": None,
                        "conditions": conditions,
                    },
                    section_label=section.label,
                    evidence=(sentence,),
                    rule_id=f"modality.{modal.replace(' ', '_')}.v1",
                )
            )
            break
    return tuple(claims)


def extract_definition_claims(
    source_text: str, sections: Sequence[StructuralSection]
) -> tuple[ExtractedClaim, ...]:
    claims = []
    sections_by_label = {section.label: section for section in sections}
    for section, sentence in _iter_operative_sentences(source_text, sections):
        match = _EXPLICIT_DEFINITION_RE.search(sentence.text)
        explicit = match is not None
        if match is None and _heading_contains(section, "definition", sections_by_label):
            match = _SECTION_DEFINITION_RE.search(sentence.text)
        if match is None:
            continue

        definition_type = match.group("kind").casefold()
        definition = _strip_terminal_punctuation(match.group("definition"))
        term = match.group("term").strip()
        if not term or not definition:
            continue
        context = "term" if explicit else "section"
        claims.append(
            ExtractedClaim(
                category="definitions",
                fields={
                    "term": term,
                    "definition": definition,
                    "definition_type": definition_type,
                },
                section_label=section.label,
                evidence=(sentence,),
                rule_id=f"definition.{context}_{definition_type}.v1",
            )
        )
    return tuple(claims)


def extract_applicability_claims(
    source_text: str, sections: Sequence[StructuralSection]
) -> tuple[ExtractedClaim, ...]:
    patterns = (
        (_DOES_NOT_APPLY_RE, "does_not_apply", "does_not_apply"),
        (_APPLIES_RE, "applies", "applies"),
        (_ELIGIBLE_RE, "eligible", "eligible"),
        (_EXCLUDES_RE, "excluded", "excludes"),
    )
    claims = []
    for section, sentence in _iter_operative_sentences(source_text, sections):
        text = sentence.text.strip()
        for pattern, applicability_type, rule_name in patterns:
            match = pattern.match(text)
            if match is None:
                continue
            subject = match.group("subject").strip()
            if applicability_type == "eligible":
                subject = subject.casefold()
            scope = _strip_terminal_punctuation(match.group("scope"))
            if not subject or not scope:
                break
            claims.append(
                ExtractedClaim(
                    category="applicability",
                    fields={
                        "subject": subject,
                        "scope": scope,
                        "applicability_type": applicability_type,
                    },
                    section_label=section.label,
                    evidence=(sentence,),
                    rule_id=f"applicability.{rule_name}.v1",
                )
            )
            break
    return tuple(claims)


def extract_claims(
    source_text: str, sections: Sequence[StructuralSection]
) -> tuple[ExtractedClaim, ...]:
    category_order = {"requirements": 0, "definitions": 1, "applicability": 2}
    claims = (
        extract_modality_claims(source_text, sections)
        + extract_definition_claims(source_text, sections)
        + extract_applicability_claims(source_text, sections)
    )
    return tuple(
        sorted(
            claims,
            key=lambda claim: (
                claim.evidence[0].start_char,
                category_order[claim.category],
            ),
        )
    )
