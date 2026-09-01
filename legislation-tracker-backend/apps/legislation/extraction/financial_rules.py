"""Deterministic extraction of explicit federal financial provisions."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from .display_text import normalize_reader_fragment
from .federal_clauses import iter_operative_clauses
from .federal_structure import sentence_spans
from .types import ExtractedClaim, SourceSpan, StructuralSection

_ACTION_RE = re.compile(
    r"(?P<authorization>\bauthorized\s+to\s+be\s+appropriated\b)|"
    r"(?P<appropriation>\b(?:there\s+(?:is|are)\s+|(?:is|are)\s+(?:hereby\s+)?)"
    r"appropriated\b)|"
    r"(?P<set_aside>\bset(?:ting)?\s+aside\b)|"
    r"(?P<allocation>\ballocat(?:e|es|ed|ing|ion)\b)|"
    r"(?P<transfer>\btransfer(?:s|red|ring)?\b)|"
    r"(?P<rescission>\brescind(?:s|ed|ing)?\b|\brescission\b)|"
    r"(?P<reduction>\breduc(?:e|es|ed|ing|tion)\b)|"
    r"(?P<cancellation>\bcancel(?:s|ed|ing|led|ling|lation)?\b)|"
    r"(?P<limitation>\bnot\s+more\s+than\b|\bnot\s+to\s+exceed\b|"
    r"\b(?:shall|must|may)\s+not\s+exceed\b|\bup\s+to\b)|"
    r"(?P<other_explicit>\b(?:make|makes|made)\s+available\b|"
    r"\bprovid(?:e|es|ed|ing)\s+funding\b)",
    re.IGNORECASE,
)
_MONEY_RE = re.compile(
    r"(?:\$\s*(?P<dollar_amount>\d[\d,]*(?:\.\d+)?)"
    r"(?:\s*(?P<dollar_scale>thousand|million|billion))?"
    r"|(?P<word_amount>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<word_scale>thousand|million|billion)?\s+dollars\b)",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"\b(?P<percentage>\d+(?:\.\d+)?)\s+percent\b", re.I)
_SUCH_SUMS_RE = re.compile(
    r"\bsuch\s+sums\s+as\s+may\s+be\s+necessary\b", re.IGNORECASE
)
_FISCAL_RANGE_RE = re.compile(
    r"\bfiscal\s+years\s+(?P<start>\d{4})\s+" r"(?:through|to|-)\s+(?P<end>\d{4})\b",
    re.IGNORECASE,
)
_FISCAL_YEAR_RE = re.compile(r"\bfiscal\s+year\s+(?P<year>\d{4})\b", re.I)
_PURPOSE_RE = re.compile(
    r"\bfor\s+(?!each\s+of\s+fiscal\s+years?\b|fiscal\s+years?\b)"
    r"(?P<purpose>.+?)(?=,\s+(?:and|or)\b|;|\.$|$)",
    re.IGNORECASE | re.DOTALL,
)
_CARRY_OUT_RE = re.compile(
    r"\bto\s+(?P<purpose>carry\s+out\b.+?)(?=;|\.$|$)", re.I | re.DOTALL
)
_INFINITIVE_PURPOSE_RE = re.compile(
    r"\bto\s+(?P<purpose>(?:acquire|build|construct|develop|establish|expand|"
    r"fund|implement|improve|increase|maintain|modernize|provide|purchase|"
    r"reduce|replace|restore|support)\b.+?)(?=;|\.$|$)",
    re.I | re.DOTALL,
)
_FROM_ACCOUNT_RE = re.compile(
    r"\bfrom\s+(?P<account>.+?)(?=\s+to\s+|\s+for\s+fiscal\s+year|[,;.]|$)",
    re.IGNORECASE | re.DOTALL,
)
_TO_ACCOUNT_RE = re.compile(
    r"\bto\s+(?P<account>.+?)(?=\s+for\s+fiscal\s+year|[,;.]|$)",
    re.IGNORECASE | re.DOTALL,
)

_DIRECTION_BY_ACTION = {
    "appropriation": "increase",
    "authorization": "increase",
    "allocation": "increase",
    "transfer": "neutral_transfer",
    "rescission": "decrease",
    "reduction": "decrease",
    "cancellation": "decrease",
    "set_aside": "increase",
    "limitation": "limit",
    "other_explicit": "increase",
}


@dataclass(frozen=True)
class _ActionMatch:
    action: str
    start: int
    end: int


@dataclass(frozen=True)
class _AmountMatch:
    amount: str | None
    amount_type: str
    currency: str | None
    start: int
    end: int


@dataclass(frozen=True)
class _InheritedContext:
    action: str
    evidence: SourceSpan
    fiscal_years: tuple[int, ...]
    source_account: str | None
    destination_account: str | None


def _strip(value: str) -> str:
    return normalize_reader_fragment(value).strip().rstrip(".;:,—–-").strip()


def _normalize_number(raw: str) -> str:
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
    return format((Decimal(normalized) * multiplier).quantize(Decimal("0.01")), ".2f")


def _actions(text: str) -> tuple[_ActionMatch, ...]:
    actions = []
    for match in _ACTION_RE.finditer(text):
        action = next(name for name, value in match.groupdict().items() if value)
        actions.append(_ActionMatch(action, match.start(), match.end()))
    return tuple(actions)


def _amounts(text: str) -> tuple[_AmountMatch, ...]:
    matches = []
    for match in _MONEY_RE.finditer(text):
        matches.append(
            _AmountMatch(
                amount=_normalize_number(match.group(0)),
                amount_type="specified",
                currency="USD",
                start=match.start(),
                end=match.end(),
            )
        )
    for match in _PERCENT_RE.finditer(text):
        matches.append(
            _AmountMatch(
                amount=format(
                    Decimal(match.group("percentage")).quantize(Decimal("0.01")), ".2f"
                ),
                amount_type="percentage",
                currency=None,
                start=match.start(),
                end=match.end(),
            )
        )
    for match in _SUCH_SUMS_RE.finditer(text):
        matches.append(
            _AmountMatch(
                amount=None,
                amount_type="such_sums",
                currency=None,
                start=match.start(),
                end=match.end(),
            )
        )
    return tuple(sorted(matches, key=lambda item: item.start))


def _fiscal_years(text: str) -> tuple[int, ...]:
    range_match = _FISCAL_RANGE_RE.search(text)
    if range_match is not None:
        start = int(range_match.group("start"))
        end = int(range_match.group("end"))
        if start <= end and end - start <= 100:
            return tuple(range(start, end + 1))
        return ()
    match = _FISCAL_YEAR_RE.search(text)
    return (int(match.group("year")),) if match else ()


def _accounts(text: str, action: str) -> tuple[str | None, str | None]:
    source_match = _FROM_ACCOUNT_RE.search(text)
    source = _strip(source_match.group("account")) if source_match else None
    destination = None
    if action == "transfer":
        destination_match = _TO_ACCOUNT_RE.search(text)
        destination = (
            _strip(destination_match.group("account")) if destination_match else None
        )
    return source, destination


def _purpose(text: str, action: str) -> str | None:
    carry_out = _CARRY_OUT_RE.search(text)
    if carry_out is not None:
        return _strip(carry_out.group("purpose")) or None
    matches = list(_PURPOSE_RE.finditer(text))
    if matches:
        return _strip(matches[-1].group("purpose")) or None
    if action != "transfer":
        infinitive = _INFINITIVE_PURPOSE_RE.search(text)
        if infinitive is not None:
            return _strip(infinitive.group("purpose")) or None
    return None


def _parent_section(
    section: StructuralSection, sections: Sequence[StructuralSection]
) -> StructuralSection | None:
    candidates = [
        candidate
        for candidate in sections
        if candidate.span.start_char < section.span.start_char
        and section.span.end_char <= candidate.span.end_char
    ]
    return max(candidates, key=lambda item: item.span.start_char, default=None)


def _inherited_context(
    source_text: str,
    section: StructuralSection,
    sections: Sequence[StructuralSection],
) -> _InheritedContext | None:
    parent = _parent_section(section, sections)
    while parent is not None:
        for sentence in reversed(sentence_spans(parent, source_text)):
            actions = _actions(sentence.text)
            if not actions:
                continue
            action = actions[-1].action
            source_account, destination_account = _accounts(sentence.text, action)
            return _InheritedContext(
                action=action,
                evidence=sentence,
                fiscal_years=_fiscal_years(sentence.text),
                source_account=source_account,
                destination_account=destination_account,
            )
        parent = _parent_section(parent, sections)
    return None


def _action_for_amount(
    amount: _AmountMatch, actions: Sequence[_ActionMatch]
) -> _ActionMatch:
    def distance(action: _ActionMatch) -> tuple[int, int, int]:
        if action.end <= amount.start:
            gap = amount.start - action.end
            follows_amount = 1
        elif amount.end <= action.start:
            gap = action.start - amount.end
            follows_amount = 0
        else:
            gap = 0
            follows_amount = 0
        negative_after = int(
            not (
                follows_amount == 0
                and action.action in {"rescission", "reduction", "cancellation"}
            )
        )
        return gap, negative_after, action.start

    return min(actions, key=distance)


def _amount_subclause(text: str, amounts: Sequence[_AmountMatch], index: int) -> str:
    start = 0
    if index > 0:
        between = text[amounts[index - 1].end : amounts[index].start]
        connectors = list(
            re.finditer(r"(?:[,;]\s*(?:and|or)?\s*|\b(?:and|or)\s+)", between, re.I)
        )
        start = (
            amounts[index - 1].end + connectors[-1].end()
            if connectors
            else amounts[index].start
        )
    end = amounts[index + 1].start if index + 1 < len(amounts) else len(text)
    return text[start:end]


def _percentage_is_financial(text: str) -> bool:
    return (
        re.search(
            r"(?:"
            r"\bpercent\s+of\s+(?:the\s+)?(?:amounts?|funds?|appropriations?|"
            r"budget\s+authority|unobligated\s+balances)\b|"
            r"\b(?:set\s+aside|allocate|transfer|reduce|rescind|cancel)\b"
            r"[^$%;.]{0,80}\b\d+(?:\.\d+)?\s+percent\b|"
            r"\b\d+(?:\.\d+)?\s+percent\b[^.;]{0,40}"
            r"\b(?:set\s+aside|allocated|transferred|reduced|rescinded|canceled)\b"
            r")",
            text,
            re.IGNORECASE,
        )
        is not None
    )


def _claim(
    *,
    section: StructuralSection,
    evidence: tuple[SourceSpan, ...],
    action: str,
    amount: _AmountMatch,
    fiscal_years: tuple[int, ...],
    purpose: str | None,
    source_account: str | None,
    destination_account: str | None,
    inherited: bool,
) -> ExtractedClaim:
    amount_type = "ceiling" if action == "limitation" else amount.amount_type
    suffix = ".inherited" if inherited else ""
    return ExtractedClaim(
        category="financial_items",
        fields={
            "financial_action": action,
            "direction": _DIRECTION_BY_ACTION[action],
            "amount": amount.amount,
            "amount_type": amount_type,
            "currency": amount.currency,
            "fiscal_years": list(fiscal_years),
            "purpose": purpose,
            "source_account": source_account,
            "destination_account": destination_account,
        },
        section_label=section.label,
        evidence=evidence,
        rule_id=f"financial.{action}.{amount_type}{suffix}.v1",
        source_id=section.source_id,
        section_id=section.source_id,
        section_path=section.path,
    )


def extract_financial_claims(
    source_text: str, sections: Sequence[StructuralSection]
) -> tuple[ExtractedClaim, ...]:
    """Return every explicitly supported financial provision in source order."""

    claims = []
    for section, span, _ in iter_operative_clauses(source_text, sections):
        candidate_amounts = _amounts(span.text)
        if not candidate_amounts:
            continue
        actions = _actions(span.text)
        inherited = (
            None if actions else _inherited_context(source_text, section, sections)
        )
        if not actions and inherited is None:
            continue

        amounts = tuple(
            amount
            for index, amount in enumerate(candidate_amounts)
            if amount.amount_type != "percentage"
            or _percentage_is_financial(
                _amount_subclause(span.text, candidate_amounts, index)
            )
        )
        if not amounts:
            continue

        for index, amount in enumerate(amounts):
            action_match = _action_for_amount(amount, actions) if actions else None
            action = action_match.action if action_match else inherited.action
            local_text = _amount_subclause(span.text, amounts, index)
            source_account, destination_account = _accounts(local_text, action)
            fiscal_years = _fiscal_years(local_text)
            evidence = (span,)
            if inherited is not None:
                fiscal_years = fiscal_years or inherited.fiscal_years
                source_account = source_account or inherited.source_account
                destination_account = (
                    destination_account or inherited.destination_account
                )
                evidence = (inherited.evidence, span)
            claims.append(
                _claim(
                    section=section,
                    evidence=evidence,
                    action=action,
                    amount=amount,
                    fiscal_years=fiscal_years,
                    purpose=_purpose(local_text, action),
                    source_account=source_account,
                    destination_account=destination_account,
                    inherited=inherited is not None,
                )
            )
    return tuple(claims)
