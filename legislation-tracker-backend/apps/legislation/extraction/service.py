import logging
from dataclasses import replace

from apps.legislation.models import Bill, BillDocument

from . import legal_rules, renderer
from .federal_structure import parse_federal_structure
from .legacy import build_legacy_document_contract
from .schema import ContractValidationError
from .types import ExpectedExtractionRejection, ExtractionResult

logger = logging.getLogger(__name__)


def _legacy_result(
    *, document: BillDocument, bill: Bill, fallback_reason: str
) -> ExtractionResult:
    return replace(
        build_legacy_document_contract(document, bill),
        fallback_reason=fallback_reason,
    )


def extract_contract(*, document: BillDocument, bill: Bill) -> ExtractionResult:
    try:
        if bill.jurisdiction != "federal":
            raise ExpectedExtractionRejection("unsupported_jurisdiction")
        source_text = document.extracted_text or ""
        if not source_text.strip():
            raise ExpectedExtractionRejection("missing_source_text")

        sections = parse_federal_structure(source_text)
        claims = legal_rules.extract_claims(source_text, sections)
        if not claims:
            raise ExpectedExtractionRejection("no_supported_claims")
        return renderer.render_contract(
            title=bill.title,
            version_label=document.version_label,
            sections=sections,
            claims=claims,
            source_text=source_text,
        )
    except ExpectedExtractionRejection as error:
        logger.info(
            "Federal legal NLP extraction fell back for expected reason: %s",
            error.reason,
        )
        return _legacy_result(
            document=document,
            bill=bill,
            fallback_reason=error.reason,
        )
    except ContractValidationError as error:
        logger.warning(
            "Federal legal NLP extraction failed validation: %s", error.reason
        )
        return _legacy_result(
            document=document,
            bill=bill,
            fallback_reason=error.reason,
        )
