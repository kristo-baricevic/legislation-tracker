import json
from collections.abc import Callable, Sequence
from decimal import Decimal

from .schema import validate_contract
from .types import (
    SCHEMA_VERSION,
    EvidenceCandidate,
    ExtractedClaim,
    ExtractionResult,
    StructuralSection,
)

_CATEGORY_ORDER = {
    "requirements": 0,
    "amendment_operations": 1,
    "funding_items": 2,
    "timeline_items": 3,
    "definitions": 4,
    "applicability": 5,
}
_KEY_KINDS = {
    "requirements": "requirement",
    "amendment_operations": "amendment",
    "funding_items": "funding",
    "timeline_items": "timeline",
    "definitions": "definition",
    "applicability": "applicability",
}
_CATEGORY_LIMIT = 100
_KEY_PROVISION_LIMIT = 10


def _punctuate(text: str) -> str:
    stripped = text.strip()
    return stripped if stripped.endswith((".", "?", "!")) else f"{stripped}."


def _render_requirement(fields: dict[str, object]) -> str:
    actor = fields["actor"]
    action = fields["action"]
    templates = {
        "required": f"{actor} is required to {action}",
        "prohibited": f"{actor} is prohibited from {action}",
        "permitted": f"{actor} is authorized to {action}",
    }
    text = templates[str(fields["modality"])]
    conditions = fields.get("conditions") or []
    if conditions:
        text = f"{text}, {'; '.join(str(value) for value in conditions)}"
    return _punctuate(text)


def _money(amount: object) -> str:
    return f"${Decimal(str(amount)):,.2f}"


def _fiscal_year_phrase(years: object) -> str | None:
    if not isinstance(years, list) or not years:
        return None
    if len(years) == 1:
        return f"fiscal year {years[0]}"
    return f"fiscal years {years[0]} through {years[-1]}"


def _render_funding(fields: dict[str, object]) -> str:
    if fields["amount_type"] == "such_sums":
        text = "Funding consists of such sums as may be necessary"
    else:
        text = f"Funding of {_money(fields['amount'])} is specified"
    fiscal_years = _fiscal_year_phrase(fields.get("fiscal_years"))
    if fiscal_years:
        text = f"{text} for {fiscal_years}"
    if fields.get("purpose"):
        text = f"{text} for {fields['purpose']}"
    return _punctuate(text)


def _render_timeline(fields: dict[str, object]) -> str:
    timeline_type = fields["timeline_type"]
    if timeline_type == "relative":
        return _punctuate(
            f"A deadline occurs {fields['relative_value']} {fields['relative_unit']} "
            f"after {fields['trigger']}"
        )
    if timeline_type == "effective":
        if fields.get("date"):
            return f"The provision takes effect on {fields['date']}."
        return "The provision takes effect."
    return f"A relevant date is {fields['date']}."


def _render_definition(fields: dict[str, object]) -> str:
    return _punctuate(
        f"“{fields['term']}” {fields['definition_type']} {fields['definition']}"
    )


def _render_applicability(fields: dict[str, object]) -> str:
    applicability_type = fields["applicability_type"]
    if applicability_type == "applies":
        text = f"{fields['subject']} applies to {fields['scope']}"
    elif applicability_type == "does_not_apply":
        text = f"{fields['subject']} does not apply to {fields['scope']}"
    elif applicability_type == "eligible":
        text = f"{fields['subject']} includes {fields['scope']}"
    else:
        text = f"{fields['subject']} excludes {fields['scope']}"
    return _punctuate(text)


def _quoted(value: object) -> str:
    return f"“{value}”"


def _render_amendment(fields: dict[str, object]) -> str:
    target = str(fields["target"]) if fields.get("target") else ""
    prefix = f"{target} " if target else ""
    operation = fields["operation"]
    removed = fields.get("removed_text")
    inserted = fields.get("inserted_text")
    if operation == "replace":
        if removed and inserted:
            text = f"{prefix}replaces {_quoted(removed)} with {_quoted(inserted)}"
        elif inserted:
            text = f"{prefix}replaces text with {_quoted(inserted)}"
        elif removed:
            text = f"{prefix}replaces {_quoted(removed)}"
        else:
            text = f"{prefix}is replaced"
    elif operation == "strike_and_insert":
        if removed and inserted:
            text = f"{prefix}strikes {_quoted(removed)} and inserts {_quoted(inserted)}"
        else:
            text = f"{prefix}strikes and inserts text"
    elif operation == "strike":
        text = f"{prefix}strikes {_quoted(removed)}" if removed else f"{prefix}strikes text"
    elif operation in {"add", "insert"}:
        verb = "adds" if operation == "add" else "inserts"
        payload = _quoted(inserted) if inserted else "text"
        text = f"{prefix}{verb} {payload}"
    elif operation == "redesignate":
        text = f"{prefix}is redesignated"
    elif operation == "repeal":
        text = f"{prefix}is repealed"
    else:
        text = f"{prefix}is amended"
    return _punctuate(text.strip())


_RENDERERS: dict[str, Callable[[dict[str, object]], str]] = {
    "requirements": _render_requirement,
    "funding_items": _render_funding,
    "timeline_items": _render_timeline,
    "definitions": _render_definition,
    "applicability": _render_applicability,
    "amendment_operations": _render_amendment,
}


def _claim_key(claim: ExtractedClaim) -> tuple[object, ...]:
    evidence_offsets = tuple(
        (evidence.start_char, evidence.end_char) for evidence in claim.evidence
    )
    fields = json.dumps(claim.fields, sort_keys=True, separators=(",", ":"))
    return claim.category, fields, evidence_offsets


def _ordered_unique_claims(
    claims: Sequence[ExtractedClaim],
) -> tuple[ExtractedClaim, ...]:
    ordered = sorted(
        claims,
        key=lambda claim: (
            claim.evidence[0].start_char,
            _CATEGORY_ORDER[claim.category],
        ),
    )
    seen = set()
    unique = []
    for claim in ordered:
        key = _claim_key(claim)
        if key not in seen:
            seen.add(key)
            unique.append(claim)
    return tuple(unique)


def _evidence_for(path: str, claim: ExtractedClaim) -> list[EvidenceCandidate]:
    return [
        EvidenceCandidate(
            field_path=path,
            quoted_text=span.text,
            start_char=span.start_char,
            end_char=span.end_char,
        )
        for span in claim.evidence
    ]


def _summary_claims(claims: Sequence[ExtractedClaim]) -> tuple[ExtractedClaim, ...]:
    selected = []
    for categories in (
        {"requirements", "amendment_operations"},
        {"funding_items"},
        {"timeline_items"},
    ):
        match = next((claim for claim in claims if claim.category in categories), None)
        if match is not None and match not in selected:
            selected.append(match)
    for claim in claims:
        if len(selected) >= 3:
            break
        if claim not in selected:
            selected.append(claim)
    return tuple(selected[:3])


def render_contract(
    *,
    title: str,
    version_label: str,
    sections: Sequence[StructuralSection],
    claims: Sequence[ExtractedClaim],
    source_text: str,
) -> ExtractionResult:
    ordered_claims = _ordered_unique_claims(claims)
    warnings = []
    stored_by_category = {}
    for category in _CATEGORY_ORDER:
        category_claims = [
            claim for claim in ordered_claims if claim.category == category
        ]
        if len(category_claims) > _CATEGORY_LIMIT:
            warnings.append(f"item_limit_reached:{category}")
        stored_by_category[category] = category_claims[:_CATEGORY_LIMIT]

    stored_claims = tuple(
        claim
        for claim in ordered_claims
        if claim in stored_by_category[claim.category]
    )
    display_by_identity = {
        id(claim): _RENDERERS[claim.category](claim.fields) for claim in stored_claims
    }
    heading_by_label = {section.label: section.heading for section in sections}
    evidence = []
    contract_categories: dict[str, list[dict[str, object]]] = {
        category: [] for category in _CATEGORY_ORDER
    }

    for category in _CATEGORY_ORDER:
        for index, claim in enumerate(stored_by_category[category]):
            item = {
                "section_label": claim.section_label,
                "display_text": display_by_identity[id(claim)],
                **claim.fields,
            }
            contract_categories[category].append(item)
            evidence.extend(_evidence_for(f"{category}[{index}].display_text", claim))
            if category == "definitions":
                evidence.extend(_evidence_for(f"definitions[{index}].term", claim))

    key_provisions = []
    for index, claim in enumerate(stored_claims[:_KEY_PROVISION_LIMIT]):
        key_provisions.append(
            {
                "kind": _KEY_KINDS[claim.category],
                "section_label": claim.section_label,
                "heading": heading_by_label.get(claim.section_label),
                "text": display_by_identity[id(claim)],
            }
        )
        evidence.extend(_evidence_for(f"key_provisions[{index}].text", claim))

    summary_claims = _summary_claims(stored_claims)
    plain_summary = " ".join(display_by_identity[id(claim)] for claim in summary_claims)
    for claim in summary_claims:
        evidence.extend(_evidence_for("plain_summary", claim))

    contract_json: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "title": title,
        "version_label": version_label,
        "extraction": {
            "method": "federal-rules",
            "parser_version": "2.0.0",
            "sections_seen": len(sections),
            "sections_with_claims": len(
                {claim.section_label for claim in stored_claims if claim.section_label}
            ),
            "warnings": warnings,
        },
        "plain_summary": plain_summary,
        "key_provisions": key_provisions,
        **contract_categories,
        "limitations": [
            "This automated summary is based on explicit patterns in the bill text and is not legal advice."
        ],
    }
    validate_contract(contract_json, evidence, source_text)
    return ExtractionResult(
        schema_version=SCHEMA_VERSION,
        contract_json=contract_json,
        evidence=tuple(evidence),
        method="federal-rules",
    )
