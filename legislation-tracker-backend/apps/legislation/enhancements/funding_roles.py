"""Governing authority for cited dollar amounts in bill text and reader claims."""

import re
from decimal import Decimal

_DOLLAR = r"\$\s*([\d,]+(?:\.\d+)?)(?:\s*(thousand|million|billion|trillion)\b)?"


def dollar_amounts(text):
    multipliers = {
        "": 1,
        "thousand": 1000,
        "million": 1000000,
        "billion": 1000000000,
        "trillion": 1000000000000,
    }
    return {
        Decimal(amount.replace(",", "")) * multipliers[magnitude.lower()]
        for amount, magnitude in re.findall(_DOLLAR, text, re.I)
    }


_AUTHORIZATION = re.compile(r"\bauthoriz\w*\s+to\s+be\s+appropriated\b", re.I)
_AUTHORIZES_AMOUNT = re.compile(
    rf"\bauthorizes?\s+(?:the appropriation of\s+)?{_DOLLAR}", re.I
)
_ENACTED_OUTLAY = re.compile(
    r"\b(?:allocates|appropriates|disburses|(?:is|are)\s+(?:hereby\s+)?(?:allocated|appropriated|disbursed))\b",
    re.I,
)
_OUTLAY = r"(?:allocate|spend|appropriate|disburse|be\s+(?:allocated|spent|appropriated|disbursed))"
_REQUIRED_OUTLAY = re.compile(rf"\b(?:must|shall|will)\s+{_OUTLAY}\b", re.I)
_FUNDING_PREDICATE = re.compile(
    rf"\b(?:(?:must|shall|will|may)\s+{_OUTLAY}|"
    r"(?:is|are)\s+(?:hereby\s+)?(?:authorized|appropriated|spent|allocated|disbursed)|"
    r"allocates|spends|appropriates|disburses|authorizes)\b",
    re.I,
)


def _funding_clauses(text):
    """Split coordinated funding decisions, preserving amount lists under one verb."""
    for sentence in re.split(r"(?<=[.;])\s+", text):
        parts = []
        for part in re.split(
            r"(?<=,)\s+|\s+(?=(?:and|but|while|whereas)\b)", sentence, flags=re.I
        ):
            if parts and _FUNDING_PREDICATE.search(part):
                yield " ".join(parts)
                parts = []
            parts.append(part)
        yield " ".join(parts)


_AUTHORIZED_SUM = re.compile(
    rf"(?P<amount>{_DOLLAR})\s+(?:previously\s+)?{_AUTHORIZATION.pattern}", re.I
)
_AUTH_SOURCE = re.compile(
    rf"\b(?:of|from|using)\s+(?:(?:the|any|such)\s+)*"
    rf"(?:(?:{_DOLLAR})\s+)?(?:amounts?|funds?|sums?|appropriations?)?\s*"
    rf"(?:previously\s+)?{_AUTHORIZATION.pattern}",
    re.I,
)


def _funding_roles(text):
    """Separate an allocation's amount from the authorized account it draws on."""
    if "$" not in text:
        return
    for clause in _funding_clauses(text):
        source_amounts = {
            amount
            for match in _AUTH_SOURCE.finditer(clause)
            for amount in dollar_amounts(match[0])
        }
        decision = _AUTH_SOURCE.sub(" ", clause)
        if _REQUIRED_OUTLAY.search(decision):
            # "$2 million authorized to be appropriated ... shall be allocated"
            # retains its explicit mandate. The authorization modifies that sum.
            decision = _AUTHORIZED_SUM.sub(r"\g<amount>", decision)
        yield decision, dollar_amounts(decision), source_amounts


def authorization_only_amounts(texts):
    authorized, operative = set(), set()
    for text in texts:
        for decision, amounts, source_amounts in _funding_roles(text):
            authorized.update(source_amounts)
            if _AUTHORIZATION.search(decision) or _AUTHORIZES_AMOUNT.search(decision):
                authorized.update(amounts)
            elif _REQUIRED_OUTLAY.search(decision) or _ENACTED_OUTLAY.search(decision):
                # A cost estimate repeating this amount supplies no authority to spend it.
                operative.update(amounts)
    return authorized - operative


def mandatory_outlays(text):
    return {
        amount
        for decision, amounts, _ in _funding_roles(text)
        if _REQUIRED_OUTLAY.search(decision)
        for amount in amounts
    }


def required_claim_conflicts(claim, amount, authorization_only):
    return (
        bool(authorization_only)
        and claim.get("modality") == "required"
        and bool(
            re.search(
                r"\b(?:spend|allocate|appropriate|disburse)\b",
                claim.get("action", ""),
                re.I,
            )
        )
        and bool(dollar_amounts(f"${amount}") & authorization_only)
    )
