"""Controlled reader rendering and immutable 2.1 contract assembly."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from .display_text import normalize_reader_fragment
from .schema import validate_contract
from .types import (
    V21_EXTRACTOR_VERSION,
    V21_SCHEMA_VERSION,
    EvidenceCandidate,
    ExtractedClaim,
    ExtractionResult,
    ExtractionWarning,
    IdentifiedClaim,
    ReaderLineItem,
    RenderedReaderClaim,
    SectionPathItem,
    SourceSpan,
    StructuralSection,
)


def _clean(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = normalize_reader_fragment(value).strip()
    return cleaned or None


def _warning(claim: ExtractedClaim) -> ExtractionWarning:
    return ExtractionWarning(
        code="reader_required_slot_missing",
        rule_id=claim.rule_id,
        source_id=claim.source_id,
        evidence=claim.evidence,
    )


def _money(value: object) -> str:
    return f"${Decimal(str(value)):,.2f}"


def _number(value: object) -> str:
    decimal = Decimal(str(value))
    return format(decimal.normalize(), "f")


def _fiscal_phrase(value: object) -> str | None:
    if not isinstance(value, list) or not value:
        return None
    if len(value) == 1:
        return f"for fiscal year {value[0]}"
    return f"for fiscal years {value[0]} through {value[-1]}"


def _gerund_phrase(action: str) -> str:
    verb, separator, remainder = action.partition(" ")
    lowered = verb.casefold()
    irregular = {
        "be": "being",
        "have": "having",
        "make": "making",
        "set": "setting",
        "submit": "submitting",
        "transfer": "transferring",
    }
    if lowered in irregular:
        gerund = irregular[lowered]
    elif lowered.endswith("ie"):
        gerund = f"{lowered[:-2]}ying"
    elif lowered.endswith("e") and not lowered.endswith("ee"):
        gerund = f"{lowered[:-1]}ing"
    else:
        gerund = f"{lowered}ing"
    return f"{gerund}{separator}{remainder}"


def _render_requirement(
    claim: ExtractedClaim,
) -> RenderedReaderClaim | ExtractionWarning:
    actor = _clean(claim.fields.get("actor"))
    action = _clean(claim.fields.get("action"))
    modality = claim.fields.get("modality")
    if (
        actor is None
        or action is None
        or modality
        not in {
            "required",
            "prohibited",
            "permitted",
        }
    ):
        return _warning(claim)
    if modality == "prohibited":
        kind = "prohibition"
        text = f"Prohibits {actor} from {_gerund_phrase(action)}"
    else:
        kind, verb = {
            "required": ("requirement", "Requires"),
            "permitted": ("permission", "Allows"),
        }[str(modality)]
        text = f"{verb} {actor} to {action}"
    conditions = claim.fields.get("conditions")
    if isinstance(conditions, list):
        cleaned_conditions = [_clean(item) for item in conditions]
        text += (
            " " + " and ".join(item for item in cleaned_conditions if item is not None)
            if any(cleaned_conditions)
            else ""
        )
    return RenderedReaderClaim(
        kind=kind,
        display_text=f"{text.rstrip('.')}.",
        actor=actor,
        action=action,
        effect=_clean(claim.fields.get("object")),
    )


def _render_amendment(
    claim: ExtractedClaim,
) -> RenderedReaderClaim | ExtractionWarning:
    target = _clean(claim.fields.get("target"))
    operation = claim.fields.get("operation")
    if target is None or operation not in {
        "add",
        "insert",
        "strike",
        "strike_and_insert",
        "replace",
        "redesignate",
        "repeal",
        "amend",
    }:
        return _warning(claim)
    removed = _clean(claim.fields.get("removed_text"))
    inserted = _clean(claim.fields.get("inserted_text"))
    if operation == "replace" and removed and inserted:
        detail = f"replacing “{removed}” with “{inserted}”"
    elif operation == "strike_and_insert" and removed and inserted:
        detail = f"striking “{removed}” and inserting “{inserted}”"
    elif operation == "strike" and removed:
        detail = f"striking “{removed}”"
    elif operation in {"add", "insert"} and inserted:
        verb = "adding" if operation == "add" else "inserting"
        detail = f"{verb} “{inserted}”"
    elif operation == "redesignate":
        detail = "redesignating the provision"
    elif operation == "repeal":
        detail = "repealing the provision"
    elif operation == "amend":
        detail = "amending the provision"
    else:
        return _warning(claim)
    return RenderedReaderClaim(
        kind="amendment",
        display_text=f"Changes {target} by {detail}.",
        actor=None,
        action=str(operation),
        effect=inserted or removed,
    )


def _render_applicability(
    claim: ExtractedClaim,
) -> RenderedReaderClaim | ExtractionWarning:
    subject = _clean(claim.fields.get("subject"))
    scope = _clean(claim.fields.get("scope"))
    applicability_type = claim.fields.get("applicability_type")
    if (
        subject is None
        or scope is None
        or applicability_type
        not in {
            "applies",
            "does_not_apply",
            "eligible",
            "excluded",
        }
    ):
        return _warning(claim)
    templates = {
        "applies": ("apply", f"Applies {subject} to {scope}."),
        "does_not_apply": (
            "does_not_apply",
            f"Does not apply {subject} to {scope}.",
        ),
        "eligible": ("include", f"Includes {scope} within {subject}."),
        "excluded": ("exclude", f"Excludes {scope} from {subject}."),
    }
    action, display = templates[str(applicability_type)]
    return RenderedReaderClaim(
        kind="applicability",
        display_text=display,
        actor=subject,
        action=action,
        effect=scope,
    )


def _render_financial(
    claim: ExtractedClaim,
) -> RenderedReaderClaim | ExtractionWarning:
    fields = claim.fields
    action = fields.get("financial_action")
    amount_type = fields.get("amount_type")
    direction = fields.get("direction")
    if action not in {
        "appropriation",
        "authorization",
        "allocation",
        "transfer",
        "rescission",
        "reduction",
        "cancellation",
        "set_aside",
        "limitation",
        "other_explicit",
    } or direction not in {"increase", "decrease", "neutral_transfer", "limit"}:
        return _warning(claim)
    amount = fields.get("amount")
    currency = fields.get("currency")
    if amount_type == "such_sums":
        amount_text = "such sums as may be necessary"
    elif amount_type in {"specified", "ceiling"} and amount is not None:
        amount_text = _money(amount) if currency == "USD" else _number(amount)
    elif amount_type == "percentage" and amount is not None:
        amount_text = f"{_number(amount)} percent"
    else:
        return _warning(claim)

    source_account = _clean(fields.get("source_account"))
    destination_account = _clean(fields.get("destination_account"))
    if action == "transfer" and (source_account is None or destination_account is None):
        return _warning(claim)

    verbs = {
        "appropriation": "Appropriates",
        "authorization": "Authorizes",
        "allocation": "Allocates",
        "transfer": "Transfers",
        "rescission": "Rescinds",
        "reduction": "Reduces available funding by",
        "cancellation": "Cancels",
        "set_aside": "Sets aside",
        "limitation": "Limits funding to no more than",
        "other_explicit": "Makes available",
    }
    text = f"{verbs[str(action)]} {amount_text}"
    if action == "transfer":
        text += f" from {source_account} to {destination_account}"
    purpose = _clean(fields.get("purpose"))
    if purpose:
        text += f" for {purpose}"
    fiscal_phrase = _fiscal_phrase(fields.get("fiscal_years"))
    if fiscal_phrase:
        text += f" {fiscal_phrase}"
    return RenderedReaderClaim(
        kind="financial",
        display_text=f"{text.rstrip('.')}.",
        actor=None,
        action=str(action),
        effect=purpose or destination_account,
    )


def _render_timeline(
    claim: ExtractedClaim,
) -> RenderedReaderClaim | ExtractionWarning:
    fields = claim.fields
    timeline_type = fields.get("timeline_type")
    if timeline_type == "relative":
        value = fields.get("relative_value")
        unit = _clean(fields.get("relative_unit"))
        trigger = _clean(fields.get("trigger"))
        if not isinstance(value, int) or unit is None or trigger is None:
            return _warning(claim)
        display = f"Sets a deadline {value} {unit} after {trigger}."
        effect = trigger
    elif timeline_type == "absolute":
        date = _clean(fields.get("date"))
        if date is None:
            return _warning(claim)
        display = f"Sets a relevant date of {date}."
        effect = date
    elif timeline_type == "effective":
        date = _clean(fields.get("date"))
        display = f"Takes effect on {date}." if date else "Takes effect."
        effect = date
    else:
        return _warning(claim)
    return RenderedReaderClaim(
        kind="timeline",
        display_text=display,
        actor=None,
        action=str(timeline_type),
        effect=effect,
    )


def _render_definition(
    claim: ExtractedClaim,
) -> RenderedReaderClaim | ExtractionWarning:
    term = _clean(claim.fields.get("term"))
    definition = _clean(claim.fields.get("definition"))
    definition_type = claim.fields.get("definition_type")
    if (
        term is None
        or definition is None
        or definition_type
        not in {
            "means",
            "includes",
            "excludes",
        }
    ):
        return _warning(claim)
    connector = {
        "means": "to mean",
        "includes": "to include",
        "excludes": "to exclude",
    }[str(definition_type)]
    return RenderedReaderClaim(
        kind="definition",
        display_text=f"Defines “{term}” {connector} {definition.rstrip('.')}.",
        actor=None,
        action="define",
        effect=definition,
    )


def render_reader_claim(
    claim: ExtractedClaim,
) -> RenderedReaderClaim | ExtractionWarning:
    renderers = {
        "requirements": _render_requirement,
        "amendment_operations": _render_amendment,
        "applicability": _render_applicability,
        "financial_items": _render_financial,
        "timeline_items": _render_timeline,
        "definitions": _render_definition,
    }
    renderer = renderers.get(claim.category)
    return renderer(claim) if renderer is not None else _warning(claim)


def split_evidence_span(
    span: SourceSpan, max_chars: int = 4_000
) -> tuple[SourceSpan, ...]:
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if span.end_char - span.start_char != len(span.text):
        raise ValueError("source span offsets must match its exact text length")
    return tuple(
        SourceSpan(
            text=span.text[offset : offset + max_chars],
            start_char=span.start_char + offset,
            end_char=span.start_char + min(offset + max_chars, len(span.text)),
        )
        for offset in range(0, len(span.text), max_chars)
    )


def _path_json(path: Sequence[SectionPathItem]) -> list[dict[str, object]]:
    return [
        {"level": item.level, "label": item.label, "heading": item.heading}
        for item in path
    ]


def _evidence_candidates(
    field_path: str, spans: Sequence[SourceSpan]
) -> list[EvidenceCandidate]:
    return [
        EvidenceCandidate(
            field_path=field_path,
            quoted_text=chunk.text,
            start_char=chunk.start_char,
            end_char=chunk.end_char,
        )
        for span in spans
        for chunk in split_evidence_span(span)
    ]


def _present_paths(
    category: str,
    index: int,
    item: dict[str, object],
    fields: Sequence[str],
) -> list[str]:
    return [
        f"{category}[{index}].{field}"
        for field in fields
        if item.get(field) is not None and item.get(field) != []
    ]


def _normalized_item(
    identified: IdentifiedClaim,
    *,
    category: str,
    index: int,
    rendered: RenderedReaderClaim,
    fields: Sequence[str],
) -> dict[str, object]:
    claim = identified.claim
    item = {
        "id": identified.id,
        "source_id": identified.id,
        "section_id": claim.section_id or claim.source_id,
        "section_label": claim.section_label,
        "section_path": _path_json(claim.section_path),
        "display_text": rendered.display_text,
        **claim.fields,
    }
    item["evidence_paths"] = _present_paths(
        category, index, item, ("display_text", *fields)
    )
    return item


def _line_item_json(
    line: ReaderLineItem,
    *,
    index: int,
    claim_display_paths: dict[str, str],
) -> dict[str, object]:
    item = {
        "id": line.id,
        "source_id": line.source_id,
        "section_id": line.section_id,
        "section_path": _path_json(line.section_path),
        "kind": line.kind,
        "display_text": line.display_text,
        "actor": line.actor,
        "action": line.action,
        "effect": line.effect,
        "claim_refs": list(line.claim_refs),
        "exact_financial_refs": list(line.exact_financial_refs),
        "timeline_refs": list(line.timeline_refs),
        "definition_refs": list(line.definition_refs),
    }
    own_paths = _present_paths(
        "line_items", index, item, ("display_text", "actor", "action", "effect")
    )
    item["evidence_paths"] = own_paths + [
        claim_display_paths[claim_ref]
        for claim_ref in line.claim_refs
        if claim_ref in claim_display_paths
    ]
    return item


def render_contract(
    *,
    title: str,
    version_label: str,
    sections: Sequence[StructuralSection],
    claims: Sequence[ExtractedClaim],
    source_text: str,
) -> ExtractionResult:
    from .reader_brief import build_reader_brief

    brief = build_reader_brief(claims, sections)
    evidence = []
    warnings = list(brief.warnings)
    contract_categories: dict[str, list[dict[str, object]]] = {
        "financial_items": [],
        "timeline_items": [],
        "requirements": [],
        "definitions": [],
        "applicability": [],
        "amendment_operations": [],
    }
    category_fields = {
        "financial_items": (
            "financial_action",
            "direction",
            "amount",
            "amount_type",
            "currency",
            "fiscal_years",
            "purpose",
            "source_account",
            "destination_account",
        ),
        "timeline_items": (
            "timeline_type",
            "date",
            "relative_value",
            "relative_unit",
            "trigger",
        ),
        "requirements": (
            "modality",
            "actor",
            "action",
            "object",
            "conditions",
        ),
        "definitions": ("term", "definition", "definition_type"),
        "applicability": ("subject", "scope", "applicability_type"),
        "amendment_operations": (
            "target",
            "operation",
            "removed_text",
            "inserted_text",
        ),
    }
    claim_display_paths = {}
    for identified in brief.identified_claims:
        category = identified.claim.category
        if category not in contract_categories:
            continue
        rendered = render_reader_claim(identified.claim)
        if isinstance(rendered, ExtractionWarning):
            warnings.append(rendered)
            continue
        index = len(contract_categories[category])
        item = _normalized_item(
            identified,
            category=category,
            index=index,
            rendered=rendered,
            fields=category_fields[category],
        )
        contract_categories[category].append(item)
        claim_display_paths[identified.id] = f"{category}[{index}].display_text"
        for field_path in item["evidence_paths"]:
            evidence.extend(_evidence_candidates(field_path, identified.claim.evidence))

    line_items = []
    for index, line in enumerate(brief.line_items):
        item = _line_item_json(
            line,
            index=index,
            claim_display_paths=claim_display_paths,
        )
        line_items.append(item)
        for field_path in _present_paths(
            "line_items",
            index,
            item,
            ("display_text", "actor", "action", "effect"),
        ):
            evidence.extend(_evidence_candidates(field_path, line.evidence))

    orientation = {
        "purpose_clause": brief.orientation.purpose_clause,
        "purpose_line_item_id": brief.orientation.purpose_line_item_id,
    }
    contract_json: dict[str, object] = {
        "schema_version": V21_SCHEMA_VERSION,
        "title": title,
        "version_label": version_label,
        "extraction": {
            "method": "federal-rules",
            "parser_version": "2.1.0",
            "extractor_version": V21_EXTRACTOR_VERSION,
            "sections_seen": len(sections),
            "sections_with_claims": len(
                {
                    item.claim.section_id or item.claim.source_id
                    for item in brief.identified_claims
                }
            ),
            "warnings": list(dict.fromkeys(item.code for item in warnings)),
        },
        "coverage_note": brief.coverage_note,
        "orientation": orientation,
        "reader_stats": {
            "line_item_count": brief.reader_stats.line_item_count,
            "financial_item_count": brief.reader_stats.financial_item_count,
            "timeline_item_count": brief.reader_stats.timeline_item_count,
            "definition_item_count": brief.reader_stats.definition_item_count,
            "section_group_count": brief.reader_stats.section_group_count,
        },
        "section_groups": [
            {
                "source_id": group.source_id,
                "section_path": _path_json(group.section_path),
                "line_item_ids": list(group.line_item_ids),
                "section_financial_refs": list(group.section_financial_refs),
                "section_timeline_refs": list(group.section_timeline_refs),
            }
            for group in brief.section_groups
        ],
        "line_items": line_items,
        **contract_categories,
        "limitations": [
            "This deterministic breakdown covers recognized explicit provisions and is not legal advice or a budget estimate."
        ],
    }
    if orientation["purpose_clause"] is not None:
        purpose_line = next(
            line
            for line in brief.line_items
            if line.id == orientation["purpose_line_item_id"]
        )
        evidence.extend(
            _evidence_candidates("orientation.purpose_clause", purpose_line.evidence)
        )
    validate_contract(contract_json, evidence, source_text)
    return ExtractionResult(
        schema_version=V21_SCHEMA_VERSION,
        contract_json=contract_json,
        evidence=tuple(evidence),
        method="federal-rules",
    )
