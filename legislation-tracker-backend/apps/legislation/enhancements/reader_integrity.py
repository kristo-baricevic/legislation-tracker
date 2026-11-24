"""Independent numeric checks. Citation presence alone does not prove accuracy.

These are conservative mechanical safeguards, not a semantic correctness proof.
Amounts stay attached to each item's cited evidence, never the entire bill.
"""
import re
from decimal import Decimal

from .diagnostics import output_error
from .provision_validation import _amounts


def percentages(text):
    return {Decimal(value.replace(',', '')) for value in re.findall(
        r'(\d[\d,]*(?:\.\d+)?)\s*(?:%|percent\b)', text, re.I)}


def validate_numbers(item, *, path):
    evidence = '\n'.join(q['quote'] for q in item['source_quotes'])
    prose = '\n'.join(str(item.get(key) or '') for key in ('text', 'amount_display', 'label', 'title'))
    if _amounts(prose) - _amounts(evidence) or percentages(prose) - percentages(evidence):
        raise output_error('reader_amount_conflict', path)
    # A matching dollar figure is not enough: authorization does not itself
    # require spending. Keep this check amount-scoped so a separate mandatory
    # allocation in the same evidence is not mistaken for an authorization.
    authorized, other = set(), set()
    for clause in re.split(r'(?<=[.;])\s+', evidence):
        bucket = authorized if re.search(r'\bauthoriz\w*\s+to\s+be\s+appropriated\b', clause, re.I) else other
        bucket.update(_amounts(clause))
    for match in re.finditer(r'\b(?:must|shall|will)\s+(?:allocate|spend|appropriate|disburse)\b[^.;]{0,160}', prose, re.I):
        if _amounts(match.group()) & (authorized - other):
            raise output_error('reader_amount_conflict', path)


def financial_signal_text(text):
    """Exclude committee names, not funding elsewhere in the same passage."""
    return re.sub(r'\b(?:committees?\s+on\s+appropriations|appropriations\s+committees?)\b',
                  'committee', text, flags=re.I)


def requires_financial_item(text):
    # Dollars cannot be waived by a model's self-reported checklist. Also catch
    # operative funding without a fixed total and percentage set-asides.
    text = financial_signal_text(text)
    return bool(_amounts(text) or re.search(
        r'\b(?:appropriat(?:ed|ion|ions)|authorized to be appropriated|'
        r'(?:shall|may|must) appropriate\s+(?:funds|money|sums)|'
        r'shall (?:reserve|transfer|allocate)|(?:may|shall) set aside)\b', text, re.I)
        or re.search(r'(?:percent\b|%)\s+of\s+(?:(?:the|total|remaining|annual|grant|appropriated)\s+)*'
                     r'(?:funds|amount|revenue|receipts|costs|income|grants)\b', text, re.I))


def validate_financial_coverage(output, catalogs):
    for key, disposition in output['money_checks'].items():
        ref, quote_id = key.split(':', 1)
        passage = catalogs[ref][quote_id]
        if requires_financial_item(passage) and disposition != 'financial':
            raise output_error('reader_coverage_incomplete', ['money_checks', key])
        if disposition != 'financial':
            continue
        supporting = [item for item in output['financial_items'] if any(
            q['source_ref'] == ref and q['quote_id'] == quote_id for q in item['source_quotes'])]
        prose = '\n'.join(item['amount_display'] + ' ' + item['text'] for item in supporting)
        if _amounts(passage) - _amounts(prose) or percentages(passage) - percentages(prose):
            raise output_error('reader_coverage_incomplete', ['financial_items', key])
