"""Transparent regression checks, not a claim of automated legal entailment.

Gold facts are manually authored regex conjunctions scoped to one displayed item.
They cannot be satisfied by unrelated words elsewhere in an explanation. Keep
human semantic review separate from these reproducible proxy measurements.
"""

import re
from collections import Counter

FRAGMENT = re.compile(
    r"\b(?:to|in|for|which|the following|set aside)\s*[.;]?$|\bAllows Providing\b", re.I
)


def nlp_items(contract):
    items = [
        {"category": "line_item", "text": x["display_text"]}
        for x in contract.get("line_items", [])
        if x.get("kind") != "financial"
    ]
    items += [
        {"category": "financial", "text": x["display_text"]}
        for x in contract.get("financial_items", [])
    ]
    items += [
        {"category": "definition", "text": x["display_text"]}
        for x in contract.get("definitions", [])
    ]
    return items


def ai_items(output):
    result = []
    for category in (
        "overview",
        "key_impacts",
        "obligations",
        "funding_and_timing",
        "uncertain_language",
    ):
        for item in output.get(category, []):
            text = item.get("text") or " ".join(
                str(item.get(k) or "")
                for k in ("actor", "modality", "action", "conditions")
            )
            result.append(
                {
                    "category": "financial"
                    if item.get("kind") == "funding"
                    else category,
                    "text": text,
                    **{
                        k: item[k]
                        for k in ("source_refs", "source_quotes")
                        if k in item
                    },
                }
            )
    return result


def score_reader(case, items, *, sources=None, usage=None, elapsed_ms=None, rates=None):
    missing = []
    for fact in case.get("required_facts", []):
        candidates = [
            x["text"]
            for x in items
            if not fact.get("category") or x.get("category") == fact["category"]
        ]
        if not any(
            all(re.search(p, text, re.I | re.S) for p in fact["patterns"])
            for text in candidates
        ):
            missing.append(fact["id"])
    forbidden = [
        p
        for p in case.get("forbidden_patterns", [])
        if any(re.search(p, x["text"], re.I) for x in items)
    ]
    texts = [x["text"] for x in items]
    word_counts = [len(re.findall(r"\b[\w'-]+\b", text)) for text in texts]
    duplicates = sum(
        n - 1
        for n in Counter(
            re.sub(r"\W+", " ", t.casefold()).strip() for t in texts
        ).values()
    )
    fragments = sum(bool(FRAGMENT.search(t)) for t in texts)
    financial_count = sum(x.get("category") == "financial" for x in items)
    financial_count_ok = (
        case.get("expected_financial_count", financial_count) == financial_count
    )
    invalid_citations = 0
    broad_citations = 0
    if sources is not None:
        by_ref = {s["source_ref"]: s for s in sources}
        for item in items:
            refs = item.get("source_refs", [])
            if not refs or any(ref not in by_ref for ref in refs):
                invalid_citations += 1
            quotes = item.get("source_quotes", [])
            if quotes:
                invalid_citations += sum(
                    q.get("source_ref") not in refs
                    or not q.get("quote")
                    or q["quote"]
                    not in by_ref.get(q.get("source_ref"), {}).get("quoted_text", "")
                    for q in quotes
                )
                broad_citations += sum(len(q.get("quote", "")) > 800 for q in quotes)
            else:
                broad_citations += sum(
                    len(by_ref.get(ref, {}).get("quoted_text", "")) > 800
                    for ref in refs
                )
    usage = usage or {}
    cost = None
    if rates and all(
        isinstance(usage.get(k), int) and usage[k] >= 0
        for k in ("input_tokens", "output_tokens")
    ):
        cost = (
            usage["input_tokens"] * rates["input_per_million"]
            + usage["output_tokens"] * rates["output_per_million"]
        ) / 1_000_000
    required = len(case.get("required_facts", []))
    absence_claims = (
        sum(
            bool(
                re.search(
                    r"\b(?:bill|act)\s+(?:contains|provides|has|specifies|authorizes)\s+no\b|"
                    r"\b(?:bill|act)\s+does\s+not\s+(?:provide|specify|authorize|appropriate)\b",
                    text,
                    re.I,
                )
            )
            for text in texts
        )
        if case.get("truncated")
        else 0
    )
    failures = []
    if missing:
        failures.append("missing_required_facts")
    if forbidden:
        failures.append("forbidden_claims")
    if fragments:
        failures.append("sentence_fragments")
    if duplicates:
        failures.append("duplicate_items")
    if not financial_count_ok:
        failures.append("financial_count_mismatch")
    if invalid_citations:
        failures.append("invalid_citations")
    if absence_claims:
        failures.append("unsupported_absence_claim")
    return {
        "passed": not failures,
        "failures": failures,
        "missing_facts": missing,
        "forbidden_matches": forbidden,
        "metrics": {
            "annotated_fact_count": required,
            "unsupported_absence_claim_count": absence_claims,
            "required_fact_recall": (required - len(missing)) / required
            if required
            else None,
            "financial_count": financial_count,
            "fragment_count": fragments,
            "duplicate_count": duplicates,
            "invalid_citation_count": invalid_citations,
            "broad_citation_count": broad_citations,
            "item_count": len(items),
            "max_item_words": max(word_counts, default=0),
            "items_over_60_words": sum(n > 60 for n in word_counts),
            "latency_ms": elapsed_ms,
            "usage": usage,
            "estimated_cost_usd": cost,
        },
        "human_review_required": [
            "semantic support of each claim",
            "important facts outside annotated cases",
            "plain-English clarity",
        ],
    }
