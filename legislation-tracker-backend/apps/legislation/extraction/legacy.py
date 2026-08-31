import re

from apps.legislation.models import Bill, BillDocument

from .types import EvidenceCandidate, ExtractionResult

LEGACY_SCHEMA_VERSION = "1.1-deterministic"


def _source_text(document: BillDocument, bill: Bill):
    text = (document.extracted_text or "").strip()
    if text:
        return text
    return (bill.summary or bill.title or "").strip()


def _sentence_spans(text):
    spans = []
    for match in re.finditer(r"[^.!?]+[.!?]", text):
        raw = match.group()
        leading = len(raw) - len(raw.lstrip())
        sentence = raw.strip()
        if not sentence:
            continue
        start = match.start() + leading
        spans.append({"text": sentence, "start": start, "end": start + len(sentence)})
    trailing_start = spans[-1]["end"] if spans else 0
    trailing = text[trailing_start:].strip()
    if trailing:
        start = text.find(trailing, trailing_start)
        spans.append({"text": trailing, "start": start, "end": start + len(trailing)})
    return spans


def _is_heading(sentence):
    return bool(re.fullmatch(r"(section|sec)\.?\s+[0-9a-zA-Z-]+\.?", sentence.lower()))


def _first_meaningful_sentence(sentences):
    for sentence in sentences:
        if not _is_heading(sentence["text"]):
            return sentence
    return sentences[0] if sentences else None


def _matches_any(sentence, keywords):
    text = sentence["text"].lower()
    return any(re.search(rf"\b{re.escape(keyword)}\b", text) for keyword in keywords)


def _matching_sentences(sentences, keywords, limit=5):
    matches = []
    for sentence in sentences:
        if _matches_any(sentence, keywords):
            matches.append(sentence)
        if len(matches) >= limit:
            break
    return matches


def _contract_item(sentence, category):
    return {"text": sentence["text"], "category": category}


def _add_evidence(evidence, field_path, quote, source_text, start=None):
    if not quote:
        return
    if start is None:
        start = source_text.find(quote)
    if start < 0:
        return
    evidence.append(
        EvidenceCandidate(
            field_path=field_path,
            quoted_text=quote,
            start_char=start,
            end_char=start + len(quote),
        )
    )


def build_legacy_document_contract(
    document: BillDocument, bill: Bill
) -> ExtractionResult:
    """Build the unchanged deterministic v1.1 contract and exact citations."""
    source_text = _source_text(document, bill)
    sentences = _sentence_spans(source_text)
    summary_sentence = _first_meaningful_sentence(sentences)
    key_sentences = [s for s in sentences if not _is_heading(s["text"])][:5]
    if summary_sentence and summary_sentence not in key_sentences:
        key_sentences.insert(0, summary_sentence)
    key_sentences = key_sentences[:5]
    requirement_sentences = _matching_sentences(
        sentences,
        {"shall", "must", "require", "requires", "required", "prohibit", "prohibits"},
    )
    funding_sentences = _matching_sentences(
        sentences,
        {
            "appropriated",
            "authorization",
            "authorized",
            "fund",
            "funding",
            "grant",
            "$",
        },
    )
    effective_date_sentences = _matching_sentences(
        sentences,
        {"effective", "takes effect", "enactment"},
    )
    summary_text = (
        summary_sentence["text"]
        if summary_sentence
        else (bill.summary or bill.title or "")
    )
    source_excerpt = source_text[:500]
    contract_json = {
        "schema_version": LEGACY_SCHEMA_VERSION,
        "title": bill.title,
        "version_label": document.version_label,
        "plain_summary": summary_text,
        "source_excerpt": source_excerpt,
        "summary": {"text": summary_text, "basis": "first substantive source sentence"},
        "key_points": [
            _contract_item(sentence, "key_point") for sentence in key_sentences
        ],
        "requirements": [
            _contract_item(sentence, "requirement")
            for sentence in requirement_sentences
        ],
        "funding_mentions": [
            _contract_item(sentence, "funding") for sentence in funding_sentences
        ],
        "effective_dates": [
            _contract_item(sentence, "effective_date")
            for sentence in effective_date_sentences
        ],
        "limitations": [
            "This deterministic summary cites exact source sentences and is not legal advice."
        ],
    }
    evidence = []
    summary_start = summary_sentence["start"] if summary_sentence else None
    _add_evidence(evidence, "plain_summary", summary_text, source_text, summary_start)
    _add_evidence(evidence, "summary.text", summary_text, source_text, summary_start)
    _add_evidence(evidence, "source_excerpt", source_excerpt, source_text, 0)
    for index, sentence in enumerate(key_sentences):
        _add_evidence(
            evidence,
            f"key_points[{index}].text",
            sentence["text"],
            source_text,
            sentence["start"],
        )
    for index, sentence in enumerate(requirement_sentences):
        _add_evidence(
            evidence,
            f"requirements[{index}].text",
            sentence["text"],
            source_text,
            sentence["start"],
        )
    for index, sentence in enumerate(funding_sentences):
        _add_evidence(
            evidence,
            f"funding_mentions[{index}].text",
            sentence["text"],
            source_text,
            sentence["start"],
        )
    for index, sentence in enumerate(effective_date_sentences):
        _add_evidence(
            evidence,
            f"effective_dates[{index}].text",
            sentence["text"],
            source_text,
            sentence["start"],
        )
    return ExtractionResult(
        schema_version=LEGACY_SCHEMA_VERSION,
        contract_json=contract_json,
        evidence=tuple(evidence),
        method="legacy-deterministic",
    )


def build_legacy_metadata_contract(bill: Bill) -> dict[str, object]:
    summary_text = (bill.summary or bill.title or "").strip()
    return {
        "schema_version": LEGACY_SCHEMA_VERSION,
        "title": bill.title,
        "version_label": "metadata",
        "plain_summary": summary_text,
        "source_excerpt": summary_text[:500],
        "summary": {
            "text": summary_text,
            "basis": "bill metadata from source API",
        },
        "key_points": (
            [{"text": summary_text, "category": "key_point"}] if summary_text else []
        ),
        "requirements": [],
        "funding_mentions": [],
        "effective_dates": [],
        "limitations": [
            "This deterministic summary cites available metadata and is not legal advice."
        ],
    }
