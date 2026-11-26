"""Governing authority for cited dollar amounts in bill text and reader claims."""

import re
from dataclasses import dataclass
from decimal import Decimal

from apps.legislation.extraction.federal_structure import STATUTORY_ABBREVIATION_RE

_DOLLAR = r"\$\s*(\d[\d,]*(?:\.\d+)?)(?:\s*(thousand|million|billion|trillion)\b)?"


def malformed_dollar_amount(text):
    return bool(re.search(r"\$\s*,", text))


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
_ENACTED_APPROPRIATION = re.compile(
    r"\b(?:appropriates|(?:is|are)\s+(?:hereby\s+)?appropriated)\b", re.I
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
        if (
            parts
            and (_FUNDING_PREDICATE.search(part) or _INDEPENDENT_PREDICATE.match(part))
            and not (
                len(parts) == 1 and re.fullmatch(r"\s*for\s+[^$,;]+,", parts[0], re.I)
            )
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
    r"\b(?:only if|if|unless|whether|when|provided that|on condition that|in the event that)\b",
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
        prerequisites = set()
        while condition := _CONDITION.search(sentence):
            main = sentence[: condition.start()]
            tail = sentence[condition.end() :]
            resume = _MAIN_CLAUSE.search(tail) if not main.strip() else None
            end = condition.end() + resume.start() if resume else len(sentence)
            prerequisites.add(_condition_key(sentence[condition.start() : end]))
            # A funding predicate in the prerequisite supplies no spending authority.
            yield sentence[condition.end() : end], frozenset(), True
            sentence = tail[resume.end() :] if resume else main
        yield sentence, frozenset(prerequisites), False


def _condition_key(text):
    # Preserve polarity, conjunctions, comparators and decimals when matching
    # conditions. Unknown paraphrases cannot discharge a source prerequisite.
    return " ".join(text.casefold().strip().rstrip(".,;:!?").split())


def _words(text):
    return " ".join(re.findall(r"[\w$]+", (text or "").casefold()))


def _asserts_outlay(text):
    return bool(_REQUIRED_OUTLAY.search(text) or _ENACTED_OUTLAY.search(text))


@dataclass(frozen=True)
class FundingDecision:
    amount: Decimal
    purpose: str
    authority: str
    prerequisites: frozenset[str]
    wording: str


def _purpose(text):
    match = re.search(r"\bfor\s+(.+)", text, re.I | re.S)
    if not match:
        match = re.search(
            r"\bto\s+(?=(?:fund|pay for|cover|finance|support)\b)(.+)",
            text,
            re.I | re.S,
        )
    if not match or re.match(
        r"(?:each of (?:the )?|the )?(?:fiscal |calendar )?years?\b", match[1], re.I
    ):
        return ""
    # Keep the named object. Dates and legal references qualify the clause but
    # cannot distinguish two projects using the same amount.
    purpose = re.split(
        r"[,;.]|\b(?:under section|in fiscal year|for fiscal year|and \$)\b",
        match[1],
        maxsplit=1,
        flags=re.I,
    )[0]
    return _words(re.sub(r"\s+and\s*$", "", purpose, flags=re.I))


def _amount_purpose(clause, match, end):
    # The purpose can follow the sum, precede the spending verb, or appear
    # between verb and sum ("appropriates for salaries the sum of $100").
    after = _purpose(clause[match.end() : end])
    if after:
        return after
    prefix = clause[: match.start()]
    front = re.match(r"\s*for\s+([^,$]+),", prefix, re.I)
    if front:
        return _purpose(front[0])
    before = re.search(
        r"\bfor\s+([^,$]+?)\s+(?:(?:the|an?)\s+(?:sum|amount|total)\s+of\s*)?$",
        prefix,
        re.I,
    )
    return _purpose("for " + before[1]) if before else ""


def _outlay_authority(text):
    if _ENACTED_APPROPRIATION.search(text):
        return "appropriated"
    if re.search(
        r"\b(?:must|shall|will)\s+(?:appropriate|be appropriated)\b|^\s*(?:to\s+)?appropriate\b",
        text,
        re.I,
    ):
        return "obligation to appropriate"
    return "outlay"


_NEGATIVE_SUBJECT = re.compile(
    r"\b(?:no\s+(?:(?:such|federal|additional|public)\s+)*(?:funds?|money|amounts?|sums?|part|portion)|none)\b"
    r"[^.;!?]*?\b(?:is|are|may|must|shall|will)\s+(?:(?:hereby|be)\s+)*(?:appropriated|allocated|disbursed|spent)\b",
    re.I,
)


def _clause_decisions(clause, prerequisites, subordinate):
    for source in _AUTH_SOURCE.finditer(clause):
        for amount in dollar_amounts(source[0]):
            yield FundingDecision(
                amount, "", "nonoperative", frozenset(), _words(source[0])
            )
    decision = _AUTH_SOURCE.sub(" ", clause)
    outlay = _asserts_outlay(decision)
    if outlay:
        decision = _AUTHORIZED_SUM.sub(r"\g<amount>", decision)
    authorized = _AUTHORIZATION.search(decision) or _AUTHORIZES_AMOUNT.search(decision)
    authority = "nonoperative"
    if outlay and not (authorized or subordinate or _NEGATIVE_SUBJECT.search(decision)):
        authority = _outlay_authority(decision)
    wording = _words(clause)
    matches = list(re.finditer(_DOLLAR, decision, re.I))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(decision)
        (amount,) = dollar_amounts(match[0])
        yield FundingDecision(
            amount,
            _amount_purpose(decision, match, end),
            authority,
            prerequisites,
            wording,
        )


def funding_decisions(texts):
    return [
        rule
        for text in texts
        if "$" in text
        for scope, prerequisites, subordinate in _funding_scopes(text)
        for clause in _funding_clauses(scope)
        for rule in _clause_decisions(clause, prerequisites, subordinate)
    ]


def _unsupported(amount, purpose, authority, prerequisites, wording, cited):
    candidates = [rule for rule in cited if rule.amount == amount]
    if not candidates:
        return True
    named = {rule.purpose for rule in candidates if rule.purpose}
    restricted = any(
        rule.authority == "nonoperative" or rule.prerequisites for rule in candidates
    )
    if not purpose and len(named) > 1:
        return True
    for decision in candidates:
        if (
            decision.authority == "nonoperative"
            or not decision.prerequisites <= prerequisites
        ):
            continue
        if authority == "appropriated" and decision.authority != "appropriated":
            continue
        if authority == "obligation to appropriate" and decision.authority == "outlay":
            continue
        if purpose and decision.purpose and decision.purpose != purpose:
            continue
        if not decision.purpose:
            if purpose:
                # Even a verbatim action cannot establish a separate typed
                # purpose absent from the citation.
                if (
                    wording != decision.wording
                    or f" {purpose} " not in f" {decision.wording} "
                ):
                    continue
            elif (
                restricted
                and not decision.prerequisites
                and wording != decision.wording
            ):
                # Unknown accounts with competing decisions stay unresolved.
                continue
        return False
    return True


def funding_statement_conflicts(text, cited, prerequisites=frozenset()):
    return "$" in text and any(
        d.authority != "nonoperative"
        and _unsupported(
            d.amount,
            d.purpose,
            d.authority,
            prerequisites | d.prerequisites,
            d.wording,
            cited,
        )
        for d in funding_decisions([text])
    )


def claim_prerequisites(condition):
    if not condition:
        return set()
    if condition["operator"] == "leaf":
        return {_condition_key(condition["text"])}
    children = [claim_prerequisites(child) for child in condition["children"]]
    if not children:
        return set()
    # A prerequisite within an alternative only governs if every branch requires it.
    return (
        set.union(*children)
        if condition["operator"] == "all"
        else set.intersection(*children)
    )


def required_claim_conflicts(claim, money, cited):
    if claim.get("modality") != "required":
        return False
    action = claim.get("action", "")
    prerequisites = claim_prerequisites(claim.get("conditions"))
    for scope, prerequisite, subordinate in _funding_scopes(action):
        if subordinate or not (
            _asserts_outlay(scope)
            or re.search(r"\b(?:spend|allocate|appropriate|disburse)\b", scope, re.I)
        ):
            continue
        purposes = {_words(money.get("purpose")), _purpose(scope)} - {""}
        if any(
            _unsupported(
                amount,
                purpose,
                _outlay_authority(scope),
                prerequisites | prerequisite,
                _words(scope),
                cited,
            )
            for purpose in purposes or {""}
            for amount in dollar_amounts(f"${money['amount']}")
        ):
            return True
    return False
