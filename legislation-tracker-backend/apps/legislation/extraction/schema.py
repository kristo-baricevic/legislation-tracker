import json
import re
from collections import Counter
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .types import V2_SCHEMA_VERSION, V21_SCHEMA_VERSION, EvidenceCandidate

MAX_QUOTED_TEXT_LENGTH = 4_000
FIELD_PATH_SEGMENT = re.compile(r"^(?P<key>[a-z_][a-z0-9_]*)(?:\[(?P<index>\d+)\])?$")
SCHEMA_FILES = {
    V2_SCHEMA_VERSION: "contract_v2.json",
    V21_SCHEMA_VERSION: "contract_v2_1.json",
}


class ContractValidationError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@lru_cache(maxsize=len(SCHEMA_FILES))
def _load_schema(schema_version: str) -> dict[str, Any]:
    try:
        schema_file_name = SCHEMA_FILES[schema_version]
    except KeyError as error:
        raise ContractValidationError(
            "schema_validation_failed",
            f"Unsupported legal NLP schema version: {schema_version!r}",
        ) from error
    schema_path = Path(__file__).with_name("schemas") / schema_file_name
    with schema_path.open(encoding="utf-8") as schema_file:
        return json.load(schema_file)


def _format_schema_error(error: Any) -> str:
    location = ".".join(str(part) for part in error.absolute_path)
    if location:
        return f"{location}: {error.message}"
    return error.message


def _resolve_field_path(contract: dict[str, object], field_path: str) -> object:
    current: object = contract
    for segment in field_path.split("."):
        match = FIELD_PATH_SEGMENT.fullmatch(segment)
        if match is None or not isinstance(current, dict):
            raise KeyError(field_path)

        key = match.group("key")
        if key not in current:
            raise KeyError(field_path)
        current = current[key]

        index_text = match.group("index")
        if index_text is not None:
            if not isinstance(current, list):
                raise KeyError(field_path)
            index = int(index_text)
            if index >= len(current):
                raise KeyError(field_path)
            current = current[index]

    return current


def _required_v2_evidence_paths(contract: dict[str, object]) -> set[str]:
    paths = {"plain_summary"}
    visible_fields = {
        "key_provisions": ("text",),
        "requirements": ("display_text",),
        "funding_items": ("display_text",),
        "timeline_items": ("display_text",),
        "definitions": ("term", "display_text"),
        "applicability": ("display_text",),
        "amendment_operations": ("display_text",),
    }
    for category, fields in visible_fields.items():
        items = contract.get(category, [])
        if not isinstance(items, list):
            continue
        for index in range(len(items)):
            paths.update(f"{category}[{index}].{field}" for field in fields)
    return paths


def _visible_paths(
    contract: dict[str, object], category: str, fields: tuple[str, ...]
) -> set[str]:
    paths = set()
    items = contract.get(category, [])
    if not isinstance(items, list):
        return paths
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        for field in fields:
            value = item.get(field)
            if value is not None and value != []:
                paths.add(f"{category}[{index}].{field}")
    return paths


def _required_v21_evidence_paths(contract: dict[str, object]) -> set[str]:
    paths = set()
    orientation = contract.get("orientation")
    if isinstance(orientation, dict) and orientation.get("purpose_clause") is not None:
        paths.add("orientation.purpose_clause")
    categories = {
        "line_items": ("display_text", "actor", "action", "effect"),
        "financial_items": (
            "display_text",
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
            "display_text",
            "timeline_type",
            "date",
            "relative_value",
            "relative_unit",
            "trigger",
        ),
        "requirements": (
            "display_text",
            "modality",
            "actor",
            "action",
            "object",
            "conditions",
        ),
        "definitions": (
            "display_text",
            "term",
            "definition",
            "definition_type",
        ),
        "applicability": (
            "display_text",
            "subject",
            "scope",
            "applicability_type",
        ),
        "amendment_operations": (
            "display_text",
            "target",
            "operation",
            "removed_text",
            "inserted_text",
        ),
    }
    for category, fields in categories.items():
        paths.update(_visible_paths(contract, category, fields))
    return paths


def _required_evidence_paths(contract: dict[str, object]) -> set[str]:
    return (
        _required_v21_evidence_paths(contract)
        if contract.get("schema_version") == V21_SCHEMA_VERSION
        else _required_v2_evidence_paths(contract)
    )


def _declared_evidence_paths(contract: dict[str, object]) -> set[str]:
    paths = set()
    for category in (
        "line_items",
        "financial_items",
        "timeline_items",
        "requirements",
        "definitions",
        "applicability",
        "amendment_operations",
    ):
        items = contract.get(category, [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            evidence_paths = item.get("evidence_paths", [])
            if isinstance(evidence_paths, list):
                paths.update(path for path in evidence_paths if isinstance(path, str))
    return paths


def _validate_evidence(
    contract: dict[str, object],
    evidence: Iterable[EvidenceCandidate],
    source_text: str,
) -> None:
    evidenced_paths: set[str] = set()
    for candidate in evidence:
        try:
            _resolve_field_path(contract, candidate.field_path)
        except KeyError as error:
            raise ContractValidationError(
                "evidence_validation_failed",
                f"Evidence field path {candidate.field_path!r} does not resolve",
            ) from error

        if not candidate.quoted_text:
            raise ContractValidationError(
                "evidence_validation_failed", "Evidence quoted text cannot be empty"
            )
        if len(candidate.quoted_text) > MAX_QUOTED_TEXT_LENGTH:
            raise ContractValidationError(
                "evidence_validation_failed",
                "Evidence quoted text cannot exceed 4,000 characters",
            )
        if not (0 <= candidate.start_char < candidate.end_char <= len(source_text)):
            raise ContractValidationError(
                "evidence_validation_failed",
                f"Evidence span for {candidate.field_path!r} is outside source text",
            )
        if (
            source_text[candidate.start_char : candidate.end_char]
            != candidate.quoted_text
        ):
            raise ContractValidationError(
                "evidence_validation_failed",
                f"Evidence quote for {candidate.field_path!r} does not match source text",
            )
        evidenced_paths.add(candidate.field_path)

    missing_paths = sorted(
        (_required_evidence_paths(contract) | _declared_evidence_paths(contract))
        - evidenced_paths,
        key=lambda path: (path.endswith(".display_text"), path),
    )
    if missing_paths:
        raise ContractValidationError(
            "evidence_validation_failed",
            f"Missing evidence for visible field {missing_paths[0]}",
        )


def _item_map(contract: dict[str, object], category: str) -> dict[str, dict]:
    items = contract.get(category, [])
    if not isinstance(items, list):
        return {}
    return {
        str(item["id"]): item
        for item in items
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def _validate_unique_ids(category: str, items: list[object]) -> None:
    ids = [item.get("id") for item in items if isinstance(item, dict)]
    if len(ids) != len(set(ids)):
        raise ContractValidationError(
            "schema_validation_failed", f"{category} IDs must be unique"
        )


def _require_refs(refs: object, targets: dict[str, dict], *, location: str) -> None:
    if not isinstance(refs, list):
        return
    for ref in refs:
        if ref not in targets:
            raise ContractValidationError(
                "schema_validation_failed",
                f"Reference {ref!r} at {location} does not resolve",
            )


def _validate_financial_axes(financial: dict[str, dict]) -> None:
    directions = {
        "appropriation": "increase",
        "authorization": "increase",
        "allocation": "increase",
        "transfer": "neutral_transfer",
        "rescission": "decrease",
        "reduction": "decrease",
        "cancellation": "decrease",
        "set_aside": "limit",
        "limitation": "limit",
        "other_explicit": "increase",
    }
    for item in financial.values():
        action = item.get("financial_action")
        amount_type = item.get("amount_type")
        amount = item.get("amount")
        currency = item.get("currency")
        valid_amount = {
            "specified": amount is not None and currency == "USD",
            "such_sums": amount is None and currency is None,
            "percentage": amount is not None and currency is None,
            "ceiling": amount is not None and currency in {"USD", None},
        }.get(str(amount_type), False)
        valid_transfer = action != "transfer" or (
            item.get("source_account") is not None
            and item.get("destination_account") is not None
        )
        valid_limitation = action != "limitation" or amount_type == "ceiling"
        if (
            item.get("direction") != directions.get(str(action))
            or not valid_amount
            or not valid_transfer
            or not valid_limitation
        ):
            raise ContractValidationError(
                "schema_validation_failed",
                f"Financial item {item.get('id')!r} has inconsistent financial axes",
            )


def _validate_v21_references(contract: dict[str, object]) -> None:
    line_items = contract.get("line_items", [])
    section_groups = contract.get("section_groups", [])
    if not isinstance(line_items, list) or not isinstance(section_groups, list):
        return
    for category in (
        "line_items",
        "financial_items",
        "timeline_items",
        "requirements",
        "definitions",
        "applicability",
        "amendment_operations",
    ):
        items = contract.get(category, [])
        if isinstance(items, list):
            _validate_unique_ids(category, items)

    lines = _item_map(contract, "line_items")
    financial = _item_map(contract, "financial_items")
    timelines = _item_map(contract, "timeline_items")
    definitions = _item_map(contract, "definitions")
    claims = {
        **financial,
        **timelines,
        **definitions,
        **_item_map(contract, "requirements"),
        **_item_map(contract, "applicability"),
        **_item_map(contract, "amendment_operations"),
    }
    _validate_financial_axes(financial)
    line_memberships = Counter(
        line_id
        for group in section_groups
        if isinstance(group, dict)
        for line_id in group.get("line_item_ids", [])
    )
    if any(line_memberships[line_id] != 1 for line_id in lines):
        raise ContractValidationError(
            "schema_validation_failed",
            "Every reader line must belong to exactly one section group",
        )
    groups = {
        str(item["source_id"]): item
        for item in section_groups
        if isinstance(item, dict) and isinstance(item.get("source_id"), str)
    }
    if len(groups) != len(section_groups):
        raise ContractValidationError(
            "schema_validation_failed", "section group source IDs must be unique"
        )

    financial_associations: list[str] = []
    timeline_associations: list[str] = []
    for index, item in enumerate(line_items):
        if not isinstance(item, dict):
            continue
        section_id = item.get("section_id")
        if section_id not in groups:
            raise ContractValidationError(
                "schema_validation_failed",
                f"Line item section {section_id!r} does not resolve",
            )
        _require_refs(item.get("claim_refs"), claims, location=f"line_items[{index}]")
        _require_refs(
            item.get("exact_financial_refs"),
            financial,
            location=f"line_items[{index}].exact_financial_refs",
        )
        _require_refs(
            item.get("timeline_refs"),
            timelines,
            location=f"line_items[{index}].timeline_refs",
        )
        _require_refs(
            item.get("definition_refs"),
            definitions,
            location=f"line_items[{index}].definition_refs",
        )
        for reference in (
            *item.get("claim_refs", []),
            *item.get("exact_financial_refs", []),
            *item.get("timeline_refs", []),
        ):
            if claims[reference].get("section_id") != section_id:
                raise ContractValidationError(
                    "schema_validation_failed",
                    f"Reference {reference!r} belongs to a different section",
                )
        financial_associations.extend(item.get("exact_financial_refs", []))
        timeline_associations.extend(item.get("timeline_refs", []))

    for index, group in enumerate(section_groups):
        if not isinstance(group, dict):
            continue
        _require_refs(
            group.get("line_item_ids"),
            lines,
            location=f"section_groups[{index}].line_item_ids",
        )
        _require_refs(
            group.get("section_financial_refs"),
            financial,
            location=f"section_groups[{index}].section_financial_refs",
        )
        _require_refs(
            group.get("section_timeline_refs"),
            timelines,
            location=f"section_groups[{index}].section_timeline_refs",
        )
        for line_id in group.get("line_item_ids", []):
            if lines[line_id].get("section_id") != group.get("source_id"):
                raise ContractValidationError(
                    "schema_validation_failed",
                    f"Line item {line_id!r} belongs to a different section",
                )
        for reference in (
            *group.get("section_financial_refs", []),
            *group.get("section_timeline_refs", []),
        ):
            if claims[reference].get("section_id") != group.get("source_id"):
                raise ContractValidationError(
                    "schema_validation_failed",
                    f"Reference {reference!r} belongs to a different section",
                )
        financial_associations.extend(group.get("section_financial_refs", []))
        timeline_associations.extend(group.get("section_timeline_refs", []))

    if sorted(financial_associations) != sorted(financial):
        raise ContractValidationError(
            "schema_validation_failed",
            "Every financial item must have exactly one reader association",
        )
    if sorted(timeline_associations) != sorted(timelines):
        raise ContractValidationError(
            "schema_validation_failed",
            "Every timeline item must have exactly one reader association",
        )

    orientation = contract.get("orientation")
    if isinstance(orientation, dict):
        purpose_id = orientation.get("purpose_line_item_id")
        purpose_clause = orientation.get("purpose_clause")
        if purpose_id is not None:
            line = lines.get(str(purpose_id))
            if line is None:
                raise ContractValidationError(
                    "schema_validation_failed",
                    f"Purpose line item {purpose_id!r} does not resolve",
                )
            if line.get("display_text") != purpose_clause:
                raise ContractValidationError(
                    "schema_validation_failed",
                    "Purpose clause must use the same controlled text as its line item",
                )

    stats = contract.get("reader_stats")
    if isinstance(stats, dict):
        expected_counts = {
            "line_item_count": len(lines),
            "financial_item_count": len(financial),
            "timeline_item_count": len(timelines),
            "definition_item_count": len(definitions),
            "section_group_count": len(groups),
        }
        if any(stats.get(key) != value for key, value in expected_counts.items()):
            raise ContractValidationError(
                "schema_validation_failed", "Reader statistics do not match arrays"
            )


def validate_contract(
    contract: dict[str, object],
    evidence: Iterable[EvidenceCandidate],
    source_text: str,
) -> None:
    schema_version = contract.get("schema_version")
    if not isinstance(schema_version, str):
        raise ContractValidationError(
            "schema_validation_failed", "schema_version must be a string"
        )
    validator = Draft202012Validator(_load_schema(schema_version))
    errors = sorted(
        validator.iter_errors(contract),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    if errors:
        raise ContractValidationError(
            "schema_validation_failed", _format_schema_error(errors[0])
        )

    if schema_version == V21_SCHEMA_VERSION:
        _validate_v21_references(contract)

    _validate_evidence(contract, evidence, source_text)
