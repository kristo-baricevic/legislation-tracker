# Phase 5: Evidence-backed bill contracts

Bill contracts turn official bill text into a structured, plain-language view while preserving an exact path back to the source. The current implementation is deterministic: it makes no LLM, external NLP, or extraction-time network calls.

## Supported contract versions

| Version | Use |
|---|---|
| `1.1-deterministic` | Compatibility contract for state bills, metadata-only bills, missing text, unsupported federal structure, and federal text with no supported claims. |
| `2.0-legal-nlp` | Federal legal-NLP contract produced from recognized bill structure and high-confidence rules. |

`BillContract.schema_version` always matches `contract_json.schema_version`. Existing v1 history remains readable through the API and client.

## Federal v2 pipeline

The extraction package is deliberately independent of the ORM:

| Module | Responsibility |
|---|---|
| `extraction/federal_structure.py` | Parse titles, parts, sections, and subdivisions without changing source offsets. |
| `extraction/legal_rules.py` | Extract explicit modalities, funding, timelines, definitions, applicability, and amendment operations. |
| `extraction/renderer.py` | Render controlled plain-language sentences, category arrays, key provisions, warnings, and evidence paths. |
| `extraction/schema.py` | Validate JSON Schema draft 2020-12 plus exact evidence/path invariants. |
| `extraction/service.py` | Select federal v2 or an expected v1 fallback. |
| `extraction/legacy.py` | Preserve the `1.1-deterministic` contract behavior. |

Rules exclude quoted text, definition payloads, table-of-contents entries, and amendment payloads from present-tense obligation claims. Amounts use decimal normalization, fiscal-year ranges are inclusive, relative deadlines retain their literal trigger, and amendment operations are reported rather than applied to external law.

## Evidence and validation

Every customer-visible v2 claim has at least one `EvidenceSpan`. Before persistence, validation proves that:

- the contract conforms to `extraction/schemas/contract_v2.json`;
- every evidence field path resolves into the contract;
- `0 <= start_char < end_char <= len(extracted_text)`;
- the exact source slice equals `quoted_text`;
- a quotation is non-empty and no longer than 4,000 characters; and
- all required visible fields have evidence.

Unexpected extractor errors are not converted to fallback results. They propagate to the durable worker so its retry and dead-letter controls remain effective.

## Selection and fallback

Federal v2 requires all of the following:

1. `bill.jurisdiction == "federal"`;
2. non-empty `BillDocument.extracted_text`;
3. a recognized `SEC.` or `SECTION` marker; and
4. at least one supported high-confidence claim.

Expected failures return an unchanged v1.1 result with one recorded fallback reason: `unsupported_jurisdiction`, `missing_source_text`, `unrecognized_federal_structure`, `no_supported_claims`, `schema_validation_failed`, or `evidence_validation_failed`.

## Durable generation and backfill

`enqueue_document_contract()` writes persistent ingestion work before waking Celery. Its dedupe key includes `federal-rules-2.0.0`, so changing extractor behavior creates new work without changing the work kind or payload. `generate_contract` preserves hash idempotency, active-version selection, change history, topic enqueueing, and exact evidence persistence.

Backfills are preview-only unless `--execute` is explicit, and at least one bound is required:

```bash
rtk .venv/bin/python manage.py backfill_contracts --session 119 --limit 100
rtk .venv/bin/python manage.py backfill_contracts --session 119 --limit 100 --execute
rtk .venv/bin/python manage.py backfill_contracts --start-id 100 --end-id 200 --all-versions --execute
```

The command only enqueues durable work; it never runs extraction synchronously.
Executed batches rebuild `extracted_text` from the stored document before contract
generation, so documents ingested before the structure-preserving parser can
produce v2 contracts without a network re-download.

## Quality gates

The federal evaluation corpus contains 29 positive and adversarial fixtures with at least three positive claims per supported category. Tests require:

- 100% schema validity;
- 100% exact evidence validity;
- at least 95% aggregate precision;
- at least 70% aggregate recall; and
- zero forbidden false positives from quotations, contents entries, or removed text.

Unit and integration coverage also verifies fallback selection, mixed v1/v2 API history, durable idempotency, preview-first backfill behavior, structured client rendering, and a live Django-to-Next.js browser flow.

## Client behavior

The bill detail page renders v2 categories separately and attaches source evidence to the claim it supports. Empty categories are omitted. Known limit warnings use controlled copy, unknown warning codes are never exposed, and malformed v2 payloads safely use the legacy summary renderer.

## Deferred scope

Provider adapters, LLM extraction, embeddings, external NLP services, and state-specific v2 rule packs are not implemented. The older provider-oriented plan is retained only as historical context in [PHASE_5_3_PLAN.md](PHASE_5_3_PLAN.md).
