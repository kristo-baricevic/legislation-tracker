from dataclasses import dataclass

SCHEMA_VERSION = "2.0-legal-nlp"
EXTRACTOR_VERSION = "federal-rules-2.0.0"

FALLBACK_REASONS = frozenset(
    {
        "unsupported_jurisdiction",
        "missing_source_text",
        "unrecognized_federal_structure",
        "no_supported_claims",
        "schema_validation_failed",
        "evidence_validation_failed",
    }
)


class ExpectedExtractionRejection(ValueError):
    def __init__(self, reason: str):
        if reason not in FALLBACK_REASONS:
            raise ValueError(f"Unsupported extraction rejection reason: {reason}")
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class SourceSpan:
    text: str
    start_char: int
    end_char: int


@dataclass(frozen=True)
class StructuralSection:
    label: str
    heading: str | None
    level: str
    span: SourceSpan
    parent_label: str | None


@dataclass(frozen=True)
class ExtractedClaim:
    category: str
    fields: dict[str, object]
    section_label: str | None
    evidence: tuple[SourceSpan, ...]
    rule_id: str


@dataclass(frozen=True)
class EvidenceCandidate:
    field_path: str
    quoted_text: str
    start_char: int
    end_char: int
    page_number: int | None = None


@dataclass(frozen=True)
class ExtractionResult:
    schema_version: str
    contract_json: dict[str, object]
    evidence: tuple[EvidenceCandidate, ...]
    method: str
    fallback_reason: str | None = None
