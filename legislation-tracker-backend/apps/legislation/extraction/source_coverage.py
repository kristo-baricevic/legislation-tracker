"""Source-preserving supplements for provisions the semantic rules cannot simplify.

Never turn amendment amounts or formula operands into new appropriations.
"""
import re
from .federal_clauses import _quoted_block_ranges, _parent_section
from .federal_structure import sentence_spans
from .types import ExtractedClaim, SourceSpan
from .operative_context import parse_operative_clauses
from .financial_rules import is_explicit_tax_rule

MONEY = re.compile(r'\$\s*\d|\b\d[\d,]*\s+(?:(?:million|billion|thousand)\s+)?dollars\b|\bsuch sums as may be necessary\b', re.I)
FINANCIAL = re.compile(r'\b(?:funds?|grants?|payments?|fees?|penalt(?:y|ies)|appropriat\w*|loans?|tax\w*|amounts?|wages?|allot\w*|allocat\w*)\b', re.I)
AMEND = re.compile(r'\b(?:striking|inserting|is amended|are amended)\b', re.I)
TIMING = re.compile(r'\b(?:shall take effect|takes effect|not later than|beginning on January 1 of the year)\b', re.I)


def supplement_source_claims(source, sections, claims, clauses=None):
    additions = []
    excluded = _quoted_block_ranges(source)
    clauses = parse_operative_clauses(source, sections) if clauses is None else clauses
    claimed = {key: [s for c in claims if c.category == key for s in c.evidence]
               for key in ('financial_items', 'timeline_items')}
    owned = []
    for section in sections:
        parent = _parent_section(section, sections)
        parent_spans = sentence_spans(parent, source) if parent else ()
        context = (parent_spans[-1],) if parent_spans and parent_spans[-1].text.rstrip().endswith((':','—','–','-')) else ()
        for span in sentence_spans(section, source):
            owners = [c for c in clauses if c.span.start_char < span.end_char and span.start_char < c.span.end_char]
            if any(c.disposition in {'prohibition', 'discussion', 'uncertain'} or c.preserve_group for c in owners):
                continue
            if any(a < span.end_char and span.start_char < b for a,b in excluded):
                continue
            if any(a <= span.start_char and span.end_char <= b for a,b in owned):
                continue
            raw = ' '.join(s.text for s in (*context, span))
            # A formula's operands are children, so keep the whole list together.
            if re.search(r'\b(?:greater|lesser|sum) of\s*[:—–-]$', span.text.strip(), re.I) and FINANCIAL.search(raw):
                span = SourceSpan(source[span.start_char:section.span.end_char], span.start_char, section.span.end_char)
                raw = ' '.join(s.text for s in (*context, span))
            if any(a < span.end_char and span.start_char < b for a,b in excluded):
                continue
            evidence = (*context, span)
            def present(category):
                return any(s.start_char <= span.start_char and span.end_char <= s.end_char for s in claimed[category])
            category, fields = None, None
            formula = re.search(r'\b(?:greater|lesser|sum) of\b', raw, re.I) and FINANCIAL.search(raw)
            proportional_reduction = FINANCIAL.search(raw) and re.search(r'\bshall be reduced in proportion\b', raw, re.I)
            tax_rule = is_explicit_tax_rule(raw)
            if (tax_rule or (proportional_reduction or MONEY.search(raw) and (AMEND.search(raw) or formula)) and re.search(r'\b(?:shall|must|is amended|are amended|by striking)\b', raw, re.I)) and not present('financial_items'):
                # The full before/after or conditional rule is authoritative.
                # No bare operand is presented as an unconditional dollar total.
                category = 'financial_items'
                fields = dict(financial_action='source_rule', direction='not_applicable', amount=None,
                              amount_type='unspecified', currency=None, fiscal_years=[], purpose=None,
                              source_account=None, destination_account=None)
            elif TIMING.search(raw) and any(c.asserted for c in owners) and not AMEND.search(raw) and not any(s.start_char < span.end_char and span.start_char < s.end_char for s in claimed['timeline_items']):
                category = 'timeline_items'
                kind = 'effective' if re.search(r'\b(?:take|takes) effect\b', raw, re.I) else 'relative'
                fields = dict(timeline_type=kind, date=None, relative_value=None, relative_unit=None, trigger=None)
            if category:
                additions.append(ExtractedClaim(category, fields, section.label, evidence,
                    f'coverage.source.{category}.v1', section.source_id, section.source_id, section.path))
                owned.append((span.start_char, span.end_char))
    return (*claims, *additions)
