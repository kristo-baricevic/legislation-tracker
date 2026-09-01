# Reader-First Bill Brief Design

**Date:** 2026-09-01
**Status:** Revised after adversarial review
**Scope:** Federal bill summaries, deterministic legal-NLP presentation, financial provisions, source evidence, voting records, comparisons, search, and safe rollout
**Source references:** [Library of Congress bill API documentation](https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/BillEndpoint.md) and [summary API documentation](https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/SummariesEndpoint.md)

## Product Goal

The bill page must let a non-specialist answer four questions without reading the whole statute:

1. What does this bill do?
2. What concrete requirements, permissions, prohibitions, amendments, deadlines, and applicability rules does it contain?
3. What money does it provide, authorize, move, rescind, reduce, reserve, or limit?
4. How did Congress vote, and what exact bill text supports each displayed statement?

The primary experience is a bill brief, not an extraction-debug view. The system remains deterministic and evidence-backed. It never uses an importance score to hide provisions.

## Product Invariants

- Do not rank provisions by presumed importance, consequence, ideology, or monetary size.
- Preserve every provision recognized by the supported deterministic grammar in bill-text order.
- Preserve every recognized financial provision; no backend or frontend top-N cap is allowed.
- Never describe recognized coverage as exhaustive coverage of every possible legal construction. Show the supported financial-action coverage in extraction limitations.
- Never imply that an authorization is an appropriation or that a transfer, rescission, reduction, set-aside, or limitation is new spending.
- Do not calculate a grand total unless the source explicitly provides an additive total. Repeated annual amounts, transfers, rescissions, overlapping accounts, and nested set-asides make naive summation misleading.
- Every reader-visible line item and financial item exposes exact, verbatim source text on request.
- Known Congress/GPO display artifacts are removed only from controlled reader text. Raw quotations remain character-for-character equal to the stored extracted source slice.
- Offset-derived IDs are contract-local source references only. Cross-version comparison never treats offsets as stable identities.
- Schema-only re-extraction never appears as a legislative change, unread update, or recent bill activity.
- Legacy and `2.0-legal-nlp` contracts remain readable. The 2.1 writer is disabled by default until compatible readers are deployed.
- The deterministic brief is public. User-owned LLM enhancement remains optional, private, and separate.
- Present all available roll-call votes and member positions without authentication.

## Information Hierarchy

The bill-detail page presents information in this order:

1. Bill identity, status, sponsor, introduced date, and policy areas.
2. **What this bill does:** the latest official CRS summary when available and clearly attributed. If CRS has not published one, show an honest deterministic orientation assembled from the official title, an explicit purpose clause when present, policy areas, and extraction coverage. Never label a count-only statement as a whole-bill summary.
3. **Bill at a glance:** counts of reader line items, financial provisions, deadlines/effective dates, structural groups, and roll-call votes. Counts describe recognized coverage, not importance.
4. **Plain-English breakdown:** every recognized operative provision and standalone deadline in source order, grouped by the complete federal hierarchy.
5. **Money in this bill:** every recognized financial provision in source order, with action, direction, amount wording, fiscal years, purpose, structural location, and source.
6. **Voting record:** all roll calls in reverse chronological order, with totals and grouped/searchable member positions.
7. **What changed:** real document, status, contract-semantic, and vote changes. Extractor rebuilds are excluded.
8. Source documents, contract history, limitations, and technical extraction details.

## Official CRS Summary and Deterministic Orientation

Congress.gov bill-specific summaries are written by CRS legislative analysts. Ingestion fetches the bill-specific summaries collection and stores the complete selected summary plus revision provenance:

- `summary_source`: `crs`, `source_metadata`, or blank.
- `summary_action_date`: legislative action date for the summary.
- `summary_version_code`: CRS action/version code.
- `summary_last_updated_at`: `lastSummaryUpdateDate`, falling back to `updateDate` when necessary.

Selection is deterministic:

1. Reject entries without usable text or a parseable `actionDate`.
2. Choose the greatest `actionDate`.
3. Within that date, choose the greatest `lastSummaryUpdateDate`, then `updateDate`.
4. Use `versionCode` and canonicalized text only as deterministic final tie-breakers; version codes are not assumed to be chronologically sortable because Congress documents that they have varied over time.

A usable CRS candidate always replaces a `source_metadata` fallback, even when the fallback inherited a later bill-metadata timestamp. A metadata fallback never replaces stored CRS text. Within CRS, a stored summary is replaced only when the candidate revision tuple is greater, or equal with identical provenance and corrected text from the same `summary_last_updated_at`. A partial or stale response cannot overwrite a newer stored revision.

CRS text contains HTML and may contain invalid markup. A tolerant `HTMLParser`-based converter preserves headings, paragraphs, and list items as plain text. Compact bill detail returns at most 1,200 characters from the first non-title content paragraph as `summary_preview`, cut at the last word boundary; `summary_has_more` is true when any text was omitted. “Read full official summary” fetches the complete stored text from a dedicated action. No storage truncation is used, and a long summary is not transferred during initial page load.

When no CRS summary exists, the page shows:

- “No official CRS summary is available yet.”
- The official bill title.
- A usable `source_metadata` description, when present, clearly labeled “Congress.gov source description” rather than CRS analysis.
- An explicit statutory purpose clause when the deterministic purpose rule finds one.
- All assigned policy-area labels in a compact disclosure.
- Recognized line-item, financial-item, and deadline counts.
- A direct transition to the full source-ordered breakdown.

This orientation is useful without pretending that counts or selected fragments summarize the entire bill.

## Structural Parsing and Controlled Display Text

The structural parser recognizes and orders the hierarchy emitted by Congress XML ingestion:

- division
- title and subtitle
- chapter and subchapter
- part and subpart
- account, subaccount, and nested subaccounts
- constitution article, normalized to the reader label “Article”
- section
- appropriations paragraph, subsection, paragraph, subparagraph, clause, subclause, item, and subitem

Every node has an offset-derived `source_id`, full ordered `section_path`, and exact source range. Repeated labels such as `(1)` are unique because their source IDs differ and their paths include every ancestor.

The clause parser handles enumerated lists, inherited modal actors, multiple clauses within a statutory sentence, conditions, and multiple explicit monetary clauses. It emits one supported claim per operative clause rather than one claim per punctuation-delimited sentence.

Controlled display normalization removes only known source artifacts:

- `<<NOTE: ...>>`
- `[[Page ...]]` and page/statute headers
- `[[QUOTED_BLOCK_START]]` / `[[QUOTED_BLOCK_END]]`
- paired congressional backticks/apostrophe quotation wrappers
- line-break hyphenation when the original token is deterministically reconstructable
- repeated whitespace and orphaned list punctuation

Normalization never changes raw evidence. It is tested against the previously observed H.R. 1 output.

Reader text is rendered from validated structured fields, not by displaying cleaned source fragments as if they were summaries. Each supported rule family owns a controlled template:

- requirement: “Requires [actor] to [action/effect].”
- prohibition: “Prohibits [actor] from [action/effect].”
- permission: “Allows [actor] to [action/effect].”
- amendment: “Changes [named law/section] by [operation/effect].”
- applicability: “Applies [rule] to [scope/date].”
- financial and timeline items use their typed action/date templates.

Templates require the structured slots needed to make a grammatical, legally faithful sentence. If a rule cannot fill its required slots, that rule does not fabricate a sentence: it emits a typed extraction warning and leaves the exact clause available in source/technical views. The renderer never invents an actor, beneficiary, causal effect, budget total, or policy rationale.

## Versioned 2.1 Reader Contract

New deterministic output uses:

- `schema_version: "2.1-legal-nlp"`
- `parser_version: "2.1.0"`
- `extractor_version: "federal-rules-2.1.0"`

The 2.0 schema remains immutable. The 2.1 contract keeps normalized claims for search, topics, evaluation, and semantic comparison while adding reader projections.

Contract-local IDs use category plus first evidence offset and a collision ordinal:

- `requirement-142-1`
- `financial-201-1`
- `timeline-350-1`
- `line-requirement-142-1`

These IDs are used only for references inside one immutable contract. They are not cross-version identities.

The reader projection contains:

```json
{
  "schema_version": "2.1-legal-nlp",
  "coverage_note": "The breakdown below contains 12 recognized operative line items across 5 sections, including 3 financial provisions and 2 deadlines or effective dates.",
  "orientation": {
    "purpose_clause": "Establishes a rural hospital grant program.",
    "purpose_line_item_id": "line-purpose-80-1"
  },
  "reader_stats": {
    "line_item_count": 12,
    "financial_item_count": 3,
    "timeline_item_count": 2,
    "definition_item_count": 4,
    "section_group_count": 5
  },
  "section_groups": [
    {
      "source_id": "section-100",
      "section_path": [
        {"level": "title", "label": "Title I", "heading": "Rural Health"},
        {"level": "section", "label": "Sec. 101", "heading": "Grant program"}
      ],
      "line_item_ids": ["line-requirement-142-1"],
      "section_financial_refs": ["financial-201-1"],
      "section_timeline_refs": []
    }
  ],
  "line_items": [
    {
      "id": "line-requirement-142-1",
      "source_id": "requirement-142-1",
      "section_id": "section-100",
      "section_path": [
        {"level": "title", "label": "Title I", "heading": "Rural Health"},
        {"level": "section", "label": "Sec. 101", "heading": "Grant program"}
      ],
      "kind": "requirement",
      "display_text": "Requires the Secretary to award grants to rural hospitals.",
      "actor": "the Secretary",
      "action": "award grants",
      "effect": "rural hospitals may receive grants",
      "claim_refs": ["requirement-142-1"],
      "exact_financial_refs": [],
      "timeline_refs": [],
      "definition_refs": ["definition-90-1"],
      "evidence_paths": ["line_items[0].display_text", "requirements[0].display_text"]
    }
  ],
  "financial_items": [
    {
      "id": "financial-201-1",
      "section_id": "section-100",
      "section_path": [
        {"level": "title", "label": "Title I", "heading": "Rural Health"},
        {"level": "section", "label": "Sec. 101", "heading": "Grant program"}
      ],
      "financial_action": "appropriation",
      "direction": "increase",
      "display_text": "Appropriates $500,000,000 for rural hospital grants for fiscal year 2026.",
      "amount": "500000000.00",
      "amount_type": "specified",
      "currency": "USD",
      "fiscal_years": [2026],
      "purpose": "rural hospital grants",
      "evidence_paths": ["financial_items[0].display_text", "financial_items[0].amount"]
    }
  ]
}
```

The stored contract has no `maxItems` cap on reader line items, financial items, timelines, or normalized claim arrays. Public reader APIs paginate these arrays instead of embedding them all in bill detail.

`coverage_note` describes deterministic extraction coverage and limitations. The UI never labels or positions it as a whole-bill summary. `orientation.purpose_clause` is populated only by an explicit statutory-purpose rule and references its evidence-backed reader line item through `purpose_line_item_id`; both are `null` when the text has no supported purpose construction. The attributed CRS text, or the explicit no-CRS orientation, owns the “What this bill does” section.

The immutable contract keeps complete `exact_financial_refs`, `timeline_refs`, `definition_refs`, `section_financial_refs`, and `section_timeline_refs`. Public reader-page objects do not copy those potentially unbounded arrays. For each line item they return exact counts and at most three compact, source-ordered financial/timeline previews plus a linked-definition count. They also return one bounded supplement per section represented on the page with section-level counts. Financial, timeline, and definition projections carry the complete structural path so standalone entries remain understandable. “Show all” uses the filtered paginated financial, timeline, or definition endpoint. The three-item preview is a transport boundary, not an importance judgment.

## Financial Provision Model and Coverage

Financial provisions use independent semantic axes:

- `financial_action`: `appropriation`, `authorization`, `allocation`, `transfer`, `rescission`, `reduction`, `cancellation`, `set_aside`, `limitation`, or `other_explicit`.
- `direction`: `increase`, `decrease`, `neutral_transfer`, or `limit`.
- `amount_type`: `specified`, `such_sums`, `percentage`, or `ceiling`.

The extractor uses `finditer` and clause boundaries so multiple amounts in one sentence produce distinct financial items. Supported tests cover appropriations, authorizations, transfers, rescissions, reductions, cancellations, set-asides, limitations, “such sums,” percentages, per-year amounts, and explicit account/purpose text.

Every recognized financial item appears exactly once in the dedicated ledger. The page title is “Money in this bill,” and its coverage disclosure names the supported actions. It does not claim to be a CBO cost estimate or a complete estimate of downstream fiscal impact.

## Financial and Timeline Association

Same-section location is not enough to assert that money belongs to a particular operative line item.

- `exact_financial_refs` is populated only when the financial and operative claims share the same clause evidence or an explicit program/account/purpose reference.
- Other financial provisions appear once in `section_groups[*].section_financial_refs` under “Money in this section.”
- Financial-only sections still receive a section group and standalone reader entry.
- Deadlines/effective dates follow the same rule: exact clause matches attach to a line item; otherwise they appear once at section level.
- A timeline-only section produces a standalone deadline/effective-date line item.

Definitions are linked to reader items only by exact normalized term occurrence in the operative clause. Unlinked definitions appear in a collapsed “Key terms” section rather than disappearing into technical diagnostics.

## Evidence Storage and Reader APIs

Evidence candidates longer than 4,000 characters are split into contiguous exact chunks. Concatenating chunks in `start_char` order reconstructs the original source span without dropped or altered characters.

Bill detail and contract history do not embed every contract array and evidence quotation. The existing contract viewset gains bounded reader actions:

- `GET /api/contracts/{id}/reader-items/?page=1&page_size=25`
- `GET /api/contracts/{id}/financial-items/?page=1&page_size=25&financial_action=transfer&fiscal_year=2026&line_item_id=line-requirement-142-1`
- `GET /api/contracts/{id}/timeline-items/?page=1&page_size=25&section_id=section-100`
- `GET /api/contracts/{id}/definition-items/?page=1&page_size=25&line_item_id=line-requirement-142-1`
- `GET /api/contracts/{id}/definition-items/?page=1&page_size=25&unlinked=true`
- `GET /api/contracts/{id}/evidence/?line_item_id=line-requirement-142-1&page=1&page_size=25`
- `GET /api/contracts/{id}/evidence/?financial_item_id=financial-201-1&page=1&page_size=25`
- `GET /api/contracts/{id}/evidence/?definition_item_id=definition-90-1&page=1&page_size=25`
- `GET /api/bills/{id}/official-summary/`

Compact bill detail returns only the official-summary preview and provenance plus contract identity, provenance, `coverage_note`, `reader_stats`, and version information. Contract list endpoints use a compact serializer. The full stored JSON remains available only from the explicit contract-detail endpoint for technical inspection.

Reader actions use explicit public serializers that omit evidence paths and replace potentially unbounded reference arrays with counts and the bounded previews above. Financial, timeline, and definition actions accept validated contract-local filters so every association and every unlinked key term remains reachable through pagination.

Evidence actions resolve IDs through the immutable contract JSON, validate every requested evidence path, query only those `EvidenceSpan` rows, deduplicate identical offsets, paginate the ordered chunks, and return source order. The frontend fetches the first evidence page only after the user opens “Read bill text,” and exposes “Load more source text” when more chunks exist. Full-document `text_url` and `download_url` remain available. The official-summary action is likewise fetched only after “Read full official summary” or “Read full source description”; it returns the complete stored text and provenance for that bill, and the UI labels it from `summary_source`.

## Cross-Version Comparison and Backfill

Cross-version comparison ignores offset-derived IDs, evidence paths, array indexes, schema metadata, and reader-only projections.

The comparison pipeline:

1. Adapts 2.0 and 2.1 normalized claims to a common semantic shape.
2. Buckets claims by normalized structural label path, category, rule family, and stable anchor fields.
3. Consumes exact semantic matches first.
4. Considers remaining items within a bucket for diff correspondence only when stable anchors agree and normalized text similarity meets a conservative documented threshold; deterministic source order breaks ties. Below-threshold items remain explicit additions/removals. Similarity is never used to merge extraction output.
5. Reports mutable fields such as amount, fiscal years, action text, or deadlines as changes rather than remove/add churn.

Tests prepend text before an unchanged section, reorder unrelated sections, replace a provision with an unrelated one, change one funding amount, and compare 2.0 with an equivalent 2.1 contract.

Schema backfills pass `generation_reason="schema_backfill"` through contract generation and downstream topic work. They may update `Bill.latest_contract`, topics, similarity, and search, but they create neither `contract_update` nor `topic_update` change events, advance no bill activity sequence/timestamp, and increase no unread counts when the source document is unchanged. Real new document versions continue recording changes normally. As a second guard, an ingestion-path re-extraction records a contract change only when the active document changed or semantic comparison finds a substantive change; a schema/hash change alone is not legislative activity.

## Search Projection

Search no longer generically flattens the entire contract JSON. A curated projection indexes exactly once:

- official CRS or deterministic orientation text
- reader line-item display text
- financial display text, purpose, action, and fiscal years
- timeline display text
- definition terms and definitions
- bill metadata and policy areas
- active full-document text in the existing lower-weight document source

The contract projection indexes the explicit statutory purpose, line items, financial/timeline text, and definitions; the separate bill-metadata projection already owns CRS/source summary text, title, sponsor, status, and policy areas. It excludes the extraction count-only `coverage_note`, source IDs, array indexes, schema metadata, evidence paths, warnings, and duplicate normalized/reader renderings.

## Voting Record

The existing vote list/detail APIs remain authoritative. The reader UI:

- shows roll calls newest first;
- displays question, chamber, date, result, yeas, nays, and source link;
- validates displayed totals against returned records without hiding discrepancies;
- groups member positions into Yes, No, Present, Not voting, and Other;
- supports member-name search and party/state filters;
- sorts members deterministically by state, district, then name;
- links each member to representative details;
- preserves isolated loading, empty, retry, pagination, and stale-request states.

## Compatible Rollout

`LEGAL_NLP_V21_WRITE_ENABLED` defaults to `False`.

Rollout order:

1. Deploy backend read APIs and frontend 2.1 readers while the writer remains disabled.
2. Verify legacy, 2.0, and seeded 2.1 read paths.
3. Enable 2.1 writing for new extraction.
4. Preview a bounded schema backfill.
5. Refuse backfill execution unless the 2.1 writer flag is enabled; then execute bounded batches while monitoring failures, response sizes, and activity suppression.
6. Retain the ability to disable new writes without making persisted 2.1 contracts unreadable.

## Quality Gates

- The previously observed H.R. 1 artifact-heavy excerpt renders without note markers, page headers, quotation wrappers, or broken line-item grammar while raw evidence remains exact.
- Every controlled line item is a complete sentence produced from validated typed slots; incomplete extractions remain warnings rather than malformed reader copy.
- Full hierarchy tests include division, subchapter, account, repeated subdivisions, clauses, and subitems.
- Multiple monetary clauses in one sentence produce multiple financial items.
- Rescissions, transfers, reductions, set-asides, limitations, authorizations, and appropriations retain distinct legal meaning.
- More than 100 recognized financial items remain accessible through pagination with no loss.
- An insertion before unchanged provisions does not create false remove/add comparison changes.
- A 2.0→2.1 schema backfill creates no legislative activity event.
- Every reader item and financial item resolves to at least one exact evidence chunk; a source span over 4,000 characters reconstructs exactly.
- Bill detail remains bounded; the 1,200-character official-summary preview, 25-item reader pages, three-item association previews, and paginated evidence-on-demand are tested independently.
- CRS malformed HTML, title-only first paragraphs, republished corrections, stale responses, and missing summaries are covered.
- No-CRS pages clearly state the limitation and still orient the reader with title, purpose when explicit, policy areas, and complete recognized breakdown access.
- Search contains reader text once and excludes internal IDs/evidence metadata.
- Every returned vote and member position remains accessible in a grouped, searchable view.
- Legacy and 2.0 history continue rendering and comparing safely.
- Backend tests, frontend unit/component tests, type checking, lint, production build, Playwright, and extension regression tests pass.
