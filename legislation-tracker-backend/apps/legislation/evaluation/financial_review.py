"""Source-pinned money regression checks; not a substitute for semantic review."""
import re


def evaluate_financial_review(review, expectations):
    failures = []
    for expected in expectations:
        supported = [item for item in review.get('financial_items', [])
                     if any(expected['source_text'] in quote['quote']
                            for quote in item.get('source_quotes', []))]
        prose = ' '.join(f"{item['amount_display']} {item['text']}" for item in supported)
        missing = [pattern for pattern in expected['patterns'] if not re.search(pattern, prose, re.I)]
        if not supported or missing:
            failures.append({'id': expected['id'], 'missing_patterns': missing,
                             'source_supported': bool(supported)})
    return {'passed': not failures, 'checked': len(expectations), 'failures': failures,
            'semantic_review_required': True}
