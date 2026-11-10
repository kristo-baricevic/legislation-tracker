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


def evaluate_policy_review(review, expectations):
    """Coverage plus concrete readability hazards, not a reading-age claim."""
    from ..enhancements.reader_discovery import validate_policy_copy
    from jsonschema import ValidationError
    items = review.get('policy_changes', [])
    failures = []
    for expected in expectations:
        supported = [item for item in items if any(expected['source_text'] in q['quote']
                     for q in item.get('source_quotes', []))]
        prose = ' '.join(f"{i['title']} {i['text']}" for i in supported)
        if not supported or any(not re.search(p, prose, re.I) for p in expected['patterns']):
            failures.append({'id': expected['id'], 'reason': 'missing_supported_policy'})
    for index, item in enumerate(items):
        try:
            validate_policy_copy(item)
        except ValidationError:
            failures.append({'id': index, 'reason': 'unreadable_policy_copy'})
    return {'passed': not failures, 'checked': len(expectations), 'failures': failures,
            'policy_count': len(items), 'word_count': sum(len(i['text'].split()) for i in items),
            'human_readability_review_required': True}
