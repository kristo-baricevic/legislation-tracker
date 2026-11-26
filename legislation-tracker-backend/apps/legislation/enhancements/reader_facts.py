"""Cited factual map carried by the existing reader review and work units.

The prose inventory is a presentation of these records, never their replacement.
Each owned citation passage has one stable record, including structural passages
with no claims. Dependency reconciliation can page these records without losing
the original conditions, definitions, or evidence.
"""

import copy

from jsonschema import Draft202012Validator, ValidationError

from .diagnostics import output_error
from .reader_citations import citation_passages
from .source_first_schema import CLAIM, CONDITION, NULL_TEXT, TEXT, _evidence_ids, obj
from .source_packet import canonical_json_bytes

MAX_FACT_RECORD_BYTES = 16384
MAX_FACT_CLAIMS = 32

FACTUAL_MAP_INSTRUCTIONS = """
When factual_records is requested, map EVERY assigned record_id exactly once.
A record_id is source_ref:quote_id for an owned passage. Preserve every operative
claim, condition, exception, definition and cross-reference in structured records;
the short policy/financial prose is not a replacement for this factual inventory.
Use actor, action, modality, affected_people, money, timing, conditions, exceptions
and evidence_ids. Preserve all/any condition structure and percentage bases.
Definitions retain their term, meaning and stated scope. References retain the
source wording, its target and whether it governs a condition, definition,
amendment or another relationship. Cite every detail using supplied evidence IDs.
Every claim, definition and reference must cite its record's owned passage; it
may also cite supplied context. Other passages are mapped separately. Do not
infer that a remote condition is absent, resolved or satisfied. Retain the
reference for the later reconciliation pass. Empty arrays are only for source
passages with no substantive rule, definition or reference. Keep each record
within 16384 UTF-8 JSON bytes without dropping facts or clipping source meaning.
"""


def _passages(source):
    allowed = source.get("allowed_quote_ids")
    return [
        p
        for p in citation_passages(source)
        if p["quote_id"] and (allowed is None or p["quote_id"] in allowed)
    ]


def factual_record_ids(sources):
    """Stable output obligations, excluding context-only passages."""
    return [
        f"{source['source_ref']}:{passage['quote_id']}"
        for source in sources
        if source.get("factual_map")
        for passage in _passages(source)
        if source.get("review_quote_ids") is None
        or passage["quote_id"] in source["review_quote_ids"]
    ]


def factual_evidence(sources):
    """Hydrate only original passages actually supplied; never generated quotes."""
    return {
        f"{source['source_ref']}:{passage['quote_id']}": {
            "source_ref": source["source_ref"],
            "quote_id": passage["quote_id"],
            "quote": passage["text"],
        }
        for source in sources
        for passage in _passages(source)
    }


def record_evidence_ids(record):
    """Include evidence nested in every condition and exception, with depth caps."""
    return _evidence_ids(record)


def factual_records_schema(sources, *, aggregate=False):
    assigned = factual_record_ids(sources)
    evidence = factual_evidence(sources)
    evidence_id = {"type": "string"}
    record_id = {"type": "string"}
    if not aggregate:
        if evidence:
            evidence_id["enum"] = list(evidence)
        if assigned:
            record_id["enum"] = assigned
    ids = {
        "type": "array",
        "items": evidence_id,
        "minItems": 1,
        "maxItems": 32,
        "uniqueItems": True,
    }
    condition = copy.deepcopy(CONDITION)
    condition["anyOf"][0]["properties"]["evidence_ids"] = ids
    claim = copy.deepcopy(CLAIM)
    claim["properties"]["evidence_ids"] = ids
    for field in ("affected_people", "timing"):
        claim["properties"][field] = {
            "type": "array",
            "items": copy.deepcopy(TEXT),
            "maxItems": 32,
        }
        claim["required"].append(field)
    definition = obj(
        {
            "term": copy.deepcopy(TEXT),
            "meaning": {"type": "string", "minLength": 1, "maxLength": 6000},
            "scope": copy.deepcopy(NULL_TEXT),
            "evidence_ids": ids,
        }
    )
    reference = obj(
        {
            "text": {"type": "string", "minLength": 1, "maxLength": 1200},
            "target": copy.deepcopy(TEXT),
            "relation": {
                "type": "string",
                "enum": ["condition", "definition", "amendment", "other"],
            },
            "evidence_ids": ids,
        }
    )
    return {
        "type": "array",
        "minItems": len(assigned),
        "maxItems": len(assigned),
        "items": obj(
            {
                "record_id": record_id,
                "claims": {
                    "type": "array",
                    "maxItems": MAX_FACT_CLAIMS,
                    "items": claim,
                },
                "definitions": {"type": "array", "maxItems": 32, "items": definition},
                "references": {"type": "array", "maxItems": 32, "items": reference},
            }
        ),
        "$defs": {"condition": condition},
    }


def _validate_detail_numbers(detail, evidence, path):
    import re

    from .provision_validation import _amounts
    from .reader_integrity import (
        authorization_only_amounts,
        check_percentage_base,
        validate_numbers,
    )

    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for key, child in value.items():
                if key != "evidence_ids":
                    yield from strings(child)
        elif isinstance(value, list):
            for child in value:
                yield from strings(child)

    text = " ".join(strings(detail))
    quotes = [evidence[pid] for pid in record_evidence_ids(detail)]
    required_outlay = detail.get("modality") == "required" and re.search(
        r"\b(?:spend|allocate|appropriate|disburse)\b", detail.get("action", ""), re.I
    )
    for money in detail.get("money", []):
        amount = money.get("amount")
        if amount is not None:
            if str(money.get("currency") or "").lower() in {
                "usd",
                "$",
                "dollar",
                "dollars",
                "us dollars",
                "u.s. dollars",
            }:
                text += f" ${amount}"
                if required_outlay and _amounts(
                    f"${amount}"
                ) & authorization_only_amounts(
                    "\n".join(quote["quote"] for quote in quotes)
                ):
                    raise output_error("reader_amount_conflict", path)
            if str(money.get("measure") or "").lower() in {
                "%",
                "percent",
                "percentage",
            }:
                check_percentage_base(amount, money.get("base"), quotes, path)
                text += f" {amount}%"
    validate_numbers(
        {
            "text": text,
            "source_quotes": quotes,
        },
        path=path,
    )


def resolve_factual_records(records, sources, *, aggregate=False):
    """Validate complete ownership and original evidence, retaining typed facts."""
    # Bound recursive condition input before asking JSON Schema to walk it.
    record_evidence_ids(records)
    schema = factual_records_schema(sources, aggregate=aggregate)
    Draft202012Validator(schema).validate(records)
    expected = factual_record_ids(sources)
    actual = [record["record_id"] for record in records]
    if len(actual) != len(set(actual)) or set(actual) != set(expected):
        raise output_error(
            "reader_coverage_incomplete", ["source_review", "factual_records"]
        )
    evidence = factual_evidence(sources)
    for index, record in enumerate(records):
        path = ["source_review", "factual_records", index]
        if len(canonical_json_bytes(record)) > MAX_FACT_RECORD_BYTES:
            raise ValidationError(
                "factual_record_capacity", validator="maxLength", path=path
            )
        if not set(record_evidence_ids(record)) <= set(evidence):
            raise output_error("citation_reference_unknown", path)
        for category in ("claims", "definitions", "references"):
            for detail in record[category]:
                if record["record_id"] not in detail["evidence_ids"]:
                    raise output_error("reader_target_invalid", [*path, category])
                _validate_detail_numbers(detail, evidence, [*path, category])
    by_id = {record["record_id"]: record for record in records}
    return [copy.deepcopy(by_id[record_id]) for record_id in expected]
