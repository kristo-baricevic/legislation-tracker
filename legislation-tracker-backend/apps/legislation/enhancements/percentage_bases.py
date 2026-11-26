"""Conservative bindings between explicit percentages and appropriations accounts."""

import re
from decimal import Decimal, InvalidOperation

_PERCENTAGE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(?:%|percent\b)", re.I)
# Accept an explicit appropriations account or an elided "of the remainder".
# Stop before the purpose, where another rate or a different account can appear.
_ACCOUNT = r"(?:appropriations?|(?:amounts?|sums?|funds?)\s+appropriated)"
_BASIS = r"(?:total|entire|full|remaining|remainder)"
_DIRECT_BASE = re.compile(
    rf"\s+of\s+(?:the\s+)?(?P<base>"
    rf"(?:{_BASIS}\s+(?:of\s+(?:the\s+)?)?)?(?:annual\s+)?{_ACCOUNT}"
    rf"(?:\s+(?:remaining|not reserved|after (?:the |any )?(?:set[ -]aside|reservation)))?"
    rf"|{_BASIS}(?=\s*(?:$|[,.;]|\b(?:and|or|for|to)\b)))\b",
    re.I,
)
_OF = re.compile(r"\s+of\b", re.I)
_FRONTED_BASE = re.compile(r"(?:^|[—,:]|\b(?:and|but))\s*(?:of|from)\s+([^,;]+),", re.I)


def percentages(text):
    return {Decimal(m[1].replace(",", "")) for m in _PERCENTAGE.finditer(text)}


def appropriation_base(text):
    """Classify one basis phrase, including H.R.9300's post-reservation wording."""
    # A standalone shorthand can refer back to the appropriations account.
    # A named, unrelated denominator (e.g. "total enrollment") cannot.
    if not re.search(_ACCOUNT, text, re.I) and not re.fullmatch(
        rf"(?:the\s+)?{_BASIS}(?:\s+(?:amounts?|funds?))?", text.strip(), re.I
    ):
        return None
    if re.search(
        rf"^(?:the\s+)?(?:remaining|remainder)\b|{_ACCOUNT}\s+remaining\b|"
        r"\b(?:not reserved|after (?:the |any )?(?:set[ -]aside|reservation))\b",
        text,
        re.I,
    ):
        return "remaining"
    if re.search(r"\b(?:total|entire|full)\b", text, re.I):
        return "total"
    return None


def percentage_bases(text):
    """Attach an explicit rate to its own account in either legislative word order."""
    for clause in re.split(r"(?<=[.;])\s+", text):
        end = 0
        governing = None
        for rate in _PERCENTAGE.finditer(clause):
            # "From the total amount appropriated ... and not reserved ..., reserve 20%".
            for fronted in _FRONTED_BASE.finditer(clause, end, rate.start()):
                governing = appropriation_base(fronted[1])
            end = rate.end()
            direct = _DIRECT_BASE.match(clause, end)
            if direct:
                basis = appropriation_base(direct["base"])
            elif _OF.match(clause, end):
                # An explicit different denominator overrides a fronted account.
                basis = None
            else:
                basis = governing
            if basis:
                yield Decimal(rate[1].replace(",", "")), basis


def cited_percentage_bases(texts):
    result = {}
    for text in texts:
        for rate, basis in percentage_bases(text):
            result.setdefault(rate, set()).add(basis)
    return result


def percentage_base_conflicts(amount, base, cited):
    try:
        rate = Decimal(str(amount).replace(",", ""))
    except InvalidOperation:
        return False
    if not rate.is_finite():
        return False
    expected = cited.get(rate, set())
    return len(expected) == 1 and appropriation_base(base or "") not in expected
