"""Deterministic legal-text extraction for legislation contracts."""

from .service import extract_contract
from .types import EXTRACTOR_VERSION, SCHEMA_VERSION

__all__ = ["EXTRACTOR_VERSION", "SCHEMA_VERSION", "extract_contract"]
