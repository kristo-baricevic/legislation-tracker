"""Governing authority for cited dollar amounts in bill text and reader claims."""

import re
from decimal import Decimal

from apps.legislation.extraction.federal_structure import STATUTORY_ABBREVIATION_RE

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
    r"\b(?:allocates|appropriates|disburses|spends|(?:is|are)\s+(?:hereby\s+)?(?:allocated|appropriated|disbursed|spent))\b",
    re.I,
)
_OUTLAY = r"(?:allocate|spend|appropriate|disburse|be\s+(?:allocated|spent|appropriated|disbursed))"
_REQUIRED_OUTLAY = re.compile(rf"\b(?:must|shall|will)\s+{_OUTLAY}\b", re.I)
_FUNDING_PREDICATE = re.compile(
    rf"\b(?:(?:must|shall|will|may)\s+{_OUTLAY}|"
    rf"{_ENACTED_OUTLAY.pattern}|(?:is|are)\s+(?:hereby\s+)?authorized|authorizes)\b",
    re.I,
)

# A second subject and finite verb start a new assertion, including a neutral
# cost estimate. A coordinated amount list still shares its governing verb.
_INDEPENDENT_PREDICATE = re.compile(
    r"^(?:(?:and|but|while|whereas)\s+)?"
    r"(?:(?:the|an?|its|their)\s+[\w-]+(?:\s+(?!(?:that|which|who)\b)[\w-]+)*?|it|CBO)\s+"
    r"\b(?:is|are|was|were|has|have|estimates|projects|forecasts|reports|totals|equals|costs)\b",
    re.I,
)


def _funding_clauses(text):
    """Split coordinated funding decisions, preserving amount lists under one verb."""
    parts = []
    for part in re.split(
        r"(?<=,)\s+|\s+(?=(?:and|but|while|whereas)\b)", text, flags=re.I
    ):
        if parts and (
            _FUNDING_PREDICATE.search(part) or _INDEPENDENT_PREDICATE.match(part)
        ):
            yield " ".join(parts)
            parts = []
        parts.append(part)
    yield " ".join(parts)


_AUTHORIZED_SUM = re.compile(
    rf"(?P<amount>{_DOLLAR})\s+(?:previously\s+)?{_AUTHORIZATION.pattern}", re.I
)
_AUTH_SOURCE = re.compile(
    rf"\b(?:of|from|using)\s+(?:(?:the|any|such)\s+)*"
    rf"(?:{_DOLLAR}|amounts?|funds?|sums?|appropriations?)\s+"
    r"(?:(?:that|which)\s+(?:is|are|was|were)\s+)?"
    rf"(?:previously\s+)?{_AUTHORIZATION.pattern}",
    re.I,
)


# Mark subordinate clauses before splitting coordinated funding decisions.
# Qualifiers inside a condition (amount comparators, subjects, adverbs and
# coordinated verbs) cannot turn its predicate into an independent enactment.
_CONDITION = re.compile(
    r"\b(?:if|unless|whether|when|provided that|on condition that|in the event that)\b",
    re.I,
)
_MAIN_CLAUSE = re.compile(
    rf"(?:,\s+(?=(?:there|Congress|the|an?|this|it|{_DOLLAR})\b)|\bthen\s+)",
    re.I,
)


def _funding_scopes(text):
    start = 0
    for boundary in re.finditer(r"(?<=[.;!?])\s+|$", text):
        end = boundary.start()
        if end < len(text) and STATUTORY_ABBREVIATION_RE.search(
            text[max(start, end - 16) : end]
        ):
            continue
        sentence = text[start:end]
        start = boundary.end()
        while condition := _CONDITION.search(sentence):
            main = sentence[: condition.start()]
            yield main, False
            tail = sentence[condition.end() :]
            # A trailing prerequisite scopes the remainder of this statement,
            # including commas and coordinated verbs inside the prerequisite.
            # A leading condition can instead introduce a separate main clause.
            resume = _MAIN_CLAUSE.search(tail) if not main.strip() else None
            if resume is None:
                yield tail, True
                break
            yield tail[: resume.start()], True
            sentence = tail[resume.end() :]
        else:
            yield sentence, False


def _asserts_outlay(text):
    return bool(_REQUIRED_OUTLAY.search(text) or _ENACTED_OUTLAY.search(text))


def _funding_roles(text):
    """Separate an allocation's amount from the authorized account it draws on."""
    if "$" not in text:
        return
    for scope, conditional in _funding_scopes(text):
        for clause in _funding_clauses(scope):
            source_amounts = {
                amount
                for match in _AUTH_SOURCE.finditer(clause)
                for amount in dollar_amounts(match[0])
            }
            decision = _AUTH_SOURCE.sub(" ", clause)
            outlay = _asserts_outlay(decision)
            if outlay:
                # "$2 million authorized to be appropriated ... shall be allocated"
                # retains its explicit mandate. The authorization modifies that sum.
                decision = _AUTHORIZED_SUM.sub(r"\g<amount>", decision)
            yield (
                decision,
                dollar_amounts(decision),
                source_amounts,
                outlay,
                conditional,
            )


def nonoperative_funding_amounts(texts):
    nonoperative, operative = set(), set()
    for text in texts:
        for decision, amounts, source_amounts, outlay, conditional in _funding_roles(
            text
        ):
            nonoperative.update(source_amounts)
            if (
                (conditional and outlay)
                or _AUTHORIZATION.search(decision)
                or _AUTHORIZES_AMOUNT.search(decision)
            ):
                nonoperative.update(amounts)
            elif outlay:
                # A cost estimate repeating this amount supplies no authority to spend it.
                operative.update(amounts)
    return nonoperative - operative


def asserted_outlays(text):
    return {
        amount
        for _, amounts, _, outlay, conditional in _funding_roles(text)
        if outlay and not conditional
        for amount in amounts
    }


def required_claim_conflicts(claim, amount, nonoperative):
    action = claim.get("action", "")
    return (
        bool(nonoperative)
        and claim.get("modality") == "required"
        and any(
            _asserts_outlay(scope)
            or re.search(r"\b(?:spend|allocate|appropriate|disburse)\b", scope, re.I)
            for scope, conditional in _funding_scopes(action)
            if not conditional
        )
        and bool(dollar_amounts(f"${amount}") & nonoperative)
    )
