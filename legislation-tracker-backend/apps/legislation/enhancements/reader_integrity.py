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


def requires_financial_item(text):
    # Dollars cannot be waived by a model's self-reported checklist. Also catch
    # operative funding without a fixed total and percentage set-asides.
    return bool(_amounts(text) or re.search(
        r'\b(?:appropriat(?:ed|ion|ions)|authorized to be appropriated|'
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
