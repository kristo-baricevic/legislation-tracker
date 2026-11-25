"""Retain independently valid ownership groups, never half a shared finding."""

import copy

from jsonschema import ValidationError

from .reader_citations import citation_passages
from .reader_discovery import resolve_discovery


class PartialReviewReady(Exception):
    def __init__(self, parts, pending, usage, resolved_model=""):
        self.parts, self.pending, self.usage = parts, pending, usage
        self.resolved_model = resolved_model


def validated_components(output, sources):
    if len(sources) != 1 or not isinstance(output, dict):
        return [], []
    source = sources[0]
    ref = source["source_ref"]
    owned = [
        p["quote_id"]
        for p in citation_passages(source)
        if p["quote_id"]
        and (
            source.get("review_quote_ids") is None
            or p["quote_id"] in source["review_quote_ids"]
        )
    ]
    groups = [{i} for i in owned]
    categories = ("financial_items", "additional_changes", "policy_changes")
    expected = {"financial_items", "additional_changes", "money_checks"}
    if source.get("policy_review"):
        expected |= {"policy_changes", "policy_checks"}
    # Malformed outer shape cannot safely identify independent work.
    if set(output) != expected or any(
        not isinstance(output.get(k, []), list) for k in categories
    ):
        return [], owned
    if any(
        not isinstance(output.get(k, {}), dict)
        for k in ("money_checks", "policy_checks")
    ):
        return [], owned
    for category in categories:
        for item in output.get(category, []):
            if not isinstance(item, dict) or not isinstance(
                item.get("source_quotes"), list
            ):
                return [], owned
            quotes = item["source_quotes"]
            if any(not isinstance(q, dict) for q in quotes):
                return [], owned
            ids = {
                q.get("quote_id") for q in quotes if q.get("source_ref") == ref
            } & set(owned)
            if not ids:
                return [], owned
            linked = [g for g in groups if g & ids]
            merged = set().union(*linked)
            groups = [g for g in groups if not g & ids] + [merged]
    valid, pending = [], []
    for group in sorted(groups, key=lambda g: min(owned.index(i) for i in g)):
        ids = [i for i in owned if i in group]
        subset = copy.deepcopy(output)
        for category in categories:
            if category in subset:
                subset[category] = [
                    item
                    for item in subset[category]
                    if any(
                        q.get("source_ref") == ref and q.get("quote_id") in group
                        for q in item["source_quotes"]
                    )
                ]
        for key in ("money_checks", "policy_checks"):
            if key in subset:
                subset[key] = {
                    k: v
                    for k, v in subset[key].items()
                    if k in {f"{ref}:{i}" for i in group}
                }
        try:
            resolve_discovery(subset, [{**source, "review_quote_ids": ids}])
        except (ValidationError, KeyError, TypeError, ValueError):
            pending.extend(ids)
        else:
            valid.append((ids, subset))
    return valid, [i for i in owned if i in pending]
