"""Governing authority for cited dollar amounts in bill text and reader claims."""

import re
from dataclasses import dataclass
from decimal import Decimal

from apps.legislation.extraction.federal_structure import STATUTORY_ABBREVIATION_RE

_DOLLAR = r"\$\s*(\d[\d,]*(?:\.\d+)?)(?:\s*(thousand|million|billion|trillion)\b)?"

_NUMBER_WITH_SCALE = (
    r"\d[\d,]*(?:\.\d+)?(?:\s+(?:thousand|million|billion|trillion)\b)?"
)
_NAMED_DOLLARS = re.compile(
    rf"\bUSD\s+(?P<prefix>{_NUMBER_WITH_SCALE})|"
    rf"(?<![\w$.,])(?P<suffix>{_NUMBER_WITH_SCALE})\s+(?:dollars?|USD)\b",
    re.I,
)


def _currency_text(text):
    """Read USD 100 and 100 dollars through the same rules as $100."""
    return _NAMED_DOLLARS.sub(
        lambda match: "$" + (match["prefix"] or match["suffix"]), text
    )


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
        for amount, magnitude in re.findall(_DOLLAR, _currency_text(text), re.I)
    }


# Bind a qualifier to its own dollar token. In particular, the next
# amount's comparator must never qualify the preceding purpose.
_COMPARATORS = {
    "ceiling": (
        "not more than",
        "no more than",
        "not to exceed",
        "not exceeding",
        "at most",
        "up to",
        "maximum of",
        "a maximum of",
        "maximum",
        "ceiling",
        "<=",
        "≤",
    ),
    "floor": (
        "not less than",
        "no less than",
        "at least",
        "minimum of",
        "a minimum of",
        "minimum",
        "floor",
        ">=",
        "≥",
    ),
    "exclusive ceiling": ("less than", "under", "<"),
    "exclusive floor": ("more than", "over", ">"),
    "approximate": ("approximately", "about"),
    "exact": ("exactly", "equal to", "exact", "="),
}
_BOUND_NAMES = {
    phrase: bound for bound, phrases in _COMPARATORS.items() for phrase in phrases
}
_BOUND_PATTERN = "|".join(
    re.escape(phrase) for phrase in sorted(_BOUND_NAMES, key=len, reverse=True)
)
_BOUND_PREFIX = re.compile(rf"(?<!\w)({_BOUND_PATTERN})\s*$", re.I)
_BOUND_SUFFIX = re.compile(r"^\s*(or less|or more|at most|at least|exactly)\b", re.I)


def _amount_comparator(prefix, suffix):
    if match := _BOUND_PREFIX.search(prefix):
        return _BOUND_NAMES[match[1].casefold()]
    if match := _BOUND_SUFFIX.match(suffix):
        phrase = match[1].casefold()
        return {"or less": "ceiling", "or more": "floor"}.get(phrase) or _BOUND_NAMES[
            phrase
        ]
    return "exact"


# An explicitly named monetary object can assert spending authority even when
# a reader omits the figure. A duty to provide guidance is a different claim.
_MONEY_NOUN = r"(?:(?:the|such|these|those|federal|additional|available|appropriated|grant|public)\s+)*(?:funds|funding|money|sums)\b"
_UNQUANTIFIED_MONEY = re.compile(
    rf"\b(?:authorizes?|appropriates?|provides?|allocates?|disburses?|spends?|pays?|obligates?)\s+{_MONEY_NOUN}|"
    rf"\b(?:is|are|be)\s+(?:hereby\s+)?(?:appropriated|provided|allocated|spent|paid|obligated|disbursed)\s+{_MONEY_NOUN}|"
    rf"\b{_MONEY_NOUN}\s+(?:is|are|must be|shall be)\s+(?:hereby\s+)?(?:authorized|appropriated|provided|made available|allocated|spent|paid|obligated|disbursed)\b",
    re.I,
)


_AUTHORIZATION = re.compile(r"\bauthoriz\w*\s+to\s+be\s+appropriated\b", re.I)
_AUTHORIZES_AMOUNT = re.compile(
    rf"\bauthorizes?\s+(?:the appropriation of\s+)?(?:(?:{_BOUND_PATTERN})\s+)?{_DOLLAR}",
    re.I,
)
_ENACTED_APPROPRIATION = re.compile(
    r"\b(?:appropriates|(?:is|are)\s+(?:hereby\s+)?appropriated)\b", re.I
)
_ENACTED_OUTLAY = re.compile(
    r"\b(?:allocates|appropriates|disburses|spends|pays|obligates|(?:is|are)\s+(?:hereby\s+)?(?:allocated|appropriated|disbursed|spent|paid|obligated))\b",
    re.I,
)
_PROVIDED = re.compile(
    rf"\b(?:provides|funds)\s+(?:(?:an?\s+)?(?:total|sum|amount)\s+of\s+|an?\s+)?(?:(?:{_BOUND_PATTERN})\s+)?(?:{_DOLLAR}|{_MONEY_NOUN}|an? amount\b)|"
    r"\b(?:is|are)\s+(?:hereby\s+)?(?:provided|made available)\b|"
    r"\bmakes\s+(?:available\b|[^.;!?]*?\bavailable\b)",
    re.I,
)
_OUTLAY = r"(?:allocate|spend|appropriate|disburse|pay|obligate|provide|be\s+(?:allocated|spent|appropriated|disbursed|paid|obligated|provided))"
_REQUIRED_OUTLAY = re.compile(rf"\b(?:must|shall|will)\s+(?:both\s+)?{_OUTLAY}\b", re.I)
_FUNDING_PREDICATE = re.compile(
    rf"\b(?:(?:must|shall|will|may)\s+(?:both\s+)?{_OUTLAY}|"
    rf"{_ENACTED_OUTLAY.pattern}|{_PROVIDED.pattern}|(?:is|are)\s+(?:hereby\s+)?authorized|authorizes)\b",
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


def _independent_prefix(text):
    """Split off earlier decisions that have a different grammatical subject."""
    clauses = list(_funding_clauses(text))
    for index in range(len(clauses) - 1, 0, -1):
        clause = clauses[index]
        predicate = _FUNDING_PREDICATE.search(clause)
        if (
            predicate
            and re.match(
                r"^(?:(?:and|but|while|whereas)\s+)?(?:the|an?|this|Congress|it|there)\b",
                clause[: predicate.start()],
                re.I,
            )
            and any(_FUNDING_PREDICATE.search(prior) for prior in clauses[:index])
        ):
            return " ".join(clauses[:index]), " ".join(clauses[index:])
    return "", text


def funding_scopes(text):
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
            if main.strip():
                prefix, main = _independent_prefix(main)
                if prefix:
                    yield prefix, frozenset(prerequisites), False
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
    return bool(
        _REQUIRED_OUTLAY.search(text)
        or _ENACTED_OUTLAY.search(text)
        or _PROVIDED.search(text)
    )


@dataclass(frozen=True)
class FundingDecision:
    amount: Decimal | None
    purpose: str
    authority: str
    prerequisites: frozenset[str]
    wording: str
    comparator: str = "exact"


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
    return _words(
        re.sub(
            r"\s+and(?:\s+(?:also\s+)?(?:spend|allocate|disburse|appropriate))?\s*$",
            "",
            purpose,
            flags=re.I,
        )
    )


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
    if re.search(r"\b(?:must|shall|will)\s+(?:provide|be provided)\b", text, re.I):
        return "mandatory provision"
    if _PROVIDED.search(text):
        return "provided"
    if _REQUIRED_OUTLAY.search(text):
        return "mandatory outlay"
    return "outlay"


_NEGATIVE_SUBJECT = re.compile(
    r"\b(?:no\s+(?:(?:such|federal|additional|public)\s+)*(?:funds?|money|amounts?|sums?|part|portion)|none)\b"
    r"[^.;!?]*?\b(?:is|are|may|must|shall|will)\s+(?:(?:hereby|be)\s+)*(?:authorized|appropriated|allocated|disbursed|spent|provided|paid|obligated|made available)\b",
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
    authorized = (
        _AUTHORIZATION.search(decision)
        or _AUTHORIZES_AMOUNT.search(decision)
        or re.search(rf"\bauthorizes?\s+{_MONEY_NOUN}", decision, re.I)
    )
    authority = "nonoperative"
    negated = _NEGATIVE_SUBJECT.search(decision) or re.search(
        r"\b(?:not|never)\s+(?:hereby\s+)?authoriz", decision, re.I
    )
    if not subordinate and not negated:
        if authorized:
            authority = "authorization"
        elif outlay:
            authority = _outlay_authority(decision)
    wording = _words(clause)
    matches = list(re.finditer(_DOLLAR, decision, re.I))
    if (
        not matches
        and authority != "nonoperative"
        and _UNQUANTIFIED_MONEY.search(decision)
    ):
        yield FundingDecision(
            None, _purpose(decision), authority, prerequisites, wording
        )
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(decision)
        comparator = _amount_comparator(
            decision[: match.start()], decision[match.end() : end]
        )
        if index + 1 < len(matches):
            following = _BOUND_PREFIX.search(decision, match.end(), end)
            if following:
                end = following.start()
        (amount,) = dollar_amounts(match[0])
        yield FundingDecision(
            amount,
            _amount_purpose(decision, match, end),
            authority,
            prerequisites,
            wording,
            comparator,
        )


def funding_decisions(texts):
    return [
        rule
        for text in map(_currency_text, texts)
        if "$" in text or _UNQUANTIFIED_MONEY.search(text)
        for scope, prerequisites, subordinate in funding_scopes(text)
        for clause in _funding_clauses(scope)
        for rule in _clause_decisions(clause, prerequisites, subordinate)
    ]


# An appropriation supplies funds. A requirement to spend them needs its
# own operative predicate, even when both decisions have the same amount.
_SUPPORTED_AUTHORITIES = {
    "authorization": {"authorization"},
    "appropriated": {"appropriated"},
    "provided": {"provided", "appropriated", "mandatory provision"},
    "mandatory provision": {"mandatory provision"},
    "obligation to appropriate": {"obligation to appropriate"},
    "mandatory outlay": {"mandatory outlay", "mandatory provision"},
    "outlay": {"outlay", "mandatory outlay"},
}


def _unsupported(amount, purpose, authority, comparator, prerequisites, wording, cited):
    candidates = [rule for rule in cited if amount is None or rule.amount == amount]
    if not candidates:
        return True
    named = {rule.purpose for rule in candidates if rule.purpose}
    restricted = len({(rule.authority, rule.prerequisites) for rule in candidates}) > 1
    if not purpose and len(named) > 1:
        return True
    for decision in candidates:
        if (
            decision.authority == "nonoperative"
            or decision.prerequisites != prerequisites
        ):
            continue
        if (
            decision.authority not in _SUPPORTED_AUTHORITIES[authority]
            or decision.comparator != comparator
        ):
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
    return any(
        d.authority != "nonoperative"
        and _unsupported(
            d.amount,
            d.purpose,
            d.authority,
            d.comparator,
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
    if condition["operator"] == "all":
        return set.union(*children)
    common = set.intersection(*children)
    # Alternatives without an equivalent common branch cannot be verified
    # against an unqualified claim simply because their intersection is empty.
    return common if common in children else {None}


def required_claim_conflicts(claim, money, cited):
    action = claim.get("action", "")
    prerequisites = claim_prerequisites(claim.get("conditions"))
    for scope, prerequisite, subordinate in funding_scopes(action):
        if subordinate:
            continue
        if claim.get("modality") in {"required", "permitted"} and re.match(
            r"\s*authorize\b", scope, re.I
        ):
            authority = "authorization"
        elif claim.get("modality") == "required" and (
            _asserts_outlay(scope)
            or re.search(
                r"\b(?:spend|allocate|appropriate|disburse|pay|obligate|provide)\b",
                scope,
                re.I,
            )
        ):
            authority = _outlay_authority(scope)
            if authority == "outlay" and not _ENACTED_OUTLAY.search(scope):
                authority = "mandatory outlay"
        else:
            continue
        purposes = {_words(money.get("purpose")), _purpose(scope)} - {""}
        if any(
            _unsupported(
                amount,
                purpose,
                authority,
                _BOUND_NAMES.get(
                    (money.get("comparator") or "exact").strip().casefold(), "unknown"
                ),
                prerequisites | prerequisite,
                _words(scope),
                cited,
            )
            for purpose in purposes or {""}
            for amount in dollar_amounts(f"${money['amount']}")
        ):
            return True
    return False
