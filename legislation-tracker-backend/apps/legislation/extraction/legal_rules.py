import re
from collections.abc import Iterator, Sequence
from datetime import date
from decimal import Decimal

from .federal_structure import sentence_spans
from .types import ExtractedClaim, SourceSpan, StructuralSection

MODAL_RE = re.compile(
    r"\b(?P<modal>shall not|may not|is prohibited from|is required to|"
    r"is authorized to|shall|must|may)\b",
    re.IGNORECASE,
)
_QUOTED_TERM_RE = (
    r"(?:[\"“](?P<term_double>[^\"”]+)[\"”]|"
    r"[‘'](?P<term_single>[^’']+)[’'])"
)
_EXPLICIT_DEFINITION_RE = re.compile(
    rf"\bThe\s+term\s+{_QUOTED_TERM_RE}\s+"
    r"(?P<kind>means|includes)\s+(?P<definition>.+)",
    re.IGNORECASE,
)
_SECTION_DEFINITION_RE = re.compile(
    rf"^{_QUOTED_TERM_RE}\s+"
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
_LEADING_CONDITION_RE = re.compile(
    r"^(?P<condition>(?:if|when|unless|subject\s+to)\b.*?),\s*"
    r"(?P<actor>.+)$",
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
_MONEY_RE = re.compile(
    r"(?:\$\s*(?P<dollar_amount>\d[\d,]*(?:\.\d+)?)"
    r"(?:\s*(?P<dollar_scale>thousand|million|billion))?"
    r"|(?P<word_amount>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<word_scale>thousand|million|billion)?\s+dollars\b)",
    re.IGNORECASE,
)
_FISCAL_RANGE_RE = re.compile(
    r"\bfiscal\s+years\s+(?P<start>\d{4})\s+"
    r"(?:through|to|-)\s+(?P<end>\d{4})\b",
    re.IGNORECASE,
)
_FISCAL_YEAR_RE = re.compile(r"\bfiscal\s+year\s+(?P<year>\d{4})\b", re.IGNORECASE)
_SUCH_SUMS_RE = re.compile(r"\bsuch\s+sums\s+as\s+may\s+be\s+necessary\b", re.IGNORECASE)
_RELATIVE_TIMELINE_RE = re.compile(
    r"\b(?P<prefix>not\s+later\s+than\s+)?(?P<value>\d+)\s+"
    r"(?P<unit>days?|months?|years?)\s+after\s+"
    r"(?P<trigger>[^,.;]+)",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"\b(?P<month>January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+"
    r"(?P<day>\d{1,2}),\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)
_TARGET_RE = re.compile(
    r"\b(?P<target>section\s+[0-9A-Z-]+(?:\s+of\s+the\s+[^,.;:]+?\s+Act)?|"
    r"paragraph\s+\([^)]+\))(?!\w)",
    re.IGNORECASE,
)
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_AMENDMENT_PATTERNS = (
    ("strike_and_insert", re.compile(r"\bstrike\b.+\band\s+insert\b", re.IGNORECASE)),
    ("replace", re.compile(r"\breplace\b.+\bwith\b", re.IGNORECASE)),
    (
        "add",
        re.compile(r"\b(?:is\s+amended\s+by\s+adding|add(?:ing)?)\b", re.IGNORECASE),
    ),
    ("insert", re.compile(r"\binsert\b", re.IGNORECASE)),
    ("strike", re.compile(r"\bstrike\b", re.IGNORECASE)),
    ("redesignate", re.compile(r"\bredesignat(?:e|ed|ing)\b", re.IGNORECASE)),
    ("repeal", re.compile(r"\brepeal(?:ed|ing)?\b", re.IGNORECASE)),
    ("amend", re.compile(r"\b(?:is\s+amended|amend(?:ed|ing)?)\b", re.IGNORECASE)),
)


def _strip_terminal_punctuation(value: str) -> str:
    return value.strip().rstrip(".;:").strip()


def _definition_term(match: re.Match[str]) -> str:
    return (match.group("term_double") or match.group("term_single")).strip()


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
    sections: Sequence[StructuralSection],
) -> bool:
    return any(
        candidate.heading
        and phrase in candidate.heading.casefold()
        and candidate.span.start_char <= section.span.start_char
        and section.span.start_char < candidate.span.end_char
        for candidate in sections
    )


def _is_modal_excluded(
    sentence: SourceSpan,
    modal_start: int,
    section: StructuralSection,
    sections: Sequence[StructuralSection],
) -> bool:
    if _heading_contains(section, "table of contents", sections):
        return True
    if _heading_contains(section, "definition", sections):
        return True
    if _EXPLICIT_DEFINITION_RE.search(sentence.text):
        return True
    if _AMENDMENT_INSTRUCTION_RE.match(sentence.text) or _amendment_details(
        sentence.text
    ):
        return True
    if sentence.text[modal_start:].casefold().startswith(
        "is authorized to be appropriated"
    ):
        return True
    such_sums = _SUCH_SUMS_RE.search(sentence.text)
    if such_sums is not None and such_sums.start() <= modal_start < such_sums.end():
        return True
    return any(
        quoted.start() <= modal_start < quoted.end()
        for quoted in _QUOTED_RANGE_RE.finditer(sentence.text)
    )


def extract_modality_claims(
    source_text: str, sections: Sequence[StructuralSection]
) -> tuple[ExtractedClaim, ...]:
    claims = []
    for section, sentence in _iter_operative_sentences(source_text, sections):
        for modal_match in MODAL_RE.finditer(sentence.text):
            if _is_modal_excluded(sentence, modal_match.start(), section, sections):
                continue

            actor = _strip_terminal_punctuation(sentence.text[: modal_match.start()])
            action = _strip_terminal_punctuation(sentence.text[modal_match.end() :])
            conditions = []
            leading_condition = _LEADING_CONDITION_RE.match(actor)
            if leading_condition is not None:
                conditions.append(
                    _strip_terminal_punctuation(
                        leading_condition.group("condition")
                    )
                )
                actor = _strip_terminal_punctuation(leading_condition.group("actor"))
            condition_match = _CONDITION_RE.search(action)
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
    for section, sentence in _iter_operative_sentences(source_text, sections):
        match = _EXPLICIT_DEFINITION_RE.search(sentence.text)
        explicit = match is not None
        if match is None and _heading_contains(section, "definition", sections):
            match = _SECTION_DEFINITION_RE.search(sentence.text)
        if match is None:
            continue

        definition_type = match.group("kind").casefold()
        definition = _strip_terminal_punctuation(match.group("definition"))
        term = _definition_term(match)
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


def normalize_usd_amount(raw: str) -> str:
    normalized = raw.casefold().replace("$", "").replace(",", "")
    normalized = re.sub(r"\bdollars?\b", "", normalized).strip()
    multiplier = Decimal(1)
    for suffix, scale in (
        ("thousand", "1000"),
        ("million", "1000000"),
        ("billion", "1000000000"),
    ):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)].strip()
            multiplier = Decimal(scale)
            break
    amount = Decimal(normalized) * multiplier
    return format(amount.quantize(Decimal("0.01")), ".2f")


def _fiscal_years(text: str) -> list[int]:
    range_match = _FISCAL_RANGE_RE.search(text)
    if range_match is not None:
        start = int(range_match.group("start"))
        end = int(range_match.group("end"))
        if start <= end and end - start <= 100:
            return list(range(start, end + 1))
        return []
    year_match = _FISCAL_YEAR_RE.search(text)
    return [int(year_match.group("year"))] if year_match else []


def _funding_purpose(text: str) -> str | None:
    carry_out = re.search(r"\bto\s+(carry\s+out\b.+)$", text, re.IGNORECASE)
    if carry_out is not None:
        return _strip_terminal_punctuation(carry_out.group(1))
    purposes = list(
        re.finditer(r"\bfor\s+(?!fiscal\s+years?\b)(?P<purpose>.+)$", text, re.IGNORECASE)
    )
    return (
        _strip_terminal_punctuation(purposes[-1].group("purpose"))
        if purposes
        else None
    )


def extract_funding_claims(
    source_text: str, sections: Sequence[StructuralSection]
) -> tuple[ExtractedClaim, ...]:
    claims = []
    for section, sentence in _iter_operative_sentences(source_text, sections):
        text = sentence.text
        lowered = text.casefold()
        such_sums = _SUCH_SUMS_RE.search(text) is not None
        money = _MONEY_RE.search(text)
        if "appropriat" not in lowered and not such_sums:
            continue
        if money is None and not such_sums:
            continue

        authorization = "authorized to be appropriated" in lowered
        if such_sums:
            amount = None
            amount_type = "such_sums"
            currency = None
            suffix = "_such_sums"
        else:
            amount = normalize_usd_amount(money.group(0))
            amount_type = "specified"
            currency = "USD"
            suffix = ""
        authority = "authorization" if authorization else "appropriation"
        claims.append(
            ExtractedClaim(
                category="funding_items",
                fields={
                    "amount": amount,
                    "amount_type": amount_type,
                    "currency": currency,
                    "fiscal_years": _fiscal_years(text),
                    "purpose": _funding_purpose(text),
                },
                section_label=section.label,
                evidence=(sentence,),
                rule_id=f"funding.{authority}{suffix}.v1",
            )
        )
    return tuple(claims)


def _normalized_date(match: re.Match[str]) -> str | None:
    try:
        parsed = date(
            int(match.group("year")),
            _MONTHS[match.group("month").casefold()],
            int(match.group("day")),
        )
    except ValueError:
        return None
    return parsed.isoformat()


def extract_timeline_claims(
    source_text: str, sections: Sequence[StructuralSection]
) -> tuple[ExtractedClaim, ...]:
    claims = []
    for section, sentence in _iter_operative_sentences(source_text, sections):
        relative = _RELATIVE_TIMELINE_RE.search(sentence.text)
        date_match = _DATE_RE.search(sentence.text)
        normalized_date = _normalized_date(date_match) if date_match else None
        effective = bool(
            re.search(r"\b(?:takes\s+effect|effective\s+on)\b", sentence.text, re.IGNORECASE)
        )
        if effective and date_match is not None and normalized_date is None:
            continue

        if relative is not None:
            fields = {
                "timeline_type": "relative",
                "date": None,
                "relative_value": int(relative.group("value")),
                "relative_unit": relative.group("unit").casefold().rstrip("s") + "s",
                "trigger": relative.group("trigger").strip(),
            }
            rule_id = "timeline.relative_deadline.v1"
        elif effective:
            fields = {
                "timeline_type": "effective",
                "date": normalized_date,
                "relative_value": None,
                "relative_unit": None,
                "trigger": None,
            }
            rule_id = "timeline.effective.v1"
        elif normalized_date is not None:
            fields = {
                "timeline_type": "absolute",
                "date": normalized_date,
                "relative_value": None,
                "relative_unit": None,
                "trigger": None,
            }
            rule_id = "timeline.absolute_date.v1"
        else:
            continue

        claims.append(
            ExtractedClaim(
                category="timeline_items",
                fields=fields,
                section_label=section.label,
                evidence=(sentence,),
                rule_id=rule_id,
            )
        )
    return tuple(claims)


def _amendment_details(text: str) -> tuple[str, str | None, str | None] | None:
    operation = next(
        (name for name, pattern in _AMENDMENT_PATTERNS if pattern.search(text)), None
    )
    if operation is None:
        return None
    target_match = _TARGET_RE.search(text)
    if target_match is None and not _AMENDMENT_INSTRUCTION_RE.match(text):
        return None

    payloads = [match.group(0)[1:-1] for match in _QUOTED_RANGE_RE.finditer(text)]
    removed_text = None
    inserted_text = None
    if operation in {"strike", "strike_and_insert", "replace"} and payloads:
        removed_text = payloads[0]
    if operation in {"add", "insert"} and payloads:
        inserted_text = payloads[0]
    elif operation in {"strike_and_insert", "replace"} and len(payloads) > 1:
        inserted_text = payloads[1]
    return operation, removed_text, inserted_text


def extract_amendment_claims(
    source_text: str, sections: Sequence[StructuralSection]
) -> tuple[ExtractedClaim, ...]:
    claims = []
    for section, sentence in _iter_operative_sentences(source_text, sections):
        details = _amendment_details(sentence.text)
        if details is None:
            continue
        operation, removed_text, inserted_text = details
        target_match = _TARGET_RE.search(sentence.text)
        claims.append(
            ExtractedClaim(
                category="amendment_operations",
                fields={
                    "target": target_match.group("target") if target_match else None,
                    "operation": operation,
                    "removed_text": removed_text,
                    "inserted_text": inserted_text,
                },
                section_label=section.label,
                evidence=(sentence,),
                rule_id=f"amendment.{operation}.v1",
            )
        )
    return tuple(claims)


def extract_claims(
    source_text: str, sections: Sequence[StructuralSection]
) -> tuple[ExtractedClaim, ...]:
    category_order = {
        "requirements": 0,
        "amendment_operations": 1,
        "funding_items": 2,
        "timeline_items": 3,
        "definitions": 4,
        "applicability": 5,
    }
    claims = (
        extract_modality_claims(source_text, sections)
        + extract_amendment_claims(source_text, sections)
        + extract_funding_claims(source_text, sections)
        + extract_timeline_claims(source_text, sections)
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
