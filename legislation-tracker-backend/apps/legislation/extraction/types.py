from dataclasses import dataclass
from enum import StrEnum

V2_SCHEMA_VERSION = "2.0-legal-nlp"
V21_SCHEMA_VERSION = "2.1-legal-nlp"
V2_EXTRACTOR_VERSION = "federal-rules-2.0.0"
V21_EXTRACTOR_VERSION = "federal-rules-2.1.0"

# Compatibility aliases for the immutable 2.0 renderer.
SCHEMA_VERSION = V2_SCHEMA_VERSION
EXTRACTOR_VERSION = V2_EXTRACTOR_VERSION

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


def active_extractor_version() -> str:
    from django.conf import settings

    return (
        V21_EXTRACTOR_VERSION
        if settings.LEGAL_NLP_V21_WRITE_ENABLED
        else V2_EXTRACTOR_VERSION
    )


class FinancialAction(StrEnum):
    APPROPRIATION = "appropriation"
    AUTHORIZATION = "authorization"
    ALLOCATION = "allocation"
    TRANSFER = "transfer"
    RESCISSION = "rescission"
    REDUCTION = "reduction"
    CANCELLATION = "cancellation"
    SET_ASIDE = "set_aside"
    LIMITATION = "limitation"
    OTHER_EXPLICIT = "other_explicit"


class FinancialDirection(StrEnum):
    INCREASE = "increase"
    DECREASE = "decrease"
    NEUTRAL_TRANSFER = "neutral_transfer"
    LIMIT = "limit"


class FinancialAmountType(StrEnum):
    SPECIFIED = "specified"
    SUCH_SUMS = "such_sums"
    PERCENTAGE = "percentage"
    CEILING = "ceiling"


@dataclass(frozen=True)
class SourceSpan:
    text: str
    start_char: int
    end_char: int


@dataclass(frozen=True)
class SectionPathItem:
    """A source-local structural marker used to identify a federal provision."""

    label: str
    heading: str | None
    level: str


@dataclass(frozen=True)
class StructuralSection:
    label: str
    heading: str | None
    level: str
    span: SourceSpan
    parent_label: str | None
    source_id: str = ""
    path: tuple[SectionPathItem, ...] = ()


@dataclass(frozen=True)
class ExtractedClaim:
    category: str
    fields: dict[str, object]
    section_label: str | None
    evidence: tuple[SourceSpan, ...]
    rule_id: str
    source_id: str | None = None
    section_id: str | None = None
    section_path: tuple[SectionPathItem, ...] = ()


@dataclass(frozen=True)
class ExtractionWarning:
    code: str
    rule_id: str
    source_id: str | None
    evidence: tuple[SourceSpan, ...]


@dataclass(frozen=True)
class RenderedReaderClaim:
    kind: str
    display_text: str
    actor: str | None
    action: str | None
    effect: str | None


@dataclass(frozen=True)
class IdentifiedClaim:
    id: str
    claim: ExtractedClaim


@dataclass(frozen=True)
class ReaderLineItem:
    id: str
    source_id: str
    section_id: str
    section_path: tuple[SectionPathItem, ...]
    kind: str
    display_text: str
    actor: str | None
    action: str | None
    effect: str | None
    claim_refs: tuple[str, ...]
    exact_financial_refs: tuple[str, ...]
    timeline_refs: tuple[str, ...]
    definition_refs: tuple[str, ...]
    evidence: tuple[SourceSpan, ...]


@dataclass(frozen=True)
class ReaderSectionGroup:
    source_id: str
    section_path: tuple[SectionPathItem, ...]
    line_item_ids: tuple[str, ...]
    section_financial_refs: tuple[str, ...]
    section_timeline_refs: tuple[str, ...]


@dataclass(frozen=True)
class ReaderStats:
    line_item_count: int
    financial_item_count: int
    timeline_item_count: int
    definition_item_count: int
    section_group_count: int


@dataclass(frozen=True)
class ReaderOrientation:
    purpose_clause: str | None
    purpose_line_item_id: str | None


@dataclass(frozen=True)
class ReaderBrief:
    coverage_note: str
    orientation: ReaderOrientation
    reader_stats: ReaderStats
    section_groups: tuple[ReaderSectionGroup, ...]
    line_items: tuple[ReaderLineItem, ...]
    identified_claims: tuple[IdentifiedClaim, ...]
    financial_items: tuple[IdentifiedClaim, ...]
    timeline_items: tuple[IdentifiedClaim, ...]
    definition_items: tuple[IdentifiedClaim, ...]
    warnings: tuple[ExtractionWarning, ...]


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
