"""Independent numeric checks. Citation presence alone does not prove accuracy.

These are conservative mechanical safeguards, not a semantic correctness proof.
Amounts stay attached to each item's cited evidence, never the entire bill.
"""

import re

from .diagnostics import output_error
from .funding_roles import (
    claim_prerequisites,
    dollar_amounts,
    funding_decisions,
    funding_statement_conflicts,
    malformed_dollar_amount,
)
from .percentage_bases import (
    cited_percentage_bases,
    percentage_base_conflicts,
    percentage_bases,
    percentages,
)


def _display_bound_conflicts(item, cited):
    display = item.get("amount_display") or ""
    if not display:
        return False
    # A compact amount label often omits the governing verb. Bind it to the item's
    # separately validated decision so another account cannot supply its bound.
    described = funding_decisions([item.get("text") or ""])
    for label in funding_decisions([display]):
        if label.amount is None:
            continue
        candidates = [
            d
            for d in described
            if d.amount == label.amount and d.authority != "nonoperative"
        ] or [d for d in cited if d.amount == label.amount]
        if label.purpose:
            candidates = [d for d in candidates if d.purpose == label.purpose]
        if {d.comparator for d in candidates} != {label.comparator}:
            return True
    return False


def validate_numbers(item, *, path, factual_claim=None):
    evidence = "\n".join(q["quote"] for q in item["source_quotes"])
    fields = [
        str(item.get(key) or "") for key in ("text", "amount_display", "label", "title")
    ]
    prose = "\n".join(fields)
    if (
        malformed_dollar_amount(prose)
        or dollar_amounts(prose) - dollar_amounts(evidence)
        or percentages(prose) - percentages(evidence)
    ):
        raise output_error("reader_amount_conflict", path)
    cited = cited_percentage_bases(q["quote"] for q in item["source_quotes"])
    for field in fields:
        for number, basis in percentage_bases(field):
            if percentage_base_conflicts(number, basis, cited):
                raise output_error("reader_amount_conflict", path)
    cited_funding = funding_decisions(q["quote"] for q in item["source_quotes"])
    if _display_bound_conflicts(item, cited_funding):
        raise output_error("reader_amount_conflict", path)
    # Structured conditions qualify their own action. Never borrow them for a
    # separate published summary or parse a concatenation of JSON fields as prose.
    statements = [factual_claim["action"]] if factual_claim else fields
    prerequisites = (
        claim_prerequisites(factual_claim.get("conditions")) if factual_claim else set()
    )
    if any(
        funding_statement_conflicts(field, cited_funding, prerequisites)
        for field in statements
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
        dollar_amounts(text)
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
        if dollar_amounts(passage) - dollar_amounts(prose) or percentages(
            passage
        ) - percentages(prose):
            raise output_error("reader_coverage_incomplete", ["financial_items", key])
