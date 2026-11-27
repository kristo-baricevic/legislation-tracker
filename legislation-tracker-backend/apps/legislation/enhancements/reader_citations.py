"""Model-selected passage IDs, resolved to verbatim server-owned citations."""

import copy
import re
from collections import OrderedDict
from contextvars import ContextVar
from functools import wraps

from jsonschema import Draft202012Validator, ValidationError

from .citations import _canonical, spans_in_canonical_source
from .diagnostics import output_error
from .reader_targets import READER_SCHEMA, validate_reader_explanations

READER_PROMPT_VERSION = "reader-8-policy-explanations"
_PASSAGE_CACHE = ContextVar("reader_passage_cache", default=None)


def cached_citations(function):
    """Reuse immutable passage catalogs only for one planning/worker operation."""

    @wraps(function)
    def run(*args, **kwargs):
        if _PASSAGE_CACHE.get() is not None:
            return function(*args, **kwargs)
        token = _PASSAGE_CACHE.set(OrderedDict())
        try:
            return function(*args, **kwargs)
        finally:
            _PASSAGE_CACHE.reset(token)

    return run


READER_ID_SCHEMA = copy.deepcopy(READER_SCHEMA)
READER_ID_SCHEMA["properties"].pop("source_review")
for category in ("summary", "explanations"):
    READER_ID_SCHEMA["properties"][category]["items"]["properties"]["source_quotes"][
        "items"
    ] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["source_ref", "quote_id"],
        "properties": {
            "source_ref": {"type": "string", "pattern": r"^src_[0-9]{4}$"},
            "quote_id": {"type": "string", "pattern": r"^p[0-9]{4,}$"},
        },
    }

# Express outcome invariants in the provider schema, not only after generation.
# An unresolved result must not carry a partial explanation or citations.
_explained = copy.deepcopy(READER_ID_SCHEMA["properties"]["explanations"]["items"])
_unresolved = copy.deepcopy(_explained)
_explained["properties"]["status"] = {"type": "string", "enum": ["explained"]}
_explained["properties"]["text"]["type"] = "string"
_explained["properties"]["unresolved_reason"] = {"type": "null"}
_explained["properties"]["source_quotes"]["minItems"] = 1
_unresolved["properties"]["status"] = {"type": "string", "enum": ["unresolved"]}
_unresolved["properties"]["text"] = {"type": "null"}
_unresolved["properties"]["unresolved_reason"]["type"] = "string"
_unresolved["properties"]["source_quotes"]["maxItems"] = 0
READER_ID_SCHEMA["properties"]["explanations"]["items"] = {
    "anyOf": [_explained, _unresolved]
}


def citation_passages(source):
    """Partition without losing text; keep each selectable quote within 800 chars.

    Prefer sentence/line boundaries. Repeated passages remain visible as context
    but cannot be selected when the existing citation resolver cannot locate them
    uniquely. Nothing is inferred or repaired from generated prose.
    """
    text = source["quoted_text"]
    cache = _PASSAGE_CACHE.get()
    if cache is not None and text in cache:
        cache.move_to_end(text)
        # Callers may annotate wire catalogs; never share mutable entries.
        return [{"quote_id": key, "text": value} for key, value in cache[text]]
    canonical = _canonical(text)
    passages = []
    start = 0
    while start < len(text):
        end = min(start + 800, len(text))
        if end < len(text):
            boundaries = list(re.finditer(r"[.!?](?:\s+)|\n+", text[start:end]))
            if boundaries and boundaries[-1].end() >= 100:
                end = start + boundaries[-1].end()
        quote = text[start:end]
        selectable = len(spans_in_canonical_source(canonical, quote)) == 1
        passages.append(
            {
                "quote_id": f"p{len(passages) + 1:04d}" if selectable else None,
                "text": quote,
            }
        )
        start = end
    if cache is not None:
        cache[text] = tuple((p["quote_id"], p["text"]) for p in passages)
        if len(cache) > 4096:
            cache.popitem(last=False)
    return passages


def bounded_reader_schema(sources, targets, catalogs):
    """Make required target outcomes and valid citation pairs decoder constraints."""
    schema = copy.deepcopy(READER_ID_SCHEMA)
    schema["properties"]["summary"]["maxItems"] = 2
    schema["properties"]["summary"]["items"]["properties"]["text"].update(maxLength=300)
    if not targets:
        return schema
    properties = {}
    for target in targets:
        quotes = []
        for source in sources:
            if not any(
                t["target_id"] == target["target_id"]
                for t in source.get("reader_targets", [])
            ):
                continue
            ids = []
            start = source["start_char"]
            for passage in catalogs[source["source_ref"]]:
                end = start + len(passage["text"])
                if passage["quote_id"] and any(
                    start < right and end > left
                    for left, right in target["evidence_ranges"]
                ):
                    ids.append(passage["quote_id"])
                start = end
            if ids:
                quotes.append(
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["source_ref", "quote_id"],
                        "properties": {
                            "source_ref": {
                                "type": "string",
                                "enum": [source["source_ref"]],
                            },
                            "quote_id": {"type": "string", "enum": ids},
                        },
                    }
                )
        explained, unresolved = copy.deepcopy(
            READER_ID_SCHEMA["properties"]["explanations"]["items"]["anyOf"]
        )
        if target.get("kind") == "line_item":
            explained["properties"]["text"].update(maxLength=400, pattern=r"[.!?]$")
        for variant in (explained, unresolved):
            variant["properties"]["target_id"] = {
                "type": "string",
                "enum": [target["target_id"]],
            }
        if quotes:
            explained["properties"]["source_quotes"]["items"] = {"anyOf": quotes}
        properties[target["target_id"]] = (
            {"anyOf": [explained, unresolved]} if quotes else unresolved
        )
    schema["properties"]["explanations"] = {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }
    return schema


def recover_reader_items(output, targets, sources):
    """Drop only unsupported replacements before caching or publishing them."""
    if (
        not targets
        or not isinstance(output, dict)
        or not isinstance(output.get("summary"), list)
    ):
        return output
    # Only the separate final-summary call owns published summary prose. Never
    # cache unsolicited summary text (even when its citations look plausible).
    output = {**output, "summary": []}
    original = output.get("explanations")
    if not isinstance(original, (dict, list)):
        return output
    if isinstance(original, list):
        if any(
            not isinstance(v, dict) or not isinstance(v.get("target_id"), str)
            for v in original
        ):
            return output
        mapping = {v["target_id"]: v for v in original}
        if len(mapping) != len(original):
            return output
    else:
        mapping = original
    if set(mapping) != {t["target_id"] for t in targets}:
        return output  # Never pretend missing or unexpected targets were reviewed.
    from .schema import _validate_snapshot

    _validate_snapshot(sources)
    safe = {}
    for target in targets:
        tid = target["target_id"]
        item = mapping[tid]
        if not isinstance(item, dict) or item.get("target_id") != tid:
            return output
        local = [s for s in sources if target in s.get("reader_targets", [])]
        try:
            resolve_reader_citations(
                {**output, "explanations": {tid: item}}, [target], local
            )
            safe[tid] = item
        except ValidationError:
            safe[tid] = {
                "target_id": tid,
                "status": "unresolved",
                "text": None,
                "source_quotes": [],
                "unresolved_reason": "Original explanation retained.",
            }
    return {
        **output,
        "explanations": safe if isinstance(original, dict) else list(safe.values()),
    }


def resolve_reader_citations(output, targets, sources):
    """Resolve only IDs from this immutable request, then run all existing checks."""
    output = copy.deepcopy(output)
    if isinstance(output.get("explanations"), dict):
        Draft202012Validator(
            bounded_reader_schema(
                sources,
                targets,
                {s["source_ref"]: citation_passages(s) for s in sources},
            )
        ).validate(output)
        mapping = output["explanations"]
        if set(mapping) != {t["target_id"] for t in targets} or any(
            not isinstance(v, dict) or v.get("target_id") != k
            for k, v in mapping.items()
        ):
            raise output_error("reader_coverage_incomplete", ["explanations"])
        output["explanations"] = list(mapping.values())
    Draft202012Validator(READER_ID_SCHEMA).validate(output)
    catalogs = {
        source["source_ref"]: {
            p["quote_id"]: p["text"]
            for p in citation_passages(source)
            if p["quote_id"] is not None
            and (
                source.get("allowed_quote_ids") is None
                or p["quote_id"] in source["allowed_quote_ids"]
            )
        }
        for source in sources
    }
    resolved = copy.deepcopy(output)
    for category in ("summary", "explanations"):
        for index, item in enumerate(resolved[category]):
            for quote_index, citation in enumerate(item["source_quotes"]):
                quote = catalogs.get(citation["source_ref"], {}).get(
                    citation["quote_id"]
                )
                if quote is None:
                    raise output_error(
                        "reader_target_invalid",
                        [category, index, "source_quotes", quote_index],
                    )
                citation.pop("quote_id")
                citation["quote"] = quote
    return validate_reader_explanations(resolved, targets, sources)
