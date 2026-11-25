"""Reuse deterministic work before expensive parsing or keyword scans."""

import hashlib
from dataclasses import asdict

from .enhancements.source_packet import canonical_json_bytes
from .extraction.types import (
    EvidenceCandidate,
    ExtractionResult,
    active_extractor_version,
)
from .models import BillProcessingCache


def cached_extraction(document, bill, extract, *, force=False):
    fingerprint = hashlib.sha256(
        canonical_json_bytes(
            {
                "kind": "extraction-1",
                "extractor": active_extractor_version(),
                "jurisdiction": bill.jurisdiction,
                "title": bill.title,
                "summary": bill.summary,
                "text": document.extracted_text,
                "version_label": document.version_label,
            }
        )
    ).hexdigest()
    saved = (
        None
        if force
        else BillProcessingCache.objects.filter(
            pk=fingerprint, kind="extraction"
        ).first()
    )
    if saved:
        data = dict(saved.result_json)
        data["evidence"] = tuple(EvidenceCandidate(**e) for e in data["evidence"])
        return ExtractionResult(**data)
    result = extract(document=document, bill=bill)
    BillProcessingCache.objects.update_or_create(
        pk=fingerprint, defaults={"kind": "extraction", "result_json": asdict(result)}
    )
    return result


def cached_topics(bill, contract, infer, taxonomy, generic_keywords):
    fingerprint = hashlib.sha256(
        canonical_json_bytes(
            {
                "kind": "topics-1",
                "title": bill.title,
                "summary": bill.summary,
                "contract": contract.contract_json if contract else {},
                "taxonomy": taxonomy,
                "generic_keywords": sorted(generic_keywords),
            }
        )
    ).hexdigest()
    cached = BillProcessingCache.objects.filter(pk=fingerprint, kind="topics").first()
    if cached:
        return [tuple(pair) for pair in cached.result_json]
    result = infer(bill=bill, contract=contract)
    BillProcessingCache.objects.get_or_create(
        pk=fingerprint, defaults={"kind": "topics", "result_json": result}
    )
    return result
