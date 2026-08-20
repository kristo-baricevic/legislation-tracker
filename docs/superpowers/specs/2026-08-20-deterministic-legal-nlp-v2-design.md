# Deterministic Legal-NLP v2 Design

**Date:** 2026-08-20  
**Status:** Approved design  
**Scope:** Federal bill contract extraction, evidence, API compatibility, bill-detail UI, and controlled backfill

## Summary

Replace the current sentence-and-keyword contract builder with a deterministic, federal-first legal extraction pipeline. The new pipeline will parse legislative structure, extract high-confidence legal facts with explicit rules, produce controlled plain-language text, validate a versioned JSON contract, and attach exact source evidence to every displayed claim.

The system will not use an LLM, hosted NLP service, API key, or downloadable statistical language model. The current `1.1-deterministic` extractor remains the fallback for unsupported or unparseable documents. Existing `BillContract`, `EvidenceSpan`, `ChangeLog`, durable ingestion work, retry, and dead-letter infrastructure remain in use.

## Goals

- Produce substantially richer, structured contracts from U.S. federal bill text without external inference services.
- Preserve exact traceability from every customer-visible claim to `BillDocument.extracted_text`.
- Favor precision over coverage and omit claims the rules cannot support reliably.
- Keep output reproducible: the same bill text and extractor version must produce the same contract and hash.
- Preserve mixed v1/v2 contract history through the existing API.
- Render v2 structure and per-claim evidence on the bill-detail page.
- Provide an explicit, preview-first backfill mechanism for existing local or future deployed data.
- Establish a checked-in evaluation corpus and measurable quality gates.

## Non-goals

- LLM, hosted NLP, embeddings, spaCy, or local-model integration.
- State-bill format support in v2. State and unsupported documents use the legacy extractor.
- Producing a legally consolidated version of statutes amended by a bill.
- Guessing ambiguous actors, objects, conditions, cross-references, dates, or amendment effects.
- Automatic historical backfill during deployment or application startup.
- Page-number evidence until document ingestion supplies a reliable page-to-character map.
- Legal advice or a representation that extraction is exhaustive.

## Chosen Approach

Use Python rules, federal legislative structure parsing, and controlled rendering templates. This avoids per-document operating costs, secrets, network dependencies, model-version drift, hallucinations, and model deployment overhead.

Two alternatives were rejected for v2:

- **spaCy-assisted extraction:** generic dependency parsing adds a large versioned model dependency without demonstrated accuracy on statutory language.
- **Rules plus a provider or local-model interface:** an abstraction for a provider that is not needed yet adds complexity. The extraction package boundaries defined below are sufficient to introduce another implementation later.

## Architecture

The Celery task remains the orchestration boundary. `generate_contract(document_id)` loads the document and bill, calls the extraction service, hashes the returned JSON, and performs the existing transactional persistence and downstream enqueue behavior.

Create `apps/legislation/extraction/` with focused modules:

| File | Responsibility |
| --- | --- |
| `types.py` | Immutable dataclasses for source spans, structural sections, claims, evidence, and extraction results. |
| `federal_structure.py` | Parse federal titles, parts, sections, subsections, headings, and sentences while preserving exact character offsets. |
| `legal_rules.py` | Extract requirements, prohibitions, permissions, funding, timelines, definitions, applicability, eligibility, and amendment operations. |
| `renderer.py` | Convert extracted facts into controlled display text and the audience summary. |
| `schema.py` | Load the v2 JSON Schema and enforce semantic evidence/path invariants. |
| `legacy.py` | Hold the existing `1.1-deterministic` builder without behavioral changes. |
| `service.py` | Select federal v2 or legacy extraction and return one `ExtractionResult`. |
| `schemas/contract_v2.json` | Machine-readable schema for `2.0-legal-nlp`. |

The core interfaces are:

```python
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


def extract_contract(*, document: BillDocument, bill: Bill) -> ExtractionResult:
    ...
```

No ORM objects are created inside the extraction package. This keeps parsing, rules, rendering, and validation independently testable.

## Structural Parsing

The parser operates on the original Python string used for extraction. It never normalizes or rewrites that string before calculating offsets.

It recognizes the following federal structural markers case-insensitively:

- `TITLE I`, `SUBTITLE A`, `PART I`, `SUBPART A`, and `CHAPTER 1`
- `SEC. 101.`, `SECTION 101.`, and common alphanumeric section labels
- Parenthesized subsection and paragraph markers such as `(a)`, `(1)`, `(A)`, and `(i)`
- Headings on the same line as or immediately following a structural marker

Each structural node contains its source range and parent label. Sentence spans are found inside structural nodes and translated back to document-global offsets. Repeated sentences are distinguished by their actual match positions.

Federal v2 is supported only when all of these conditions hold:

1. `bill.jurisdiction == "federal"`.
2. `document.extracted_text` is non-empty.
3. At least one recognizable federal section is present.
4. At least one high-confidence operative claim is extracted.

Failure of any support condition returns the legacy result. A short federal bill with a recognizable section and one supported claim is valid; document length is not a support criterion.

## Extraction Rules

Rules are explicit, versioned by `rule_id`, and limited to grammatical forms for which the implementation can identify the operative phrase and exact evidence.

### Requirements, prohibitions, and permissions

- Required: `shall`, `must`, `is required to`
- Prohibited: `may not`, `shall not`, `is prohibited from`
- Permitted or authorized: `may`, `is authorized to`

The rule emits a claim only when it can isolate a non-empty actor and action within the same operative sentence or immediately inherited subsection context. Extracted fields are `modality`, `actor`, `action`, optional `object`, `conditions`, and `section_label`.

Quoted text, a definition, an amendment target, a table of contents, or a removed phrase must not be emitted as a present obligation merely because it contains a modal verb.

### Funding

Recognize appropriations and authorizations of appropriations, including:

- Dollar amounts normalized to decimal strings without currency symbols or separators
- `currency: "USD"`
- Explicit fiscal years as integers
- Fiscal-year ranges as inclusive integer arrays when both endpoints are explicit
- `such sums as may be necessary` with `amount: null` and `amount_type: "such_sums"`
- The purpose or recipient only when contained in the same provision

### Timelines

Recognize:

- Explicit calendar dates normalized to ISO `YYYY-MM-DD`
- `not later than N days/months/years after <trigger>`
- `N days/months/years after <trigger>`
- `takes effect` and `effective on`

Relative timelines store `relative_value`, `relative_unit`, and the literal `trigger`. The extractor does not calculate a calendar date when the trigger date is unavailable.

### Definitions

Recognize `means` and `includes` definitions only in an explicitly labeled definitions provision or a syntactically explicit `The term "X" means ...` form. The result stores `term`, `definition`, `definition_type`, and `section_label`.

### Applicability and eligibility

Recognize explicit `applies to`, `does not apply to`, `eligible entity`, `eligible applicant`, and exclusion forms. Claims store a `subject`, `scope`, `applicability_type`, and `section_label`. The extractor does not infer membership in an eligibility class.

### Amendment operations

Recognize add, insert, strike, strike-and-insert, replace, redesignate, repeal, and amend instructions. Store the target citation, operation, and literal affected text where explicit.

The extractor reports the operation; it does not apply the operation to external law or claim that the result is consolidated. Text identified as existing-law quotation, insertion payload, or removal payload is excluded from ordinary obligation rules unless the bill independently makes it operative.

### Ordering, deduplication, and limits

Claims are ordered by the first evidence offset, then by stable category order. Duplicates require the same category, normalized fields, and evidence offsets. No semantic or fuzzy deduplication is used.

Each category is capped at 100 stored items. Reaching a cap adds `item_limit_reached:<category>` to `extraction.warnings`. The renderer uses at most three claims in `plain_summary`, selected in this order:

1. First primary requirement, prohibition, permission, or amendment operation
2. First funding item
3. First effective date or deadline

Missing categories are skipped rather than replaced with generic text.

## Contract Schema

The new schema version is `2.0-legal-nlp`. The extractor implementation identifier is `federal-rules-2.0.0`. Changing output shape requires a schema-version change; changing rule behavior requires an extractor-version change.

Top-level shape:

```json
{
  "schema_version": "2.0-legal-nlp",
  "title": "Rural Health Grants Act",
  "version_label": "Introduced",
  "extraction": {
    "method": "federal-rules",
    "parser_version": "2.0.0",
    "sections_seen": 8,
    "sections_with_claims": 5,
    "warnings": []
  },
  "plain_summary": "The Secretary is required to award grants to rural hospitals.",
  "key_provisions": [],
  "requirements": [],
  "funding_items": [],
  "timeline_items": [],
  "definitions": [],
  "applicability": [],
  "amendment_operations": [],
  "limitations": [
    "This automated summary is based on explicit patterns in the bill text and is not legal advice."
  ]
}
```

### Common item fields

Every structured item includes:

- `section_label`: string or `null`
- `display_text`: non-empty controlled-rendered string

`key_provisions` contains references to selected claims rather than a second independently extracted fact set. Each item contains `kind`, `section_label`, optional `heading`, and `text`.

### Normalized values

- Money: decimal string, such as `"25000000.00"`
- Currency: `"USD"`
- Calendar date: ISO string
- Fiscal year: integer
- Relative duration: integer value plus `days`, `months`, or `years`
- Missing or non-explicit values: JSON `null`, never an inferred value

The JSON Schema sets `additionalProperties: false` at every object level, category arrays to a maximum of 100 items, and required fields for each item kind. Production requirements add `jsonschema>=4.23,<5` for validation.

Metadata-only contracts remain `1.1-deterministic` because bill metadata cannot support the v2 evidence requirements.

## Evidence Invariants

Each prominently rendered claim must have at least one `EvidenceCandidate`. This includes:

- `plain_summary`
- Every `key_provisions[i].text`
- Every category item's `display_text`
- Definition term and definition display text

Multiple evidence rows may share a field path. This supports a summary sentence constructed from more than one exact provision.

Before persistence, validation requires:

1. The field path resolves to an existing value in `contract_json`.
2. `0 <= start_char < end_char <= len(extracted_text)`.
3. `extracted_text[start_char:end_char] == quoted_text` exactly.
4. The quote is non-empty and no longer than 4,000 characters.
5. Every required customer-visible field has evidence.

`page_number` remains `null` until ingestion can produce a reliable page map.

## Selection and Fallback

`service.extract_contract()` attempts v2 only for a federal document with text. Expected v2 rejection uses one of these internal reason codes:

- `unsupported_jurisdiction`
- `missing_source_text`
- `unrecognized_federal_structure`
- `no_supported_claims`
- `schema_validation_failed`
- `evidence_validation_failed`

Expected rejection is logged and returns the unchanged legacy extractor result. The fallback reason is returned on `ExtractionResult` for logging and tests but is not added to legacy JSON, which preserves legacy behavior and hashes.

Unexpected programming errors, database errors, storage errors, and transaction failures propagate. They are not converted into legacy output. The existing durable work retry and dead-letter behavior handles them.

## Persistence and Durable Work

The task preserves its current transaction behavior:

1. Load the `BillDocument` and related `Bill`.
2. Extract and validate outside the database transaction.
3. Compute the canonical contract hash.
4. Skip a duplicate contract for the same document and hash.
5. Create `BillContract`, `EvidenceSpan`, and `ChangeLog` rows atomically.
6. Update `Bill.latest_contract` only for the active document version.
7. Mark `contract_generated_at`.
8. Enqueue downstream topic work.

Document-contract work deduplication changes from document ID plus content hash to document ID plus content hash plus extractor version. This creates one durable attempt when rules change without causing view-driven or repeated extraction. Dead work is retried through existing replay controls.

Because the project is not deployed, no automatic migration job is needed. Existing v1 rows remain valid history and are superseded only when an explicit backfill generates a v2 contract.

## Backfill Command

Add `python manage.py backfill_contracts` with these options:

- `--session <int>`: filter by congressional session
- `--start-id <int>` and `--end-id <int>`: inclusive document ID bounds
- `--limit <int>`: maximum documents selected after ordering by ID
- `--all-versions`: include inactive document versions; active versions are the default
- `--execute`: enqueue selected documents; without it, print a preview only

The command requires at least one narrowing selector from `--session`, an ID bound, or `--limit`. It uses `enqueue_document_contract()` so execution is durable and idempotent for the extractor version. It prints selected count, ID range, session breakdown, active/inactive counts, and enqueue count. It never invokes extraction synchronously.

## API Compatibility

No new endpoint or database field is required. `BillContractSerializer` continues returning `schema_version`, `contract_json`, and `evidence_spans`.

Contract history can contain both schema versions. API tests must cover:

- Latest contract is v2 while history includes v1
- Latest contract remains v1 after a v2 fallback
- V1 and v2 evidence serialization
- Active versus inactive document version behavior

Consumers must branch on the top-level model `schema_version`, which must equal `contract_json.schema_version` for v2.

## Frontend

Replace the untyped `Record<string, unknown>` consumption with a versioned contract union:

```typescript
type ContractJson = LegacyContractJson | LegalNlpV2ContractJson;

function isLegalNlpV2Contract(
  schemaVersion: string,
  value: unknown,
): value is LegalNlpV2ContractJson;
```

The v2 bill-detail view renders non-empty sections in this order:

1. Plain-language overview
2. Key provisions
3. Requirements and prohibitions
4. Funding
5. Deadlines and effective dates
6. Definitions
7. Eligibility and applicability
8. Amendment operations
9. Automated extraction limitations

Each item displays its section label and an expandable `Source evidence` control. Evidence is grouped by exact `field_path`. Empty sections are omitted. Extraction warnings are translated from known codes to restrained product copy; unknown warning codes use one generic limitation message and are never displayed verbatim.

V1 records continue through the existing legacy summary component. Contract history shows the schema and summary for both versions.

## Observability

Each extraction logs one structured event containing:

- `document_id` and `bill_id`
- selected `schema_version`, method, and parser version
- `sections_seen` and `sections_with_claims`
- count by extracted category
- warning codes
- fallback reason when applicable
- duration in milliseconds

Logs must not contain full bill text or evidence quotations. Existing dead-letter records capture unexpected task failures.

## Evaluation and Testing

### Evaluation corpus

Check in at least 25 public-domain federal legislative excerpts and expected claim files. The corpus must include:

- At least three positive examples for every supported category
- At least five negative examples containing quoted, defined, removed, table-of-contents, or otherwise non-operative modal language
- At least five amendment examples, including strike-and-insert and repeal
- Repeated sentences, Unicode punctuation, missing terminal punctuation, multi-line headings, and long sections

Expected claims use category plus normalized core fields and exact evidence ranges. A pytest evaluation module computes per-category and aggregate precision and recall.

Release gates are:

- 100% contract JSON Schema validity
- 100% exact evidence-offset validity
- At least 95% aggregate precision for supported claim categories
- At least 70% aggregate recall for explicitly supported patterns
- No false current obligation emitted from a negative amendment or quotation fixture

Recall outside the documented supported grammar is measured for information but is not a v2 release gate.

### Backend tests

- Structural parsing and exact global offsets
- Rule positives, negatives, boundaries, and caps
- Controlled rendering and deterministic ordering
- JSON Schema rejection and semantic evidence validation
- Federal v2 selection and every fallback reason
- Task persistence, unchanged hash, active-version selection, transaction atomicity, and downstream enqueue
- Extractor-version durable deduplication
- Backfill preview, filters, `--execute`, and idempotency
- Mixed v1/v2 API history

### Frontend tests

- Runtime v2 guard accepts valid and rejects malformed payloads
- Structured sections render only when non-empty
- Evidence groups attach to the correct item
- Known and unknown warning rendering
- V1 fallback rendering and mixed history
- Playwright bill-detail flow for v2 summary, structured claims, and evidence expansion

### Final verification

- Full backend pytest suite
- Frontend Vitest and Node test suites
- TypeScript typecheck
- ESLint
- Next.js production webpack build
- Playwright E2E suite
- Extension tests to detect shared API regressions

## Rollout

1. Land the schema, parser, rules, renderer, validation, integration, UI, and tests without running a backfill.
2. Generate v2 contracts naturally for newly processed supported federal documents.
3. Preview a small active-document batch with `backfill_contracts`.
4. Execute a bounded batch and review output against source evidence.
5. Expand by session or ID range only after the quality gates and manual sample review pass.
6. Use the legacy fallback and existing dead-letter replay controls for exceptions.

## Future Extension Boundary

A future spaCy, local-model, or provider-backed extractor may implement the same `ExtractionResult` boundary, but it must use a new schema or extractor version as appropriate and must pass the same JSON and evidence validation. No provider adapter is included in v2.

