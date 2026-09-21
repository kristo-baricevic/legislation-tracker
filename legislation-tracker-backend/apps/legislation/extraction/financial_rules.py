"""Deterministic extraction of explicit federal financial provisions."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from itertools import pairwise

from .display_text import normalize_reader_fragment
from .federal_clauses import iter_operative_clauses
from .federal_structure import sentence_spans
from .operative_context import parse_operative_clauses
from .types import ExtractedClaim, SourceSpan, StructuralSection

_ACTION_RE = re.compile(
    r"(?P<authorization>\bauthorized\s+to\s+be\s+appropriated\b)|"
    r"(?P<appropriation>\b(?:there\s+(?:is|are)\s+|(?:is|are)\s+(?:hereby\s+)?)"
    r"appropriated\b)|"
    r"(?P<set_aside>\bset(?:ting)?\s+aside\b|\breserve(?:s|d)?\b)|"
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
    r"(?P<purpose>.+?)(?=;|\.$|$)",
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
    **dict.fromkeys(
        ("fee", "surcharge", "penalty", "fee_exemption", "account_rule"),
        "not_applicable",
    ),
    "appropriation": "increase",
    "authorization": "increase",
    "allocation": "increase",
    "transfer": "neutral_transfer",
    "rescission": "decrease",
    "reduction": "decrease",
    "cancellation": "decrease",
    "set_aside": "limit",
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
    is_minimum: bool = False


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


def _reservation_has_financial_object(before: str, after: str) -> bool:
    tail = after.strip()
    # Bare list introductions inherit their financial amounts from the leaves.
    if not tail.rstrip(":—–-"):
        return True
    tail = re.sub(
        r"^(?:not\s+(?:less|more)\s+than|at\s+least|up\s+to)\s+", "", tail, flags=re.I
    )
    if _MONEY_RE.match(tail) or _PERCENT_RE.match(tail) or _SUCH_SUMS_RE.match(tail):
        return True
    # A fronted purpose can separate the verb from its monetary object:
    # 'reserve, for rural grants, $5 million'.
    object_amount = _MONEY_RE.search(tail) or _PERCENT_RE.search(tail)
    if object_amount and re.fullmatch(
        r",?\s*for\s+[^,;.]+,?\s*", tail[: object_amount.start()], re.I
    ):
        return True
    if re.match(
        r"(?:(?:the|a|an|any|all|some|remaining|available|unobligated|additional|appropriated)\s+)*"
        r"(?:funds?|amounts?|money|appropriations?|balances?|sums?)\b",
        tail,
        re.I,
    ):
        return True
    # Passive monetary subjects: '$5 million is reserved for ...'. An amount
    # elsewhere in a reservation of rights/authority is not the verb's object.
    amounts = tuple(_MONEY_RE.finditer(before)) + tuple(_PERCENT_RE.finditer(before))
    return any(
        re.fullmatch(
            r"\s+(?:(?:shall|must|may)\s+)?(?:is|are|was|were|be)\s+(?:hereby\s+)?",
            before[amount.end() :],
            re.I,
        )
        for amount in amounts
    )


def _actions(text: str) -> tuple[_ActionMatch, ...]:
    actions = []
    for match in _ACTION_RE.finditer(text):
        action = next(name for name, value in match.groupdict().items() if value)
        if action == "set_aside" and match.group().lower().startswith("reserv"):
            # A reservation must be operative, not an agency/account name or
            # a reference to money previously reserved by another provision.
            if not re.search(
                r"\b(?:shall|must|may|to|is|are|be|was|were)\s+(?:(?:also|hereby)\s+)?$",
                text[: match.start()],
                re.I,
            ):
                continue
            if not _reservation_has_financial_object(
                text[: match.start()], text[match.end() :]
            ):
                continue
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
                is_minimum=bool(
                    re.search(
                        r"\b(?:not\s+less\s+than|at\s+least)\s*$",
                        text[: match.start()],
                        re.I,
                    )
                ),
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
                is_minimum=bool(
                    re.search(
                        r"\b(?:not\s+less\s+than|at\s+least)\s*$",
                        text[: match.start()],
                        re.I,
                    )
                ),
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
    # Percentage bases often precede the operative verb and include exclusions.
    base = re.match(
        r"\s*From\s+(.+?),\s+(?:the\s+)?\w+\s+(?:shall|may|must)\b", text, re.I | re.S
    )
    if base and action != "transfer":
        return _strip(base.group(1)), None
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
    # Do not mistake the opening 'appropriated to carry out this Act' for
    # the purpose of a reservation appearing later in the same sentence.
    amounts = _amounts(text)
    if amounts:
        tail = text[amounts[-1].end :]
        explicit = re.search(r"\b(?:for\s+|to\s+(?=award\b))(.+)", tail, re.I | re.S)
        if explicit and not re.match(
            r"(?:(?:a|each(?: of)?)(?: the)?\s+)?fiscal years?", explicit.group(1), re.I
        ):
            return _strip(explicit.group(1)) or None
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
        preceding_sentences = (
            sentence
            for sentence in sentence_spans(parent, source_text)
            if sentence.end_char <= section.span.start_char
        )
        for sentence in reversed(tuple(preceding_sentences)):
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
    financial_noun = re.search(
        r"\b(?:amounts?|funds?|funding|appropriations?|budget\s+authority|"
        r"unobligated\s+balances?|accounts?)\b",
        text,
        re.IGNORECASE,
    )
    if financial_noun is None:
        return False
    return (
        re.search(
            r"(?:"
            r"\bpercent\s+of\s+(?:the\s+)?(?:amounts?|funds?|funding|"
            r"appropriations?|budget\s+authority|unobligated\s+balances?|accounts?)\b|"
            r"\b(?:set\s+aside|reserve|allocate|transfer|reduce|rescind|cancel)\b"
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
        amount_is_minimum=amount.is_minimum,
    )


def extract_financial_claims(
    source_text: str, sections: Sequence[StructuralSection], clauses=None
) -> tuple[ExtractedClaim, ...]:
    """Return every explicitly supported financial provision in source order."""

    claims = list(_payment_claims(source_text, sections, clauses))
    payment_spans = [claim.fields["_payment_span"] for claim in claims]
    payment_offsets = {
        claim.fields["_amount_span"]
        for claim in claims
        if claim.fields.get("_amount_span")
    }
    for section, span, _ in iter_operative_clauses(
        source_text, sections, date_aware=True
    ):
        payment_sentence = any(
            start <= span.start_char and span.end_char <= end
            for start, end in payment_spans
        )
        actions = _actions(span.text)
        # A payment/account sentence can also contain a distinct appropriation.
        # Suppress only payment-owned amounts, not the entire sentence.
        if payment_sentence and not any(a.action != "limitation" for a in actions):
            continue
        candidate_amounts = _amounts(span.text)
        if payment_sentence:
            candidate_amounts = tuple(
                a
                for a in candidate_amounts
                if (span.start_char + a.start, span.start_char + a.end)
                not in payment_offsets
            )
        if not candidate_amounts:
            continue
        inherited = (
            _inherited_context(source_text, section, sections)
            if (
                not actions
                or (
                    any(
                        amount.amount_type == "percentage"
                        for amount in candidate_amounts
                    )
                    and all(action.action == "limitation" for action in actions)
                )
            )
            else None
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
            or (
                inherited is not None
                and inherited.action == "set_aside"
                and re.search(
                    r"\b(?:amounts?|funds?|appropriations?)\b",
                    inherited.evidence.text,
                    re.I,
                )
                and re.match(
                    r"\s*(?:not\s+(?:more|less)\s+than\s+|up\s+to\s+|at\s+least\s+)?\d+(?:\.\d+)?\s+percent\s+for\b",
                    span.text,
                    re.I,
                )
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
            purpose = _purpose(local_text, action)
            if purpose and re.fullmatch(r"carry out this section", purpose, re.I):
                owner = next(
                    (
                        s
                        for s in sections
                        if s.level == "section"
                        and s.span.start_char <= span.start_char < s.span.end_char
                    ),
                    None,
                )
                if owner and owner.heading:
                    purpose = owner.heading
                    heading_end = source_text.find("\n", owner.span.start_char)
                    if heading_end >= 0:
                        evidence = (
                            *evidence,
                            SourceSpan(
                                source_text[owner.span.start_char : heading_end],
                                owner.span.start_char,
                                heading_end,
                            ),
                        )
            claims.append(
                _claim(
                    section=section,
                    evidence=evidence,
                    action=action,
                    amount=amount,
                    fiscal_years=fiscal_years,
                    purpose=purpose,
                    source_account=source_account,
                    destination_account=destination_account,
                    inherited=inherited is not None,
                )
            )
    return tuple(
        replace(
            claim,
            fields={
                key: value
                for key, value in claim.fields.items()
                if key not in {"_amount_span", "_payment_span"}
            },
        )
        for claim in sorted(
            claims,
            key=lambda c: (
                c.fields.get("_amount_span") or (c.evidence[-1].start_char,)
            )[0],
        )
    )


def _payment_amounts(text, action):
    noun = {"fee": r"fees?", "surcharge": r"surcharge", "penalty": r"fined"}[action]
    anchors = list(re.finditer(r"\b" + noun + r"\b", text, re.I))
    owned = None
    payment_nouns = list(re.finditer(r"\b(?:fees?|surcharge|fined)\b", text, re.I))
    for amount in _amounts(text):
        if amount.amount is None:
            continue
        before = [anchor for anchor in anchors if anchor.end() <= amount.start]
        bridge = text[before[-1].end() : amount.start] if before else None
        preceding_payment = [m for m in payment_nouns if m.end() <= amount.start]
        prefixed = action == "fee" and re.match(
            r"\s+(?:(?:application|processing)\s+)?fee\b", text[amount.end :], re.I
        )
        if (
            not prefixed
            and preceding_payment
            and not re.fullmatch(noun, preceding_payment[-1].group(), re.I)
        ):
            owned = None
            continue
        direct = bridge is not None and re.fullmatch(
            r"\s*(?:(?:of|equal to|in (?:the|an) amount of)\s*)?"
            r"(?:[—:–]\s*\([a-z0-9]+\)\s*)?"
            r"(?:(?:not more than|not less than|not to exceed|at least|up to)\s+)?",
            bridge,
            re.I,
        )
        # Cost-based fees often state a cap later in the same clause.
        cap = (
            bridge is not None
            and not _amounts(bridge)
            and not re.search(
                r"\b(?:if|when|income|assets|salary|earnings|appropriated)\b",
                bridge,
                re.I,
            )
            and re.search(
                r"\b(?:does not exceed|shall not exceed|must not exceed|not more than|not to exceed|up to)\s*$",
                bridge,
                re.I,
            )
        )
        prefixed = action == "fee" and re.match(
            r"\s+(?:(?:application|processing)\s+)?fee\b", text[amount.end :], re.I
        )
        continuation = False
        if owned is not None:
            between = text[owned.end : amount.start]
            # Fiscal qualifiers may precede or follow a schedule price. They
            # belong to that price, not to the payment-noun continuation grammar.
            between = re.sub(
                r"\bfor\s+fiscal\s+years?\s+\d{4}(?:\s+(?:through|to|-)\s+\d{4})?\s*,?",
                "",
                between,
                flags=re.I,
            )
            # A coordinated price or the next enumerated price inherits the
            # payment noun, but an income/eligibility threshold does not.
            continuation = bool(
                re.fullmatch(
                    r"\s*(?:for\s+(?:(?!\b(?:if|income|assets|salary|earnings|when)\b).)+?)?"
                    r"\s*(?:;?\s*(?:and|or)\s*,?\s*|;?\s*(?:(?:and|or)\s*)?\n\s*\([a-z0-9]+\)\s*)"
                    r"(?:(?:not more than|not less than|at least|up to)\s+)?",
                    between,
                    re.I | re.S,
                )
            )
        if direct or cap or prefixed or continuation:
            owned = amount
            yield amount


def _payment_actions(text):
    text = re.sub(r"\s+", " ", text)
    actions = []
    if re.search(
        r"\b(?:may|shall|must) be exempted from paying\b.*\bfee\b", text, re.I | re.S
    ):
        actions.append("fee_exemption")
    if re.search(
        r"\bsurcharge\b.*\b(?:shall|must) be (?:imposed|collected)\b", text, re.I | re.S
    ) or re.search(
        r"\b(?:shall|must|may)\b.*\b(?:impose|collect|pay)\s+(?:an?\s+)?(?:additional\s+)?surcharge\b",
        text,
        re.I | re.S,
    ):
        actions.append("surcharge")
    if re.search(r"\b(?:shall|must|may) be fined\b", text, re.I):
        actions.append("penalty")
    if re.search(
        r"\b(?:shall|may|must)\b.*\b(?:pay|require|include a requirement)\b.*\bfee\b",
        text,
        re.I | re.S,
    ):
        actions.append("fee")
    if re.search(
        r"\b(?:fees|amounts|funds)\b.*\bshall (?:be deposited|remain available)\b",
        text,
        re.I | re.S,
    ):
        actions.append("account_rule")
    return actions


def _payment_claims(source, sections, clauses=None):
    clauses = (
        clauses if clauses is not None else parse_operative_clauses(source, sections)
    )
    for clause in clauses:
        if not clause.asserted:
            continue
        span, section = clause.span, clause.section
        children = [child for child in clauses if span in child.context]
        actions = _payment_actions(span.text)
        inherited = False
        if not actions and clause.context and clause.modality:
            # Only bare list prices inherit a parent's payment action.
            if re.match(
                r"\s*(?:(?:not\s+(?:more|less)\s+than|not\s+to\s+exceed|at\s+least|up\s+to)\s+)?(?:\$|[0-9]+(?:\.[0-9]+)?\s+percent)",
                span.text,
                re.I,
            ):
                actions = _payment_actions(clause.context[-1].text)
                inherited = True
        for action in actions:
            if (
                action in {"fee", "surcharge", "penalty"}
                and children
                and not tuple(_payment_amounts(span.text, action))
            ):
                continue
            evidence = clause.evidence
            if children and (
                action == "fee_exemption" or action in {"fee", "surcharge", "penalty"}
            ):
                # Eligibility alternatives are context for one exemption.
                end = max(c.span.end_char for c in children)
                evidence = (
                    *clause.evidence_context,
                    SourceSpan(source[span.start_char : end], span.start_char, end),
                )
            yield from _payment_records(
                source,
                sections,
                section,
                span,
                action,
                evidence,
                inherited,
                governing_sentence=clause.sentence,
                owned_end=max([span.end_char, *(c.span.end_char for c in children)]),
            )


def _payment_subclauses(text, amounts):
    """Keep a coordinated price's leading and trailing qualifiers together."""
    boundaries = [0]
    for previous, current in pairwise(amounts):
        between = text[previous.end : current.start]
        connectors = list(
            re.finditer(r"\b(?:and|or)\b\s*,?\s*|\n\s*\([a-z0-9]+\)\s*", between, re.I)
        )
        boundaries.append(
            previous.end + connectors[-1].end() if connectors else current.start
        )
    boundaries.append(len(text))
    return [text[start:end] for start, end in pairwise(boundaries)]


def _payment_records(
    source,
    sections,
    section,
    span,
    action,
    evidence,
    inherited=False,
    governing_sentence=None,
    owned_end=None,
):
    text = span.text
    prefix = (
        {"fee": "fee of ", "surcharge": "surcharge of ", "penalty": "fined "}.get(
            action, ""
        )
        if inherited
        else ""
    )
    amounts = (
        tuple(
            replace(a, start=a.start - len(prefix), end=a.end - len(prefix))
            for a in _payment_amounts(prefix + text, action)
        )
        if action in {"fee", "surcharge", "penalty"}
        else ()
    )
    if not amounts:
        amounts = (_AmountMatch(None, "unspecified", None, 0, 0),)
    # Only a leading year governs the whole schedule. Trailing years belong
    # to the individual price, not every amount in this sentence.
    fiscal_years = _fiscal_years(text[: amounts[0].start])
    if not fiscal_years and governing_sentence is not None:
        governing_amounts = _amounts(governing_sentence.text)
        if governing_amounts:
            fiscal_years = _fiscal_years(
                governing_sentence.text[: governing_amounts[0].start]
            )
    parent = _parent_section(section, sections)
    while not fiscal_years and parent is not None:
        # Only inherit an explicit list introduction governing this child.
        introductions = sentence_spans(parent, source)
        if introductions and introductions[-1].text.rstrip().endswith((":", "—", "–")):
            fiscal_years = _fiscal_years(introductions[-1].text)
        parent = _parent_section(parent, sections)
    for amount, local_text in zip(
        amounts, _payment_subclauses(text, amounts), strict=True
    ):
        amount_years = _fiscal_years(local_text) or fiscal_years
        ceiling = amount.amount is not None and bool(
            re.search(
                r"\b(?:does\s+not\s+exceed|not\s+more\s+than|not\s+to\s+exceed|shall\s+not\s+exceed|must\s+not\s+exceed|up\s+to)\s*$",
                text[: amount.start],
                re.I,
            )
        )
        fields = {
            "financial_action": action,
            "direction": "not_applicable",
            "amount": amount.amount,
            "amount_type": "ceiling" if ceiling else amount.amount_type,
            "currency": amount.currency,
            "fiscal_years": list(amount_years),
            "purpose": None,
            "source_account": None,
            "destination_account": None,
            "_payment_span": (span.start_char, owned_end or span.end_char),
            "_amount_span": (
                span.start_char + amount.start,
                span.start_char + amount.end,
            )
            if amount.amount is not None
            else None,
        }
        yield ExtractedClaim(
            "financial_items",
            fields,
            section.label,
            evidence,
            f"financial.{action}.v1",
            section.source_id,
            section.source_id,
            section.path,
        )
