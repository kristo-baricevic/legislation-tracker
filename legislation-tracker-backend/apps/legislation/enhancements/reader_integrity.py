"""Independent numeric checks. Citation presence alone does not prove accuracy.

These are conservative mechanical safeguards, not a semantic correctness proof.
Amounts stay attached to each item's cited evidence, never the entire bill.
"""

import re

from .diagnostics import output_error
from .percentage_bases import (
    cited_percentage_bases,
    percentage_base_conflicts,
    percentage_bases,
    percentages,
)
from .provision_validation import _amounts

_AUTHORIZATION = re.compile(r"\bauthoriz\w*\s+to\s+be\s+appropriated\b", re.I)
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


def authorization_only_amounts(quotes):
    authorized, other = set(), set()
    for quote in quotes:
        for clause in _funding_clauses(quote["quote"]):
            bucket = authorized if _AUTHORIZATION.search(clause) else other
            bucket.update(_amounts(clause))
    return authorized - other


def validate_numbers(item, *, path):
    evidence = "\n".join(q["quote"] for q in item["source_quotes"])
    fields = [
        str(item.get(key) or "") for key in ("text", "amount_display", "label", "title")
    ]
    prose = "\n".join(fields)
    if _amounts(prose) - _amounts(evidence) or percentages(prose) - percentages(
        evidence
    ):
        raise output_error("reader_amount_conflict", path)
    cited = cited_percentage_bases(q["quote"] for q in item["source_quotes"])
    for field in fields:
        for number, basis in percentage_bases(field):
            if percentage_base_conflicts(number, basis, cited):
                raise output_error("reader_amount_conflict", path)
    # A matching dollar figure is not enough: authorization does not itself
    # require spending. Keep this check amount-scoped so a separate mandatory
    # allocation in the same evidence is not mistaken for an authorization.
    authorization_only = authorization_only_amounts(item["source_quotes"])
    if authorization_only:
        for field in fields:
            for clause in _funding_clauses(field):
                if (
                    _REQUIRED_OUTLAY.search(clause)
                    and _amounts(clause) & authorization_only
                ):
                    raise output_error("reader_amount_conflict", path)


def financial_signal_text(text):
    """Exclude committee names, not funding elsewhere in the same passage."""
    return re.sub(
        r"\b(?:committees?\s+on\s+appropriations|appropriations\s+committees?)\b",
        "committee",
        text,
        flags=re.I,
    )


def requires_financial_item(text):
    # Dollars cannot be waived by a model's self-reported checklist. Also catch
    # operative funding without a fixed total and percentage set-asides.
    text = financial_signal_text(text)
    return bool(
        _amounts(text)
        or re.search(
            r"\b(?:appropriat(?:ed|ion|ions)|authorized to be appropriated|"
            r"(?:shall|may|must) appropriate\s+(?:funds|money|sums)|"
            r"shall (?:reserve|transfer|allocate)|(?:may|shall) set aside)\b",
            text,
            re.I,
        )
        or re.search(
            r"(?:percent\b|%)\s+of\s+(?:(?:the|total|remaining|annual|grant|appropriated)\s+)*"
            r"(?:funds|amount|revenue|receipts|costs|income|grants)\b",
            text,
            re.I,
        )
    )


def validate_financial_coverage(output, catalogs):
    for key, disposition in output["money_checks"].items():
        ref, quote_id = key.split(":", 1)
        passage = catalogs[ref][quote_id]
        if requires_financial_item(passage) and disposition != "financial":
            raise output_error("reader_coverage_incomplete", ["money_checks", key])
        if disposition != "financial":
            continue
        supporting = [
            item
            for item in output["financial_items"]
            if any(
                q["source_ref"] == ref and q["quote_id"] == quote_id
                for q in item["source_quotes"]
            )
        ]
        prose = "\n".join(
            item["amount_display"] + " " + item["text"] for item in supporting
        )
        if _amounts(passage) - _amounts(prose) or percentages(passage) - percentages(
            prose
        ):
            raise output_error("reader_coverage_incomplete", ["financial_items", key])
