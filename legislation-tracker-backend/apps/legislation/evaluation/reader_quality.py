"""Transparent regression checks, not a claim of automated legal entailment.

Gold facts are manually authored regex conjunctions scoped to one displayed item.
They cannot be satisfied by unrelated words elsewhere in an explanation. Keep
human semantic review separate from these reproducible proxy measurements.
"""

import json
import re
from collections import Counter, defaultdict

from .correctness import (
    faithful_source_display,
    score_correctness,
)
from .correctness import (
    source_only as is_source_only,
)

FRAGMENT = re.compile(
    r"\b(?:to|in|for|which|the following|set aside)\s*[.;]?$|\bAllows Providing\b", re.I
)


def nlp_items(contract, *, evidence=None, source_text=None):
    by_path = defaultdict(list)
    for span in evidence or ():
        by_path[span.field_path].append(span)
    items = [
        {**x, "category": "line_item", "text": x["display_text"]}
        for x in contract.get("line_items", [])
        if x.get("kind") != "financial"
    ]
    items += [
        {**x, "category": "financial", "text": x["display_text"]}
        for x in contract.get("financial_items", [])
    ]
    items += [
        {**x, "category": "definition", "text": x["display_text"], "term": x["term"]}
        for x in contract.get("definitions", [])
    ]
    requirements = {r["id"]: r for r in contract.get("requirements", [])}
    orientation = contract.get("orientation", {})
    for item in items:
        if item.get("kind") == "purpose":
            item["synopsis_consistent"] = item.get("id") == orientation.get(
                "purpose_line_item_id"
            ) and item["text"] == orientation.get("purpose_clause")
        refs = item.get("claim_refs", [])
        if len(refs) == 1 and refs[0] in requirements:
            requirement = requirements[refs[0]]
            item.update({k: requirement[k] for k in ("modality", "conditions")})
        if evidence is not None:
            paths = item.get("evidence_paths", [])
            linked = [e for path in paths for e in by_path[path]]
            item["evidence_quotes"] = list(dict.fromkeys(e.quoted_text for e in linked))
            item["evidence_valid"] = (
                bool(linked)
                and source_text is not None
                and all(
                    0 <= e.start_char < e.end_char <= len(source_text)
                    and source_text[e.start_char : e.end_char] == e.quoted_text
                    for e in linked
                )
                and all(by_path[path] for path in paths)
            )
    if orientation.get("purpose_clause") is not None and not any(
        i.get("kind") == "purpose"
        and i.get("id") == orientation.get("purpose_line_item_id")
        for i in items
    ):
        items.append(
            {
                "category": "synopsis",
                "text": orientation["purpose_clause"],
                "synopsis_consistent": False,
            }
        )
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
                    **item,
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


def score_reader(
    case, items, *, sources=None, usage=None, elapsed_ms=None, rates=None, pipeline=None
):
    missing = []
    if sources is not None:
        by_ref = {s["source_ref"]: s for s in sources}
        items = [dict(item) for item in items]
        for item in items:
            quotes, refs = item.get("source_quotes", []), item.get("source_refs", [])
            item["evidence_quotes"] = [q.get("quote", "") for q in quotes]
            item["evidence_valid"] = (
                bool(quotes)
                and all(
                    q.get("source_ref") in refs
                    and q.get("source_ref") in by_ref
                    and bool(q.get("quote"))
                    and q["quote"] in by_ref[q["source_ref"]]["quoted_text"]
                    for q in quotes
                )
                if quotes
                else None
            )
    correctness = score_correctness(case, items, pipeline or "ai")
    facts = case.get("required_facts", []) + (
        case.get("glossary_facts", []) if pipeline == "nlp" else []
    )
    for fact in facts:
        candidates = [
            x["text"]
            for x in items
            if (not fact.get("category") or x.get("category") == fact["category"])
            and (
                not fact.get("term")
                or x.get("term", "").casefold() == fact["term"].casefold()
            )
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
    source_only = sum(t.startswith("Source text (not simplified):") for t in texts)
    definitions = [x["text"] for x in items if x.get("category") == "definition"]
    unresolved = sum("unresolved legal reference" in t.lower() for t in definitions)
    unexplained = sum(
        bool(re.search(r"\bmeaning (?:given|assigned|provided)\b", t, re.I))
        and "unresolved legal reference" not in t.lower()
        for t in definitions
    )
    word_counts = [len(re.findall(r"\b[\w'-]+\b", text)) for text in texts]
    duplicates = sum(
        n - 1
        for n in Counter(
            (
                re.sub(r"\W+", " ", item["text"].casefold()).strip(),
                json.dumps(
                    {
                        k: item[k]
                        for k in (
                            "financial_action",
                            "amount",
                            "amount_type",
                            "currency",
                            "fiscal_years",
                            "direction",
                            "purpose",
                            "source_account",
                            "destination_account",
                        )
                        if k in item
                    },
                    sort_keys=True,
                )
                if item.get("category") == "financial"
                else "",
            )
            for item in items
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
    required = len(facts)
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
    failures = list(correctness["failures"])
    if any(
        is_source_only(item)
        and item.get("evidence_valid") is True
        and not faithful_source_display(item)
        for item in items
    ):
        failures.append("unfaithful_source_display")
    invalid_nlp_evidence = sum(item.get("evidence_valid") is False for item in items)
    if invalid_nlp_evidence:
        failures.append("invalid_item_evidence")
    inconsistent_synopsis = any(i.get("synopsis_consistent") is False for i in items)
    if inconsistent_synopsis:
        failures.append("inconsistent_synopsis")
    if unexplained:
        failures.append("unexplained_definitions")
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
        "correctness": correctness,
        "dimensions": {
            "correctness": {
                "status": "fail"
                if correctness["failures"]
                or forbidden
                or invalid_citations
                or invalid_nlp_evidence
                or absence_claims
                or inconsistent_synopsis
                or "unfaithful_source_display" in failures
                else "pass"
                if correctness["evaluated"]
                else "not_evaluated"
            },
            "coverage": {
                "status": "fail"
                if missing or correctness["missing_fact_ids"] or not financial_count_ok
                else "pass"
                if facts
                or correctness["expected_fact_count"]
                or "expected_financial_count" in case
                else "not_evaluated",
                "fact_recall": correctness["fact_recall"],
            },
            "readability": {
                "status": "fail" if fragments or duplicates or unexplained else "pass",
                "scope": "heuristics_only",
            },
            "abstention": {
                "status": "fail"
                if correctness["missing_source_only_ids"]
                or correctness["source_only_leak_indices"]
                or "unfaithful_source_display" in failures
                else "pass"
                if correctness["expected_source_only_count"]
                else "not_evaluated"
            },
        },
        "metrics": {
            "source_only_item_count": source_only,
            "invalid_item_evidence_count": invalid_nlp_evidence,
            "source_only_item_fraction": source_only / len(texts) if texts else None,
            "unexplained_definition_count": unexplained,
            "unresolved_definition_count": unresolved,
            "literal_definition_count": sum(
                t.startswith("Legal definition:") for t in definitions
            ),
            "ambiguous_definition_count": sum(
                "source wording is unclear" in t for t in definitions
            ),
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
