"""Model-selected passage IDs, resolved to verbatim server-owned citations."""

import copy
import re

from jsonschema import Draft202012Validator

from .citations import citation_spans
from .diagnostics import output_error
from .reader_targets import READER_SCHEMA, validate_reader_explanations

READER_PROMPT_VERSION = "reader-2"
READER_ID_SCHEMA = copy.deepcopy(READER_SCHEMA)
for category in ("summary", "explanations"):
    READER_ID_SCHEMA["properties"][category]["items"]["properties"]["source_quotes"]["items"] = {
        "type": "object", "additionalProperties": False,
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
READER_ID_SCHEMA["properties"]["explanations"]["items"] = {"anyOf": [_explained, _unresolved]}


def citation_passages(source):
    """Partition without losing text; keep each selectable quote within 800 chars.

    Prefer sentence/line boundaries. Repeated passages remain visible as context
    but cannot be selected when the existing citation resolver cannot locate them
    uniquely. Nothing is inferred or repaired from generated prose.
    """
    text = source["quoted_text"]
    passages = []
    start = 0
    while start < len(text):
        end = min(start + 800, len(text))
        if end < len(text):
            boundaries = list(re.finditer(r"[.!?](?:\s+)|\n+", text[start:end]))
            if boundaries and boundaries[-1].end() >= 100:
                end = start + boundaries[-1].end()
        quote = text[start:end]
        selectable = len(citation_spans(text, quote)) == 1
        passages.append({
            "quote_id": f"p{len(passages) + 1:04d}" if selectable else None,
            "text": quote,
        })
        start = end
    return passages


def resolve_reader_citations(output, targets, sources):
    """Resolve only IDs from this immutable request, then run all existing checks."""
    Draft202012Validator(READER_ID_SCHEMA).validate(output)
    catalogs = {
        source["source_ref"]: {p["quote_id"]: p["text"] for p in citation_passages(source)
                               if p["quote_id"] is not None}
        for source in sources
    }
    resolved = copy.deepcopy(output)
    for category in ("summary", "explanations"):
        for index, item in enumerate(resolved[category]):
            for quote_index, citation in enumerate(item["source_quotes"]):
                quote = catalogs.get(citation["source_ref"], {}).get(citation["quote_id"])
                if quote is None:
                    raise output_error("reader_target_invalid", [category, index, "source_quotes", quote_index])
                citation.pop("quote_id")
                citation["quote"] = quote
    return validate_reader_explanations(resolved, targets, sources)
