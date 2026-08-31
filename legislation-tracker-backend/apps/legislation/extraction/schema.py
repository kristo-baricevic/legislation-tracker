import json
import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .types import EvidenceCandidate

MAX_QUOTED_TEXT_LENGTH = 4_000
FIELD_PATH_SEGMENT = re.compile(r"^(?P<key>[a-z_][a-z0-9_]*)(?:\[(?P<index>\d+)\])?$")


class ContractValidationError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@lru_cache(maxsize=1)
def _load_schema() -> dict[str, Any]:
    schema_path = Path(__file__).with_name("schemas") / "contract_v2.json"
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


def _required_evidence_paths(contract: dict[str, object]) -> set[str]:
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
        _required_evidence_paths(contract) - evidenced_paths,
        key=lambda path: (path.endswith(".display_text"), path),
    )
    if missing_paths:
        raise ContractValidationError(
            "evidence_validation_failed",
            f"Missing evidence for visible field {missing_paths[0]}",
        )


def validate_contract(
    contract: dict[str, object],
    evidence: Iterable[EvidenceCandidate],
    source_text: str,
) -> None:
    validator = Draft202012Validator(_load_schema())
    errors = sorted(
        validator.iter_errors(contract),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    if errors:
        raise ContractValidationError(
            "schema_validation_failed", _format_schema_error(errors[0])
        )

    _validate_evidence(contract, evidence, source_text)
