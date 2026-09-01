# Phase 5: Evidence-backed bill contracts

Bill contracts turn official bill text into a structured, plain-language view while preserving an exact path back to the source. The current implementation is deterministic: it makes no LLM, external NLP, or extraction-time network calls.

## Supported contract versions

| Version | Use |
|---|---|
| `1.1-deterministic` | Compatibility contract for state bills, metadata-only bills, missing text, unsupported federal structure, and federal text with no supported claims. |
| `2.0-legal-nlp` | Immutable compatibility contract for federal text recognized by the original legal-NLP rules. It remains the default write format while the 2.1 gate is disabled. |
| `2.1-legal-nlp` | Immutable reader-first federal contract: source-ordered plain-English lines, complete recognized financial actions, timelines, definitions, and bounded evidence associations. |

`BillContract.schema_version` always matches `contract_json.schema_version`.
Existing 1.1 and 2.0 history remains readable through the API and client. The
`LEGAL_NLP_V21_WRITE_ENABLED` flag selects only which version new generation
writes; turning it off never makes an already-persisted 2.1 contract unreadable.

## Federal v2 pipeline

The extraction package is deliberately independent of the ORM:

| Module | Responsibility |
|---|---|
| `extraction/federal_structure.py` | Parse divisions, titles, subtitles, chapters, subchapters, parts, subparts, accounts, sections, appropriations paragraphs, and nested clauses without changing source offsets. |
| `extraction/legal_rules.py` | Extract explicit modalities, funding, timelines, definitions, applicability, and amendment operations. |
| `extraction/financial_rules.py` | Extract each recognized monetary action and preserve its action, direction, amount type, fiscal years, accounts, purpose, and source order. |
| `extraction/renderer.py` | Preserve the immutable 2.0 renderer. |
| `extraction/reader_renderer.py` | Render controlled 2.1 orientation, section groups, reader lines, associations, and evidence chunks. |
| `extraction/schema.py` | Validate JSON Schema draft 2020-12 plus association and exact-evidence invariants. |
| `extraction/service.py` | Select write-gated federal 2.1, compatible 2.0, or an expected 1.1 fallback. |
| `extraction/legacy.py` | Preserve the `1.1-deterministic` contract behavior. |

Rules exclude quoted text, definition payloads, table-of-contents entries, and amendment payloads from present-tense obligation claims. Amounts use decimal normalization, fiscal-year ranges are inclusive, relative deadlines retain their literal trigger, and amendment operations are reported rather than applied to external law.

Contract IDs such as section, line-item, financial-item, timeline, and
definition IDs are local to one contract source. They are stable within that
payload and support its internal links, but callers must never use an
offset-derived ID to match provisions across different bill versions. Version
comparison uses normalized semantic content and structural context instead, so
prepending text does not by itself report every unchanged provision as changed.

## Reader-first coverage

The bill brief is a deterministic aid, not an exhaustive legal interpretation.
It starts with the latest attributed CRS summary when Congress.gov provides
one. If no CRS summary exists, the reader instead shows an evidence-backed
statutory purpose when one can be cited, or a controlled
jurisdiction/status/topic overview as a final fallback.
This deterministic orientation is not presented as an official summary and
never invents policy claims unsupported by those fields. Policy areas,
extraction counts, and the complete recognized line-item and financial
breakdown remain available below it.

Reader lines are grouped by the federal source hierarchy and kept in source
order. Controlled display text is separated from exact official evidence, so
page markers, drafting notes, and quotation artifacts do not leak into the
primary reading surface. Exact text remains available on demand.

The financial collection is not ranked or capped. Every recognized
appropriation, authorization, allocation, transfer, rescission, reduction,
cancellation, set-aside, limitation, and other explicit action is retained as
a distinct item. Specified amounts, percentages, ceilings, and "such sums" are
also distinct. The product deliberately computes no grand total: different
actions, fiscal years, bases, and transfers cannot safely be added together.

A financial item is attached to a reader line only when the same exact clause,
or explicit program/account evidence, supports that association. Otherwise it
appears once at its section level. Standalone deadlines, effective dates, and
linked or unlinked definitions remain accessible through their own collections.

## Evidence and validation

Every customer-visible v2 claim has at least one `EvidenceSpan`. Before persistence, validation proves that:

- the contract conforms to `extraction/schemas/contract_v2.json`;
- every evidence field path resolves into the contract;
- `0 <= start_char < end_char <= len(extracted_text)`;
- the exact source slice equals `quoted_text`;
- each quotation chunk is non-empty and no longer than 4,000 characters; and
- all required visible fields have evidence.

When one supporting span exceeds 4,000 characters, the renderer stores ordered,
contiguous chunks that reconstruct the exact source slice without loss. The
public evidence endpoint deduplicates identical source slices and returns a
bounded page only after a caller supplies exactly one contract-local line,
financial, timeline, or definition item ID.

Unexpected extractor errors are not converted to fallback results. They propagate to the durable worker so its retry and dead-letter controls remain effective.

## Selection and fallback

Federal v2 requires all of the following:

1. `bill.jurisdiction == "federal"`;
2. non-empty `BillDocument.extracted_text`;
3. a recognized `SEC.` or `SECTION` marker; and
4. at least one supported high-confidence claim.

Expected failures return an unchanged v1.1 result with one recorded fallback reason: `unsupported_jurisdiction`, `missing_source_text`, `unrecognized_federal_structure`, `no_supported_claims`, `schema_validation_failed`, or `evidence_validation_failed`.

## Durable generation, semantic comparison, and backfill

`enqueue_document_contract()` writes persistent ingestion work before waking
Celery. Its dedupe key includes the active extractor version and an explicit
`generation_reason` (`ingestion` or `schema_backfill`), so normal ingestion and
schema migration cannot suppress each other. `generate_contract` preserves
hash idempotency, active-version selection, and exact evidence persistence.

User-visible comparison is semantic rather than a raw contract hash comparison.
Presentation-only schema changes and equivalent 2.0/2.1 content do not create a
false bill change. Normal ingestion can create contract/topic ChangeLog and
unread activity when meaning changes. A `schema_backfill` is intentionally
silent: it must not create `contract_update` or `topic_update` ChangeLog rows,
advance the bill activity sequence or timestamp, or mark a followed bill
unread. Topic and search projections are still refreshed with the backfill
reason so the new schema remains discoverable.

Backfills are preview-only unless `--execute` is explicit, and at least one bound is required:

```bash
rtk run "cd legislation-tracker-backend && .venv/bin/python manage.py backfill_contracts --session 119 --limit 25"
rtk run "cd legislation-tracker-backend && .venv/bin/python manage.py backfill_contracts --session 119 --limit 25 --execute"
rtk run "cd legislation-tracker-backend && .venv/bin/python manage.py backfill_contracts --start-id 100 --end-id 124 --all-versions --execute"
```

Preview output includes `generation_reason=schema_backfill`, target schema and
extractor versions, selected and eligible counts, document ID range, session
counts, and active/inactive counts. Preview works while the writer is disabled.
`--execute` refuses before enqueueing anything unless
`LEGAL_NLP_V21_WRITE_ENABLED=True`, and requires a bounded limit or ID range.
The command only enqueues durable work; it never runs extraction synchronously.
If the writer is disabled after a schema backfill is queued, the work remains
retryable instead of being recorded as successfully completed; re-enable the
writer or replay the work after restoring a consistent rollout configuration.
Executed batches rebuild `extracted_text` from the stored document before contract
generation, so documents ingested before the structure-preserving parser can
produce v2 contracts without a network re-download.

## Read-before-write rollout

1. Deploy the API, workers, and client with
   `LEGAL_NLP_V21_WRITE_ENABLED=False` everywhere.
2. Verify legacy, 2.0, and seeded 2.1 API and UI behavior, including bounded
   evidence and the no-CRS state.
3. Set `LEGAL_NLP_V21_WRITE_ENABLED=True` on the API, worker, and Beat for new
   generation.
4. Preview 25 documents with `backfill_contracts`.
5. Execute 25-document batches. Inspect durable work failures, contract and
   evidence counts, and confirm that schema backfills create no user activity.
6. If necessary, disable new 2.1 writes again. Persisted 2.1 contracts continue
   to be served by the already-deployed readers.

## Quality gates

The federal evaluation corpus contains 29 positive and adversarial fixtures with at least three positive claims per supported category. Tests require:

- 100% schema validity;
- 100% exact evidence validity;
- at least 95% aggregate precision;
- at least 70% aggregate recall; and
- zero forbidden false positives from quotations, contents entries, or removed text.

Unit and integration coverage also verifies fallback selection, mixed 1.1/2.0/
2.1 API history, durable idempotency, semantic comparison, silent preview-first
backfill behavior, structured client rendering, and Django-to-Next.js browser
flows against real legislation-shaped fixtures.

## Client behavior

The compact bill detail response contains orientation and counts, but never the
substantive reader arrays or evidence quotations. Reader, financial, timeline,
definition, contract-history, and evidence endpoints are paginated and enforce
a maximum page size of 100. Association previews are limited to three items and
remain source ordered; they are previews, not a ranking. Full evidence and the
complete official summary are loaded only after explicit reader action.

The client presents the bill as an overview, plain-English source-ordered line
items, an uncapped financial breakdown, key dates, terms, and voting record.
Legacy and 2.0 payloads keep their compatible renderer. Unknown warnings and
malformed 2.1 payloads are not exposed as internal debug data.

## Deferred scope

Provider adapters, LLM extraction, embeddings, external NLP services, and state-specific v2 rule packs are not implemented. The older provider-oriented plan is retained only as historical context in [PHASE_5_3_PLAN.md](PHASE_5_3_PLAN.md).
