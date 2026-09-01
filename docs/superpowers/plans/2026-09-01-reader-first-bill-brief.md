# Reader-First Bill Brief Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the extraction-debug bill page with a bounded, reader-first brief that explains the bill, presents every provision recognized by the deterministic grammar, preserves every recognized financial provision, exposes exact evidence on demand, and shows complete voting records.

**Architecture:** Keep immutable 2.0 contracts and build a gated `2.1-legal-nlp` writer with complete source hierarchy, artifact-free controlled text, typed financial provisions, contract-local source IDs, and semantic cross-version comparison. Add paginated reader/financial/timeline/definition/evidence actions plus a lazy official-summary action so the bill page never downloads an unbounded contract or long CRS summary during initial render. Deploy compatible readers first, then enable 2.1 writes and activity-silent schema backfills.

**Tech Stack:** Django 5.2, Django REST Framework, PostgreSQL, Celery, Python deterministic extraction rules, JSON Schema 2020-12, Next.js 16, React 19, TypeScript 5, Vitest, Testing Library, and Playwright.

**Spec:** `docs/superpowers/specs/2026-09-01-reader-first-bill-brief-design.md`

**External contracts:** [Library of Congress bill API documentation](https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/BillEndpoint.md) and [summary API documentation](https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/SummariesEndpoint.md)

## Global Constraints

- The deterministic path must not call an LLM, hosted NLP service, embedding service, or downloadable statistical model.
- Do not rank, score, or select provisions by presumed importance, consequence, ideology, or monetary size.
- Preserve every provision recognized by the supported grammar in evidence-source order.
- Preserve every recognized financial provision; there is no backend or frontend top-N cap.
- Never call an authorization, transfer, rescission, reduction, cancellation, set-aside, or limitation an appropriation.
- Do not display a computed grand total unless the statute explicitly provides an additive total.
- Offset-derived source IDs are valid only within one immutable contract and must never be cross-version comparison identities.
- Known source artifacts may be removed from controlled display text only. Evidence quotations remain exact source slices.
- Schema backfills do not create user-visible bill changes, unread updates, or recent activity.
- `LEGAL_NLP_V21_WRITE_ENABLED` defaults to `False`; deploy compatible readers before enabling it.
- Legacy and `2.0-legal-nlp` read/history behavior remains available.
- The baseline brief is public; existing user-owned LLM enhancements remain optional and separate.
- Public reader and evidence endpoints are paginated; full evidence and full official summaries are fetched only on request.
- Every shell command in this repository must run through `rtk`.

---

## File and Responsibility Map

### Backend extraction and ingestion

- `apps/ingestion/congress_client.py`: validated bill-summary pagination.
- `apps/ingestion/tasks.py`: CRS revision selection/persistence and durable work dispatch.
- `apps/legislation/models.py`: CRS provenance fields.
- `apps/legislation/extraction/types.py`: 2.0/2.1 constants, source identity, reader, and financial types.
- `apps/legislation/extraction/federal_structure.py`: complete Congress XML hierarchy.
- `apps/legislation/extraction/federal_clauses.py`: clause/list segmentation and inherited modal context.
- `apps/legislation/extraction/display_text.py`: controlled artifact cleanup.
- `apps/legislation/extraction/financial_rules.py`: multi-amount financial extraction.
- `apps/legislation/extraction/reader_brief.py`: section groups, line items, association, and orientation metadata.
- `apps/legislation/extraction/reader_renderer.py`: immutable 2.1 JSON and evidence assembly.
- `apps/legislation/extraction/renderer.py`: unchanged 2.0 rendering path.
- `apps/legislation/extraction/schema.py`: version-aware schema and chunked evidence validation.
- `apps/legislation/extraction/schemas/contract_v2_1.json`: immutable 2.1 schema.
- `apps/legislation/extraction/service.py`: gated 2.0/2.1 writer selection.

### Backend persistence and APIs

- `apps/legislation/tasks.py`: generation reason, activity-silent backfill, persistence, topics, and search enqueueing.
- `apps/legislation/comparison.py`: semantic mixed-schema comparison that ignores offsets.
- `apps/legislation/search_index.py`: curated contract search projection.
- `apps/legislation/reader_api.py`: reader/financial/timeline/definition pagination, bounded association previews, evidence resolution, and official-summary projection.
- `apps/legislation/serializers.py`: compact contract summaries and strict reader query serializers.
- `apps/legislation/views.py`: contract reader, financial, timeline, definition, and evidence actions plus full-summary expansion.
- `apps/legislation/management/commands/backfill_contracts.py`: preview-first schema backfill.
- `config/settings/base.py`: disabled-by-default 2.1 writer flag.

### Frontend

- `lib/contracts.ts`: 2.0/2.1 summary and page types with strict runtime guards.
- `lib/api.ts`: compact bill detail plus paginated reader, financial, timeline, definition, and evidence clients.
- `app/bills/[id]/bill-brief.tsx`: summary/orientation, counts, and paginated source-ordered line items.
- `app/bills/[id]/financial-ledger.tsx`: server-filtered complete financial ledger.
- `app/bills/[id]/source-evidence.tsx`: evidence-on-open and document links.
- `app/bills/[id]/voting-record.tsx`: grouped, searchable complete roll-call records.
- `app/bills/[id]/contract-section.tsx`: version dispatch and legacy compatibility.
- `app/bills/[id]/page.tsx`: page hierarchy and isolated request state.

---

### Task 1: Ingest Complete CRS Summary Revisions Safely

**Files:**
- Modify: `legislation-tracker-backend/apps/ingestion/congress_client.py`
- Modify: `legislation-tracker-backend/apps/ingestion/tasks.py`
- Modify: `legislation-tracker-backend/apps/legislation/models.py`
- Create: `legislation-tracker-backend/apps/legislation/migrations/0013_bill_summary_provenance.py`
- Modify: `legislation-tracker-backend/apps/legislation/serializers.py`
- Modify: `legislation-tracker-backend/apps/ingestion/tests/test_congress_client.py`
- Modify: `legislation-tracker-backend/apps/ingestion/tests/test_tasks.py`
- Modify: `legislation-tracker-backend/apps/legislation/tests/test_public_api.py`

**Interfaces:**
- Produces: `bill_summaries(congress: int, bill_type: str, bill_number: str) -> list[dict[str, object]]`
- Produces: `CRSSummaryRevision(text, action_date, version_code, last_updated_at)`
- Produces: `select_latest_crs_summary(items: Sequence[dict[str, object]]) -> CRSSummaryRevision | None`
- Produces: `clean_crs_summary(value: object) -> str`
- Produces: `Bill.summary_source`, `Bill.summary_action_date`, `Bill.summary_version_code`, and `Bill.summary_last_updated_at`

- [ ] **Step 1: Write failing paginator validation tests**

Test a 251-entry response, a repeated page, a dictionary payload, an explicit null payload, and a non-dictionary entry:

```python
@pytest.mark.parametrize("payload", ({}, None, "invalid"))
def test_bill_summaries_rejects_non_list_payload(monkeypatch, payload):
    monkeypatch.setattr(
        congress_client,
        "_request",
        lambda *args, **kwargs: {"summaries": payload},
    )
    monkeypatch.setattr(congress_client, "_throttle", lambda: None)

    with pytest.raises(CongressAPIError, match="invalid summaries payload"):
        congress_client.bill_summaries(119, "hr", "1")
```

- [ ] **Step 2: Run the client test and verify failure**

```bash
rtk run "cd legislation-tracker-backend && .venv/bin/pytest apps/ingestion/tests/test_congress_client.py -q"
```

Expected: FAIL because `bill_summaries` is absent and the shared paginator coerces falsey invalid values to an empty list.

- [ ] **Step 3: Make collection pagination reject explicit invalid payloads**

Replace falsey coercion in `_paginated_bill_collection`:

```python
raw_page = data.get(key, [])
if not isinstance(raw_page, list):
    raise CongressAPIError(
        f"Congress bill {collection} returned an invalid {key} payload"
    )
page = raw_page
```

Implement `bill_summaries` through this helper and retain `limit=250`, offset progression, repeated-page detection, throttling, and request byte/time limits.

- [ ] **Step 4: Write failing selection, correction, and malformed-HTML tests**

Cover:

- a newer legislative action;
- two summaries on one action date with different `lastSummaryUpdateDate` values;
- a re-published correction with the same action date and version code;
- a stale partial response that must not replace stored data;
- first-arriving CRS text replacing a newer-dated `source_metadata` fallback;
- missing/older source metadata never replacing stored CRS text;
- version codes that do not sort chronologically;
- a title-only first paragraph;
- malformed nested list/paragraph markup;
- source metadata used only when no CRS summary exists.

```python
def test_latest_summary_uses_revision_time_not_version_code_order():
    selected = select_latest_crs_summary(
        [
            {
                "actionDate": "2025-03-01",
                "versionCode": "87",
                "lastSummaryUpdateDate": "2025-03-02T10:00:00Z",
                "text": "<p>Older publication</p>",
            },
            {
                "actionDate": "2025-03-01",
                "versionCode": "01",
                "lastSummaryUpdateDate": "2025-03-03T10:00:00Z",
                "text": "<p>Corrected publication</p>",
            },
        ]
    )

    assert selected.text == "Corrected publication"
    assert selected.version_code == "01"
```

- [ ] **Step 5: Add complete summary provenance fields**

Add:

```python
summary_source = models.CharField(max_length=32, blank=True, default="")
summary_action_date = models.DateField(blank=True, null=True)
summary_version_code = models.CharField(max_length=16, blank=True, default="")
summary_last_updated_at = models.DateTimeField(blank=True, null=True)
```

Create migration `0013_bill_summary_provenance.py` depending on `0012_assign_fallback_topics_to_existing_bills`.

- [ ] **Step 6: Implement tolerant plain-text conversion**

Use a small `HTMLParser` subclass rather than regular expressions as the primary parser. Preserve block boundaries and list bullets, ignore script/style content, unescape entities, collapse intra-line whitespace, and remove a duplicate leading title only for presentation metadata—not from stored summary text.

```python
class CRSPlainTextParser(HTMLParser):
    BLOCK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li"}

    def handle_starttag(self, tag, attrs):
        if tag == "li":
            self.parts.extend(("\n", "- "))
        elif tag in self.BLOCK_TAGS or tag == "br":
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)
```

Normalize the parser result line-by-line and store the complete result.

- [ ] **Step 7: Persist only monotonic CRS revisions**

Represent the stored revision as:

```python
def stored_summary_revision(bill):
    return (
        bill.summary_action_date or date.min,
        bill.summary_last_updated_at or datetime.min.replace(tzinfo=UTC),
        bill.summary_version_code or "",
    )
```

Select CRS revisions by action date, then publication/update timestamp, then deterministic version/text tie-breakers. A usable `crs` candidate always supersedes `source_metadata`; `source_metadata` never supersedes stored CRS. Within the same source, never overwrite a greater stored revision. Set `summary_source="source_metadata"` only when no CRS summary exists and metadata supplies the only usable summary.

Extend `compute_metadata_hash` with the source, action date, version code, and revision timestamp so equal text with newer provenance does not short-circuit. Add defaults to avoid breaking existing callers and a test documenting the one-time hash refresh for existing rows.

- [ ] **Step 8: Expose provenance and run focused tests**

Add all four provenance fields to `BillDetailSerializer` and run:

```bash
rtk run "cd legislation-tracker-backend && .venv/bin/pytest apps/ingestion/tests/test_congress_client.py apps/ingestion/tests/test_tasks.py apps/legislation/tests/test_public_api.py -q"
```

Expected: PASS.

- [ ] **Step 9: Commit CRS ingestion**

```bash
rtk git add legislation-tracker-backend/apps/ingestion/congress_client.py legislation-tracker-backend/apps/ingestion/tasks.py legislation-tracker-backend/apps/ingestion/tests legislation-tracker-backend/apps/legislation/models.py legislation-tracker-backend/apps/legislation/migrations/0013_bill_summary_provenance.py legislation-tracker-backend/apps/legislation/serializers.py legislation-tracker-backend/apps/legislation/tests/test_public_api.py
rtk git commit -m "feat(summaries): preserve complete CRS revisions"
```

### Task 2: Parse the Complete Federal Hierarchy and Clean Reader Text

**Files:**
- Modify: `legislation-tracker-backend/apps/legislation/extraction/types.py`
- Modify: `legislation-tracker-backend/apps/legislation/extraction/federal_structure.py`
- Create: `legislation-tracker-backend/apps/legislation/extraction/federal_clauses.py`
- Create: `legislation-tracker-backend/apps/legislation/extraction/display_text.py`
- Modify: `legislation-tracker-backend/apps/legislation/extraction/legal_rules.py`
- Modify: `legislation-tracker-backend/apps/legislation/tests/test_federal_structure.py`
- Create: `legislation-tracker-backend/apps/legislation/tests/test_federal_clauses.py`
- Create: `legislation-tracker-backend/apps/legislation/tests/test_display_text.py`
- Modify: `legislation-tracker-backend/apps/legislation/tests/test_legal_rules.py`

**Interfaces:**
- Produces: `SectionPathItem(label: str, heading: str | None, level: str)`
- Produces: `StructuralSection.source_id` and `StructuralSection.path`
- Produces: `iter_operative_clauses(source_text, sections) -> Iterator[tuple[StructuralSection, SourceSpan, ModalContext | None]]`
- Produces: `normalize_reader_fragment(value: str) -> str`
- Preserves: raw `SourceSpan.text`, `start_char`, and `end_char`

- [ ] **Step 1: Write failing full-hierarchy tests**

Use a source containing `DIVISION`, `TITLE`, `SUBCHAPTER`, `ACCOUNT`, `SEC.`, `(a)`, `(1)`, `(A)`, and `(i)`. Assert every path and unique source ID:

```python
def test_structure_preserves_division_account_and_nested_provisions():
    sections = parse_federal_structure(FULL_HIERARCHY_SOURCE)
    clause = next(section for section in sections if section.label == "(i)")

    assert [item.level for item in clause.path] == [
        "division", "title", "subchapter", "account", "section",
        "subsection", "paragraph", "subparagraph", "clause",
    ]
    assert clause.source_id == f"section-{clause.span.start_char}"
```

- [ ] **Step 2: Run hierarchy tests and verify missing levels**

```bash
rtk run "cd legislation-tracker-backend && .venv/bin/pytest apps/legislation/tests/test_federal_structure.py -q"
```

Expected: FAIL because the parser currently recognizes only title/subtitle/part/subpart/chapter plus generic subdivisions.

- [ ] **Step 3: Expand structural markers to match ingestion output**

Define ordered ranks for the exact container/provision vocabulary emitted by `document_download.py`. Named levels use named regular expressions; parenthesized provision levels continue using contextual rank inference.

```python
CONTAINER_RANKS = {
    "division": 0,
    "title": 10,
    "subtitle": 20,
    "chapter": 30,
    "subchapter": 40,
    "part": 50,
    "subpart": 60,
    "account": 70,
    "subaccount": 80,
    "article": 90,
}
```

Include `subdivision`, `subsubaccount`, and `subsubsubaccount` aliases at deterministic ranks. Build `path` from the active parser stack and current marker. IDs remain source-offset based and are documented as contract-local.

- [ ] **Step 4: Write failing clause/list inheritance tests**

Cover one modal actor followed by `(A)` and `(B)` actions, two modals in one sentence, a leading condition, and an amendment quotation block that must remain excluded.

```python
def test_clause_parser_inherits_actor_without_combining_list_items():
    claims = extract_modality_claims(INHERITED_LIST_SOURCE, parse_federal_structure(INHERITED_LIST_SOURCE))

    assert [claim.fields["action"] for claim in claims] == [
        "publish the report",
        "send the report to Congress",
    ]
    assert {claim.fields["actor"] for claim in claims} == {"The Secretary"}
```

- [ ] **Step 5: Implement clause segmentation**

Move operative iteration into `federal_clauses.py`. Split on structural markers before punctuation, carry explicit modal/actor context only from the nearest valid ancestor, and emit one exact `SourceSpan` per clause. Do not perform fuzzy merging.

- [ ] **Step 6: Write failing artifact-cleanup tests using observed text**

Include exact examples containing `<<NOTE: Deadline.>>`, `[[Page 139 STAT.`, congressional backticks, `re- evaluate`, and an orphaned list marker. Assert controlled output is clean and evidence remains exact:

```python
def test_reader_cleanup_does_not_mutate_evidence():
    raw = "``(A) <<NOTE: Deadline.>> The Secretary shall re-\n evaluate the plan. [[Page 139 STAT. 81]]"
    span = SourceSpan(raw, 200, 200 + len(raw))

    assert normalize_reader_fragment(raw) == "The Secretary shall reevaluate the plan."
    assert span.text == raw
    assert (span.start_char, span.end_char) == (200, 200 + len(raw))
```

- [ ] **Step 7: Implement allowlisted display normalization**

Compile explicit artifact patterns, remove only recognized annotations/wrappers, reconstruct line-break hyphenation only across `-\n`, collapse whitespace, strip orphaned leading connectors, and normalize terminal punctuation. Never call this helper when creating `EvidenceCandidate`.

- [ ] **Step 8: Route every rule through structural identity and cleanup**

Extend `ExtractedClaim` with `source_id`, `section_id`, `section_path`, and `rule_id`. Use raw spans for evidence and normalized fields for rendering. Add a single `_claim(...)` constructor so all rule families follow the same invariant.

- [ ] **Step 9: Run and commit structural/cleanup tests**

```bash
rtk run "cd legislation-tracker-backend && .venv/bin/pytest apps/legislation/tests/test_federal_structure.py apps/legislation/tests/test_federal_clauses.py apps/legislation/tests/test_display_text.py apps/legislation/tests/test_legal_rules.py -q"
rtk git add legislation-tracker-backend/apps/legislation/extraction/types.py legislation-tracker-backend/apps/legislation/extraction/federal_structure.py legislation-tracker-backend/apps/legislation/extraction/federal_clauses.py legislation-tracker-backend/apps/legislation/extraction/display_text.py legislation-tracker-backend/apps/legislation/extraction/legal_rules.py legislation-tracker-backend/apps/legislation/tests
rtk git commit -m "feat(extraction): parse and clean federal provisions"
```

Expected: all focused tests pass.

### Task 3: Build the Gated 2.1 Reader and Financial Contract

**Files:**
- Modify: `legislation-tracker-backend/config/settings/base.py`
- Modify: `legislation-tracker-backend/.env.example`
- Modify: `legislation-tracker-backend/apps/legislation/extraction/types.py`
- Create: `legislation-tracker-backend/apps/legislation/extraction/financial_rules.py`
- Create: `legislation-tracker-backend/apps/legislation/extraction/reader_brief.py`
- Create: `legislation-tracker-backend/apps/legislation/extraction/reader_renderer.py`
- Create: `legislation-tracker-backend/apps/legislation/extraction/schemas/contract_v2_1.json`
- Modify: `legislation-tracker-backend/apps/legislation/extraction/schema.py`
- Modify: `legislation-tracker-backend/apps/legislation/extraction/service.py`
- Create: `legislation-tracker-backend/apps/legislation/tests/test_financial_rules.py`
- Create: `legislation-tracker-backend/apps/legislation/tests/test_reader_brief.py`
- Create: `legislation-tracker-backend/apps/legislation/tests/test_reader_renderer.py`
- Modify: `legislation-tracker-backend/apps/legislation/tests/test_extraction_schema.py`
- Modify: `legislation-tracker-backend/apps/legislation/tests/test_extraction_service.py`

**Interfaces:**
- Produces: `V2_SCHEMA_VERSION`, `V21_SCHEMA_VERSION`, `V2_EXTRACTOR_VERSION`, and `V21_EXTRACTOR_VERSION`
- Produces: `active_extractor_version() -> str`
- Produces: `FinancialAction`, `FinancialDirection`, and `FinancialAmountType`
- Produces: `extract_financial_claims(source_text, sections) -> tuple[ExtractedClaim, ...]`
- Produces: `build_reader_brief(claims, sections) -> ReaderBrief`
- Produces: `render_reader_claim(claim: ExtractedClaim) -> RenderedReaderClaim | ExtractionWarning`
- Produces: `split_evidence_span(span, max_chars=4000) -> tuple[SourceSpan, ...]`
- Produces: a valid immutable `2.1-legal-nlp` contract while retaining the existing 2.0 renderer

- [ ] **Step 1: Add the disabled-by-default writer flag**

```python
LEGAL_NLP_V21_WRITE_ENABLED = env.bool("LEGAL_NLP_V21_WRITE_ENABLED", default=False)
```

Document `LEGAL_NLP_V21_WRITE_ENABLED=False` in `.env.example`. Define:

```python
def active_extractor_version() -> str:
    return (
        V21_EXTRACTOR_VERSION
        if settings.LEGAL_NLP_V21_WRITE_ENABLED
        else V2_EXTRACTOR_VERSION
    )
```

Do not replace the 2.0 renderer or schema.

- [ ] **Step 2: Write failing multi-action financial tests**

Cover:

- two different amounts in one sentence;
- appropriation versus authorization;
- allocation and set-aside;
- transfer with source and destination;
- rescission, reduction, and cancellation;
- limitation/ceiling;
- “such sums as may be necessary”;
- percentage amounts;
- repeated annual amount wording;
- inherited fiscal-year and account context;
- a forbidden non-financial percentage false positive.

```python
def test_financial_rules_emit_each_amount_and_preserve_direction():
    claims = extract_financial_claims(MULTI_AMOUNT_SOURCE, parse_federal_structure(MULTI_AMOUNT_SOURCE))

    assert [(item.fields["financial_action"], item.fields["amount"]) for item in claims] == [
        ("appropriation", "500000000.00"),
        ("rescission", "75000000.00"),
    ]
    assert [item.fields["direction"] for item in claims] == ["increase", "decrease"]
```

- [ ] **Step 3: Implement independent financial axes**

Use `finditer` within clause boundaries. Each item includes:

```python
{
    "financial_action": "appropriation",
    "direction": "increase",
    "amount": "500000000.00",
    "amount_type": "specified",
    "currency": "USD",
    "fiscal_years": [2026],
    "purpose": "rural hospital grants",
    "source_account": None,
    "destination_account": None,
}
```

Do not reuse the old rule that maps every affirmative operational amount to an appropriation. Preserve explicit verbs and reject ambiguous amounts lacking a supported financial context.

- [ ] **Step 4: Write failing section-group and association tests**

Create one section with two programs and one financial clause. Assert the money is section-level unless evidence or explicit program purpose identifies exactly one line item. Add timeline-only and definition-reference cases.

```python
def test_same_section_alone_does_not_create_line_level_financial_link():
    brief = build_reader_brief(claims, sections)

    assert all(item.exact_financial_refs == () for item in brief.line_items)
    assert brief.section_groups[0].section_financial_refs == ("financial-240-1",)
```

Add table-driven renderer cases for requirement, prohibition, permission, amendment, applicability, financial, and timeline claims. Assert each result is a complete sentence with the expected actor/action/effect and no raw marker fragments. Missing required structured slots must produce a typed warning rather than text such as “is required to be” or a section-number-only line item.

- [ ] **Step 5: Implement reader line items and groups**

Build source-ordered `ReaderLineItem`, `ReaderSectionGroup`, and financial/timeline references. Render display text only through rule-family templates with validated required slots; never promote a cleaned fragment to reader copy merely because it is non-empty. Exact links require shared evidence offsets or an explicit normalized program/account/purpose reference. Create standalone financial and timeline line items when a section has no operative line. Link definitions by exact normalized term occurrence only.

Line-item IDs use `line-{primary_source_id}`. They remain contract-local.

- [ ] **Step 6: Write failing long-evidence reconstruction tests**

```python
def test_long_evidence_chunks_reconstruct_exact_source():
    span = SourceSpan(text="x" * 9_001, start_char=100, end_char=9_101)
    chunks = split_evidence_span(span)

    assert all(len(chunk.text) <= 4_000 for chunk in chunks)
    assert "".join(chunk.text for chunk in chunks) == span.text
    assert [(chunk.start_char, chunk.end_char) for chunk in chunks] == [
        (100, 4_100), (4_100, 8_100), (8_100, 9_101),
    ]
```

- [ ] **Step 7: Implement immutable 2.1 schema and evidence validation**

The 2.1 schema requires `coverage_note`, an `orientation` object with nullable `purpose_clause` and matching `purpose_line_item_id`, `reader_stats`, `section_groups`, `line_items`, `financial_items`, timelines, normalized claim arrays, complete structural paths, source IDs, exact/section associations, and evidence paths. Require that a non-null purpose ID resolves to an evidence-backed line item with the same controlled text. Do not set `maxItems` on substantive arrays or association-reference arrays; completeness lives in the immutable contract and response bounding happens in the public projections. Keep bounded structural-path depth and sensible scalar `maxLength` constraints.

Make schema loading version-keyed:

```python
SCHEMA_FILES = {
    V2_SCHEMA_VERSION: "contract_v2.json",
    V21_SCHEMA_VERSION: "contract_v2_1.json",
}

@lru_cache(maxsize=len(SCHEMA_FILES))
def _load_schema(schema_version: str) -> dict[str, Any]:
    ...
```

Validate all references and require evidence for every visible reader/financial/timeline field. Split oversized evidence before the 4,000-character validation boundary.

- [ ] **Step 8: Preserve 2.0 and gate 2.1 in the service**

```python
if settings.LEGAL_NLP_V21_WRITE_ENABLED:
    return reader_renderer.render_contract(...)
return renderer.render_contract(...)
```

Add tests proving default extraction remains 2.0, `override_settings(LEGAL_NLP_V21_WRITE_ENABLED=True)` produces 2.1, and both validate against their own immutable schema.

- [ ] **Step 9: Run focused extraction tests**

```bash
rtk run "cd legislation-tracker-backend && .venv/bin/pytest apps/legislation/tests/test_financial_rules.py apps/legislation/tests/test_reader_brief.py apps/legislation/tests/test_reader_renderer.py apps/legislation/tests/test_extraction_schema.py apps/legislation/tests/test_extraction_service.py -q"
```

Expected: PASS, including multiple amounts, negative financial actions, standalone deadlines, exact associations, 101 financial provisions, long evidence reconstruction, default 2.0, and gated 2.1.

- [ ] **Step 10: Commit the gated reader contract**

```bash
rtk git add legislation-tracker-backend/config/settings/base.py legislation-tracker-backend/.env.example legislation-tracker-backend/apps/legislation/extraction legislation-tracker-backend/apps/legislation/tests
rtk git commit -m "feat(contract): add gated reader-first contract"
```

### Task 4: Make Persistence, Comparison, Search, and Backfill Semantically Safe

**Files:**
- Modify: `legislation-tracker-backend/apps/legislation/tasks.py`
- Modify: `legislation-tracker-backend/apps/ingestion/tasks.py`
- Modify: `legislation-tracker-backend/apps/legislation/comparison.py`
- Modify: `legislation-tracker-backend/apps/legislation/search_index.py`
- Modify: `legislation-tracker-backend/apps/legislation/management/commands/backfill_contracts.py`
- Modify: `legislation-tracker-backend/apps/legislation/tests/test_tasks.py`
- Modify: `legislation-tracker-backend/apps/ingestion/tests/test_tasks.py`
- Modify: `legislation-tracker-backend/apps/legislation/tests/test_contract_comparison.py`
- Modify: `legislation-tracker-backend/apps/legislation/tests/test_search_index.py`
- Modify: `legislation-tracker-backend/apps/legislation/tests/test_backfill_contracts_command.py`

**Interfaces:**
- Produces: `GenerationReason = Literal["ingestion", "schema_backfill"]`
- Produces: `enqueue_document_contract(document, *, reextract_source=False, generation_reason="ingestion")`
- Produces: `enqueue_topic_update(*, contract=None, bill=None, source_updated_at=None, generation_reason="ingestion")`
- Produces: `semantic_contract_items(contract_json) -> dict[str, tuple[SemanticItem, ...]]`
- Produces: `project_reader_contract_text(contract_json) -> str`
- Preserves: durable deduplication by content, active extractor version, re-extraction version, and generation reason

- [ ] **Step 1: Write a failing activity-silent backfill test**

Create an active document with a 2.0 contract, enable 2.1, enqueue `generation_reason="schema_backfill"`, and assert latest contract changes while activity does not:

```python
assert bill.latest_contract.schema_version == "2.1-legal-nlp"
assert not ChangeLog.objects.filter(
    bill=bill,
    change_type__in=("contract_update", "topic_update"),
).exists()
assert refreshed_bill.last_activity_sequence == original_activity_sequence
```

Also assert topics are updated, similarity/search work is enqueued, the bill activity timestamp is unchanged, unread state does not advance, and the 2.0 contract remains in history.

- [ ] **Step 2: Carry generation reason through durable work**

Change the enqueue signature exactly once:

```python
def enqueue_document_contract(
    document,
    *,
    reextract_source: bool = False,
    generation_reason: GenerationReason = "ingestion",
):
    extractor_version = active_extractor_version()
```

Include `extractor_version`, source fingerprint, re-extraction version, and generation reason in the contract-work dedupe key. Store `generation_reason` in `payload_json`; pass it through `_process_durable_work` to `_generate_contract_impl`, then into `enqueue_topic_update` and `_update_topics_impl`. Include the reason in topic-work deduplication as well so a silent schema-backfill job cannot absorb a real ingestion activity event.

- [ ] **Step 3: Suppress schema-only activity without suppressing persistence**

Persist the new contract and evidence atomically and update `Bill.latest_contract`, topics, similarity, and search. Suppress both contract and topic `record_bill_change` calls for `generation_reason == "schema_backfill"`. Add a defensive assertion that schema backfill operates on the same `BillDocument`; a new document version always uses ingestion semantics. On the ingestion path, record a contract update only when the active document changed or `semantic_contract_items` reports a substantive change, never for schema/hash drift alone.

- [ ] **Step 4: Write failing offset-shift and mixed-schema comparison tests**

Test:

1. Prepending an unrelated section shifts every offset but yields no semantic changes for the original provisions.
2. Reordering unrelated sections does not mutate matched claims.
3. Changing one amount under the same purpose/action reports one `changed` item.
4. Equivalent 2.0 and 2.1 normalized claims produce no legislative change.
5. New/removed provisions remain added/removed.
6. Two unrelated claims in one structural/category bucket remain remove/add rather than a fabricated mutation.

- [ ] **Step 5: Implement semantic comparison adapters**

Never add `("id",)` to `CONTRACT_ITEM_IDENTITIES`. Adapt both schemas into a common shape that excludes source IDs, evidence paths, reader projections, extraction metadata, and display-only artifacts.

Bucket items by structural label path, category, rule family, and stable anchors. Consume exact semantic matches first. For remaining items within one bucket whose stable anchors agree, use normalized `SequenceMatcher` only for diff correspondence when its ratio is at least a named conservative constant such as `MIN_DIFF_CORRESPONDENCE_RATIO = 0.72`; break equal scores by source order. Treat below-threshold items as additions/removals, and never feed this matcher back into extraction or merging. Lock the threshold with positive amount-change and negative unrelated-replacement fixtures rather than tuning it against the test at runtime.

```python
@dataclass(frozen=True)
class SemanticItem:
    category: str
    structural_path: tuple[str, ...]
    anchor: tuple[str, ...]
    mutable_fields: dict[str, object]
    source_order: int
```

- [ ] **Step 6: Write failing curated-search tests**

Assert explicit purpose, reader display text, and financial purpose are indexed once while the count-only `coverage_note`, `source_id`, `evidence_paths`, `schema_version`, and duplicate normalized display text are absent.

- [ ] **Step 7: Replace generic contract flattening with a curated projection**

`project_reader_contract_text` emits only the explicit statutory purpose, line-item text, financial action/purpose/fiscal wording, timelines, and definitions. It excludes the count-only `coverage_note`. Official summary, bill metadata, and full-document sources remain separate existing search sources with their existing weights.

- [ ] **Step 8: Make backfill preview explicit and safe**

Preview reports the fixed intended `target_schema=V21_SCHEMA_VERSION` and `target_extractor=V21_EXTRACTOR_VERSION` rather than the currently active writer, plus generation reason, selected document count, ID range, active/inactive counts, and sessions. Execution calls:

```python
enqueue_document_contract(
    document,
    reextract_source=True,
    generation_reason="schema_backfill",
)
```

Require a narrowing selector and retain bounded `--limit` batches. Preview is allowed while the writer is disabled so operators can inspect the intended 2.1 scope, but it must clearly report `writer_enabled=false`. Refuse `--execute` before creating durable work unless `LEGAL_NLP_V21_WRITE_ENABLED=True`; this prevents a command advertised as a 2.1 backfill from silently enqueueing 2.0 extraction.

- [ ] **Step 9: Run persistence/comparison/search/backfill tests**

```bash
rtk run "cd legislation-tracker-backend && .venv/bin/pytest apps/legislation/tests/test_tasks.py apps/ingestion/tests/test_tasks.py apps/legislation/tests/test_contract_comparison.py apps/legislation/tests/test_search_index.py apps/legislation/tests/test_backfill_contracts_command.py -q"
```

Expected: PASS with no schema-backfill contract/topic activity, no offset-shift churn, and no internal search tokens.

- [ ] **Step 10: Commit semantic persistence integration**

```bash
rtk git add legislation-tracker-backend/apps/legislation/tasks.py legislation-tracker-backend/apps/ingestion/tasks.py legislation-tracker-backend/apps/legislation/comparison.py legislation-tracker-backend/apps/legislation/search_index.py legislation-tracker-backend/apps/legislation/management/commands/backfill_contracts.py legislation-tracker-backend/apps/legislation/tests legislation-tracker-backend/apps/ingestion/tests
rtk git commit -m "feat(contract): backfill reader contracts without activity churn"
```

### Task 5: Add Bounded Reader, Financial, Timeline, Definition, and Evidence APIs

**Files:**
- Create: `legislation-tracker-backend/apps/legislation/reader_api.py`
- Modify: `legislation-tracker-backend/apps/legislation/serializers.py`
- Modify: `legislation-tracker-backend/apps/legislation/views.py`
- Modify: `legislation-tracker-backend/apps/legislation/tests/test_public_api.py`
- Create: `legislation-tracker-backend/apps/legislation/tests/test_reader_api.py`

**Interfaces:**
- Produces: `BillContractSummarySerializer`
- Produces: explicit `ReaderLineItemPublicSerializer`, `FinancialItemPublicSerializer`, `TimelineItemPublicSerializer`, `DefinitionItemPublicSerializer`, and `EvidenceSpanPublicSerializer`
- Produces: `ReaderItemsQuerySerializer`, `FinancialItemsQuerySerializer`, `TimelineItemsQuerySerializer`, `DefinitionItemsQuerySerializer`, and `EvidenceQuerySerializer`
- Produces: `reader_items_page(contract, *, page, page_size)`
- Produces: `financial_items_page(contract, *, page, page_size, financial_action, fiscal_year, line_item_id, section_id)`
- Produces: `timeline_items_page(contract, *, page, page_size, line_item_id, section_id)`
- Produces: `definition_items_page(contract, *, page, page_size, line_item_id, unlinked)`
- Produces: `contract_evidence_page(contract, *, line_item_id=None, financial_item_id=None, definition_item_id=None, page, page_size)`
- Produces: `official_summary_projection(bill, *, full: bool)`
- Adds: `GET /api/contracts/{id}/reader-items/`, `/financial-items/`, `/timeline-items/`, `/definition-items/`, and `/evidence/`
- Adds: `GET /api/bills/{id}/official-summary/`

- [ ] **Step 1: Write failing strict-query and pagination tests**

Cover page sizes 1 and 100, reject 101, reject unknown parameters, filter financial/timeline/definition items by validated IDs or unlinked status, reject conflicting scope filters, require exactly one supported evidence item ID, reject dangling IDs, paginate evidence chunks, preserve source order, and return the complete official summary only from its dedicated action.

```python
response = api_client.get(
    f"/api/contracts/{contract.id}/reader-items/",
    {"page": 2, "page_size": 25},
)

assert response.status_code == 200
assert response.data["count"] == 101
assert len(response.data["results"]) == 25
assert response.data["results"][0]["id"] == expected_ids[25]
```

- [ ] **Step 2: Run the API tests and verify missing actions**

```bash
rtk run "cd legislation-tracker-backend && .venv/bin/pytest apps/legislation/tests/test_reader_api.py apps/legislation/tests/test_public_api.py -q"
```

Expected: FAIL with action routes not found.

- [ ] **Step 3: Implement compact contract summaries**

`BillContractSummarySerializer` returns only:

```python
fields = [
    "id", "schema_version", "contract_hash", "computed_at", "document",
    "document_version_label", "coverage_note", "orientation", "reader_stats",
]
```

Declare `coverage_note`, `orientation`, and `reader_stats` as read-only method fields derived from the validated 2.1 `contract_json`; they are not model columns. For 2.1, `coverage_note` is explicitly extraction coverage and must not be exposed as `plain_summary` or rendered under “What this bill does.” Preserve the existing 2.0 `plain_summary` only through the legacy/full compatibility serializer.

Add `contract_view=summary|full` to a strict bill-detail query serializer. Keep `full` as the compatibility default during rollout; the new frontend explicitly requests `summary`. Add `view=summary|full` to contract history with the same compatibility rule. Do not prefetch evidence for summary requests.

For `contract_view=summary`, return `summary_preview` as at most 1,200 characters of the first non-title content paragraph, cut at the last word boundary; return `summary_has_more` and the four provenance fields, but omit the complete stored `summary`. Preserve the existing full `summary` field for compatibility when `contract_view=full`. Implement `official-summary` on `BillViewSet` to return the complete stored summary and provenance only after explicit expansion.

- [ ] **Step 4: Implement page slicing and server-side financial filters**

Full JSON Schema, evidence, and reference validation occurs before contract persistence. At read time, require the stored `2.1-legal-nlp` schema marker and non-empty persisted contract hash, then validate each projected page through explicit public serializers; do not recompute the full hash or traverse the entire contract merely to return one reader page. Return standard count/next/previous/results fields. A legacy/2.0 contract returns HTTP 409 with code `reader_contract_unavailable`, allowing the frontend to use its existing renderer.

The reader-page response omits internal `evidence_paths` and complete reference arrays. Each line item includes exact association counts, a linked-definition count, and at most three compact financial/timeline previews in source order. Its envelope includes one `section_supplements` entry per section present on that page, with section-level financial/timeline counts. Add filtered paginated financial/timeline/definition actions for “Show all” and the global unlinked “Key terms” disclosure. Do not rank previews; they are the first three in source order.

- [ ] **Step 5: Implement evidence-on-demand by immutable item ID**

Resolve the line, financial, or definition item from contract JSON, collect its evidence paths, query only matching `EvidenceSpan` rows for that contract, deduplicate `(start_char, end_char, quoted_text)`, order by start/end, and paginate with the same `page_size <= 100` boundary. Never accept a raw client-supplied field path.

- [ ] **Step 6: Add bounded-response assertions**

For a 101-item contract, assert bill detail with `contract_view=summary` contains no complete CRS `summary`, `line_items`, `financial_items`, or `evidence_spans`; `summary_preview` never exceeds 1,200 characters; a 25-item page contains exactly 25 items; no association preview exceeds three; filtered financial/timeline/definition pagination exposes all referenced items; and each evidence page contains at most the requested size and only one requested item’s evidence.

- [ ] **Step 7: Run and commit reader APIs**

```bash
rtk run "cd legislation-tracker-backend && .venv/bin/pytest apps/legislation/tests/test_reader_api.py apps/legislation/tests/test_public_api.py -q"
rtk git add legislation-tracker-backend/apps/legislation/reader_api.py legislation-tracker-backend/apps/legislation/serializers.py legislation-tracker-backend/apps/legislation/views.py legislation-tracker-backend/apps/legislation/tests
rtk git commit -m "feat(api): paginate reader briefs and evidence"
```

Expected: PASS.

### Task 6: Add Runtime-Safe Frontend Reader Clients

**Files:**
- Modify: `legislation-tracker-client/lib/contracts.ts`
- Modify: `legislation-tracker-client/lib/api.ts`
- Modify: `legislation-tracker-client/tests/contracts.test.ts`
- Modify: `legislation-tracker-client/tests/api-ingestion.test.ts`

**Interfaces:**
- Produces: `LegalNlpV21ContractSummary`, public reader/financial/timeline/definition item types, compact association-preview types, `LegalNlpReaderStats`, and paginated response types
- Produces: `isLegalNlpV21ContractSummary(value: unknown)` and strict page-item guards
- Produces: `getBill(id, { contractView: "summary" })`
- Produces: `getContracts(billId, { view: "summary" })`, `getReaderItems`, `getFinancialItems`, `getTimelineItems`, `getDefinitionItems`, `getContractEvidence`, and `getOfficialSummary`
- Preserves: 2.0 and legacy contract guards

- [ ] **Step 1: Write failing runtime-guard tests**

Test valid summary/page/evidence payloads plus duplicate IDs, dangling references, malformed paths, unknown financial actions, invalid directions, invalid page metadata, and a 2.0 fallback.

```typescript
test("rejects a financial item with an unknown action", () => {
  const item = validFinancialItem();
  item.financial_action = "spending";
  assert.equal(isLegalNlpFinancialItem(item), false);
});
```

- [ ] **Step 2: Run exact Node contract tests and verify missing exports**

```bash
rtk run "cd legislation-tracker-client && node --disable-warning=ExperimentalWarning --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --experimental-strip-types --test tests/contracts.test.ts"
```

Expected: FAIL because 2.1 summary/page types are absent.

- [ ] **Step 3: Add exact TypeScript contracts**

```typescript
export type FinancialAction =
  | "appropriation" | "authorization" | "allocation" | "transfer"
  | "rescission" | "reduction" | "cancellation" | "set_aside"
  | "limitation" | "other_explicit";

export interface LegalNlpLineItem {
  id: string;
  source_id: string;
  section_id: string;
  section_path: LegalNlpSectionPathItem[];
  kind: "requirement" | "prohibition" | "permission" | "amendment" | "applicability" | "financial" | "timeline";
  display_text: string;
  actor: string | null;
  action: string | null;
  effect: string | null;
  exact_financial_count: number;
  exact_financial_preview: LegalNlpFinancialPreview[];
  timeline_count: number;
  timeline_preview: LegalNlpTimelinePreview[];
  definition_count: number;
}
```

Add a guarded `orientation` type with nullable, mutually consistent `purpose_clause`/`purpose_line_item_id`. Add `summary_preview`, `summary_has_more`, `summary_version_code`, and `summary_last_updated_at` to compact `BillDetail`, plus a guarded full official-summary response type.

- [ ] **Step 4: Implement strict clients and guards**

Use `URLSearchParams` for all page/filter values, including `view=summary` for contract history and contract-local association filters. Build the API URL through existing base helpers. Reject malformed responses before they reach React. Abort requests with the page’s existing request fence/abort pattern.

- [ ] **Step 5: Run API tests and type checking**

```bash
rtk run "cd legislation-tracker-client && pnpm run test:api && pnpm typecheck"
```

Expected: PASS.

- [ ] **Step 6: Commit frontend reader clients**

```bash
rtk git add legislation-tracker-client/lib/contracts.ts legislation-tracker-client/lib/api.ts legislation-tracker-client/tests/contracts.test.ts legislation-tracker-client/tests/api-ingestion.test.ts
rtk git commit -m "feat(client): add bounded bill brief clients"
```

### Task 7: Build the Reader-First Bill Brief and Money Ledger

**Files:**
- Create: `legislation-tracker-client/app/bills/[id]/source-evidence.tsx`
- Create: `legislation-tracker-client/app/bills/[id]/financial-ledger.tsx`
- Create: `legislation-tracker-client/app/bills/[id]/bill-brief.tsx`
- Modify: `legislation-tracker-client/app/bills/[id]/contract-section.tsx`
- Modify: `legislation-tracker-client/app/bills/[id]/page.tsx`
- Create: `legislation-tracker-client/tests/components/source-evidence.test.tsx`
- Create: `legislation-tracker-client/tests/components/financial-ledger.test.tsx`
- Create: `legislation-tracker-client/tests/components/bill-brief.test.tsx`
- Modify: `legislation-tracker-client/tests/components/contract-section.test.tsx`
- Modify: `legislation-tracker-client/tests/components/bill-detail-page.test.tsx`

**Interfaces:**
- Produces: `<BillBrief bill contractSummary />`
- Produces: `<FinancialLedger contractId totalCount />`
- Produces: `<SourceEvidence contractId lineItemId financialItemId definitionItemId textUrl downloadUrl />`
- Consumes: bounded API clients from Task 6

- [ ] **Step 1: Write failing CRS and no-CRS orientation tests**

Assert:

- CRS attribution, action date, Congress.gov link, and opening non-title paragraph;
- the complete summary is absent from initial bill detail and is requested only after “Read full official summary”;
- no-CRS copy explicitly says no official summary exists;
- a metadata fallback is labeled “Congress.gov source description,” never CRS analysis;
- official title, explicit purpose when present, policy areas, and counts orient the reader;
- “Read purpose text” uses `purpose_line_item_id` to fetch exact evidence on demand;
- a count statement is never labeled as the bill’s summary.

- [ ] **Step 2: Write failing paginated line-item tests**

Mock 61 reader items across three section paths. Assert the first 25 load, “Show 25 more” fetches page 2 rather than revealing preloaded DOM, page 3 eventually exposes all 61, source order is preserved, and a later-page failure leaves earlier items visible with retry.

- [ ] **Step 3: Write failing financial-ledger tests**

Use appropriation, authorization, transfer, rescission, reduction, set-aside, and limitation items. Assert distinct labels/directions, server-requested action/year/line/section filters, full/filtered counts, no computed total, three-item source-order previews with an exact “Show all N” count, exact line-level links only when supplied, and section-level money displayed once.

- [ ] **Step 4: Write failing lazy-evidence tests**

Assert no evidence request occurs during initial render. Click “Read bill text,” assert one evidence-page request, exact chunk order, “Load more source text” for later chunks, reconstruction after all pages, retry behavior, and full text/download links. Closing and reopening may use an in-memory result for that immutable contract/item pair.

Also test linked definitions by line item and the collapsed, paginated “Key terms” disclosure for unlinked definitions. Each definition must retain its term, plain definition, structural path, and source-text action.

- [ ] **Step 5: Run focused component tests and verify missing components**

```bash
rtk run "cd legislation-tracker-client && pnpm vitest run tests/components/source-evidence.test.tsx tests/components/financial-ledger.test.tsx tests/components/bill-brief.test.tsx tests/components/contract-section.test.tsx tests/components/bill-detail-page.test.tsx"
```

Expected: FAIL because the new components and request behavior do not exist.

- [ ] **Step 6: Implement summary/orientation and reader counts**

Render “What this bill does,” source attribution, revision date, the honest no-CRS orientation, and “Bill at a glance.” Use `summary_preview` initially. Fetch and render the complete summary with `whitespace-pre-line` only after expansion. Detect and skip a duplicate title paragraph using exact normalized equality with `bill.title`, not a generic “first paragraph” assumption.

- [ ] **Step 7: Implement source-ordered paginated reader groups**

Fetch `reader-items` page 1 on contract change. Append only when the returned next page matches the active contract/request ID. Group consecutive items by serialized structural path without reordering. Display actor/action/effect when available, source-ordered exact money/deadline previews, exact counts, and “Show all” controls backed by filtered pagination. Display each section-level money/deadline count once and expose its complete filtered list. Keep standalone timeline items visible. Show linked definition counts on their line items and load unlinked definitions only when the reader opens the paginated “Key terms” disclosure.

- [ ] **Step 8: Implement the complete financial ledger**

Use API pagination and server-side filters. Labels:

```typescript
const actionLabels: Record<FinancialAction, string> = {
  appropriation: "Appropriation",
  authorization: "Authorization",
  allocation: "Allocation",
  transfer: "Transfer",
  rescission: "Rescission",
  reduction: "Reduction",
  cancellation: "Cancellation",
  set_aside: "Set-aside",
  limitation: "Limitation",
  other_explicit: "Other explicit financial provision",
};
```

Title the section “Money in this bill.” Add the supported-coverage disclosure and explicitly state that it is not a CBO cost estimate.

- [ ] **Step 9: Implement evidence-on-open**

Use button/disclosure state and render spans only after a successful evidence request. Preserve exact whitespace with `whitespace-pre-wrap`. Do not normalize quotations. Append later evidence pages without reordering or duplication and fence them by the active immutable contract/item ID. Resolve document URLs through `getApiBase()`.

- [ ] **Step 10: Preserve historical rendering and isolate errors**

2.1 summary uses the new brief; 2.0 and legacy continue through existing renderers. Summary, reader items, financial items, timelines, definitions, evidence, votes, changes, and document errors must not hide one another.

- [ ] **Step 11: Run and commit reader UI**

```bash
rtk run "cd legislation-tracker-client && pnpm vitest run tests/components/source-evidence.test.tsx tests/components/financial-ledger.test.tsx tests/components/bill-brief.test.tsx tests/components/contract-section.test.tsx tests/components/bill-detail-page.test.tsx && pnpm typecheck"
rtk git add legislation-tracker-client/app/bills/\[id\] legislation-tracker-client/tests/components legislation-tracker-client/lib/contracts.ts legislation-tracker-client/lib/api.ts
rtk git commit -m "feat(client): present reader-first bill briefs"
```

Expected: PASS.

### Task 8: Make Complete Voting Records Digestible

**Files:**
- Create: `legislation-tracker-client/app/bills/[id]/voting-record.tsx`
- Modify: `legislation-tracker-client/app/bills/[id]/page.tsx`
- Modify: `legislation-tracker-client/lib/api.ts`
- Create: `legislation-tracker-client/tests/components/voting-record.test.tsx`
- Modify: `legislation-tracker-client/tests/components/bill-detail-page.test.tsx`

**Interfaces:**
- Produces: `<VotingRecord votes selectedVote loadingVoteId error onSelect page hasNext onPrevious onNext />`
- Consumes: existing `getVotes(billId)` and `getVote(voteId)`
- Preserves: request fencing, retry, pagination, and all returned member records

- [ ] **Step 1: Write failing grouped-record tests**

Cover newest-first votes, totals, source links, pagination, every returned member, position groups, member search, party/state filters, deterministic state/district/name ordering, totals-versus-record discrepancy warning, empty state, retry, and stale response suppression.

```tsx
await user.click(screen.getByRole("button", { name: "View voting record" }));
expect(screen.getByRole("heading", { name: "Yes — 2" })).toBeVisible();
expect(screen.getByRole("heading", { name: "Not voting — 1" })).toBeVisible();
await user.type(screen.getByRole("searchbox", { name: "Search members" }), "Garcia");
expect(screen.getByText("Representative Garcia")).toBeVisible();
```

- [ ] **Step 2: Run tests and verify missing component**

```bash
rtk run "cd legislation-tracker-client && pnpm vitest run tests/components/voting-record.test.tsx tests/components/bill-detail-page.test.tsx"
```

Expected: FAIL because the grouped component does not exist.

- [ ] **Step 3: Extract and improve vote presentation**

Keep network ownership in `page.tsx`. Group records by normalized position, filter locally within the selected roll call, sort by state/district/name, and show a non-blocking discrepancy message when persisted aggregate totals differ from returned member records. Do not discard or silently rewrite records.

- [ ] **Step 4: Move voting beneath the bill brief and preserve failure isolation**

Page order becomes metadata, topics, brief, money ledger, voting, optional LLM enhancement, what changed, history, and source documents. A vote failure leaves the brief, money, and documents usable.

- [ ] **Step 5: Run and commit voting UI**

```bash
rtk run "cd legislation-tracker-client && pnpm vitest run tests/components/voting-record.test.tsx tests/components/bill-detail-page.test.tsx && pnpm typecheck"
rtk git add legislation-tracker-client/app/bills/\[id\]/voting-record.tsx legislation-tracker-client/app/bills/\[id\]/page.tsx legislation-tracker-client/tests/components/voting-record.test.tsx legislation-tracker-client/tests/components/bill-detail-page.test.tsx
rtk git commit -m "feat(votes): group complete bill voting records"
```

Expected: PASS.

### Task 9: Add Real Omnibus, Capacity, API, and End-to-End Gates

**Files:**
- Create: `legislation-tracker-backend/apps/legislation/tests/fixtures/legal_nlp/reader_brief_hr1_excerpt.json`
- Create: `legislation-tracker-backend/apps/legislation/tests/fixtures/legal_nlp/reader_brief_financial_actions.json`
- Create: `legislation-tracker-backend/apps/legislation/tests/fixtures/legal_nlp/reader_brief_funding_101.json`
- Create: `legislation-tracker-backend/apps/legislation/tests/fixtures/legal_nlp/reader_brief_offset_shift.json`
- Modify: `legislation-tracker-backend/apps/legislation/tests/test_extraction_evaluation.py`
- Modify: `legislation-tracker-backend/scripts/seed-e2e-legislative-intelligence.py`
- Modify: `legislation-tracker-client/e2e/contract-detail.spec.ts`
- Modify: `legislation-tracker-client/e2e/representative-insights.spec.ts`

**Interfaces:**
- Produces: public-domain evaluation fixtures for the observed H.R. 1 failure and diverse financial actions
- Produces: a seeded 2.1 bill with paginated reader/financial/timeline/definition data, chunked evidence, and two votes
- Enforces: extraction accuracy, exact evidence, bounded API responses, and user-outcome E2E behavior

- [ ] **Step 1: Check in the observed H.R. 1 failure as a golden fixture**

Use a public-domain excerpt containing actual `<<NOTE...>>`, page/statute markers, congressional quotations, nested amendments, inherited clauses, and financial provisions. Store exact source reference/locator, expected controlled line items, expected financial actions, forbidden malformed display fragments, and exact evidence offsets.

Assertions include:

```python
assert "<<NOTE:" not in rendered_reader_text
assert "[[Page" not in rendered_reader_text
assert " is required to be" not in rendered_reader_text
assert all(source[start:end] == quote for start, end, quote in evidence)
```

- [ ] **Step 2: Add diverse financial-action and multi-amount fixtures**

Hand-author expected claims for appropriation, authorization, allocation, transfer, rescission, reduction, cancellation, set-aside, limitation, such-sums, percentage, ceiling, and two amounts in one sentence. Include explicit forbidden claims for incidental dollar references and quoted external law.

- [ ] **Step 3: Add static capacity and offset-shift fixtures**

The 101-item fixture contains 101 distinct source provisions and hand-authored expected IDs/actions/amounts/offsets. The offset-shift fixture has before/after documents where a new opening section shifts all later offsets but leaves their semantics unchanged.

- [ ] **Step 4: Extend evaluation gates by category and financial action**

Retain existing overall precision/recall requirements and require at least three expected examples for every supported financial action before release. Assert exact recognized counts, line/financial source order, no forbidden display artifacts, all reference resolution, exact evidence reconstruction, and no schema fallback for the omnibus excerpt.

- [ ] **Step 5: Seed a complete bounded E2E scenario**

Seed:

- a CRS summary with title paragraph and revision provenance;
- 61 reader items and 101 financial items;
- section-level and exact financial associations;
- a timeline-only item;
- linked and unlinked definitions;
- a long evidence span split into three chunks;
- active document text/download links;
- two roll calls and member positions across every group.

- [ ] **Step 6: Rewrite bill-detail E2E around user outcomes**

Verify an unauthenticated reader can:

1. Read the attributed CRS preview, verify the complete summary was not in initial bill detail, and expand the complete official summary on demand.
2. Understand the no-CRS fallback on a second seeded bill.
3. Load all 61 line items across pages in source order.
4. Filter and load all 101 financial provisions without a computed total.
5. Distinguish appropriation, authorization, transfer, and rescission.
6. Expand and paginate exact raw text, including reconstructed long evidence.
7. Open linked definitions and paginate the unlinked “Key terms” disclosure.
8. Search/filter a complete voting record.
9. Open full text and source download links.

- [ ] **Step 7: Add API response-boundary assertions**

At the test client boundary, serialize responses and assert:

- compact bill detail contains no complete CRS summary, evidence quotations, or substantive arrays;
- reader/financial/timeline/definition pages never exceed requested `page_size` and association previews never exceed three source-ordered items;
- every evidence page stays within `page_size` and contains only the selected item’s paths;
- query counts remain bounded with no evidence prefetch for compact detail.

- [ ] **Step 8: Run evaluation and E2E tests**

```bash
rtk run "cd legislation-tracker-backend && .venv/bin/pytest apps/legislation/tests/test_extraction_evaluation.py apps/legislation/tests/test_reader_api.py -q"
rtk run "cd legislation-tracker-client && pnpm test:e2e -- e2e/contract-detail.spec.ts e2e/representative-insights.spec.ts"
```

Expected: PASS.

- [ ] **Step 9: Commit quality gates**

```bash
rtk git add legislation-tracker-backend/apps/legislation/tests/fixtures/legal_nlp legislation-tracker-backend/apps/legislation/tests/test_extraction_evaluation.py legislation-tracker-backend/apps/legislation/tests/test_reader_api.py legislation-tracker-backend/scripts/seed-e2e-legislative-intelligence.py legislation-tracker-client/e2e
rtk git commit -m "test(brief): gate reader quality on real legislation"
```

### Task 10: Document Compatible Rollout and Run Full Verification

**Files:**
- Modify: `legislation-tracker-backend/apps/legislation/README.md`
- Modify: `legislation-tracker-backend/docs/PHASE_5_CONTRACT.md`
- Modify: `legislation-tracker-backend/docs/PRODUCTION_OPERATIONS.md`
- Modify: `legislation-tracker-client/README.md`
- Modify: `README.md`
- Modify: `.env.production.example`

**Interfaces:**
- Documents: financial-action coverage, honest limitations, compact APIs, evidence behavior, semantic comparisons, backfill activity suppression, and read-before-write rollout
- Consumes: all completed tasks

- [ ] **Step 1: Document the 2.1 contract and user-facing coverage**

Document source-local IDs, semantic comparison, section-level versus exact financial links, every financial action, no-total rule, long-evidence chunking, no-CRS orientation, silent contract/topic schema backfills, and legacy/2.0 compatibility. Replace primary-reader references to “key provisions” or category debug lists.

- [ ] **Step 2: Document the read-before-write rollout**

Exact sequence:

1. Deploy code with `LEGAL_NLP_V21_WRITE_ENABLED=False`.
2. Verify legacy, 2.0, and seeded 2.1 APIs/UI.
3. Set `LEGAL_NLP_V21_WRITE_ENABLED=True` for new work.
4. Preview 25 documents.
5. Execute 25-document batches and inspect durable failures, payload counts, and absence of user activity.
6. Disable new writes if necessary; persisted 2.1 readers remain supported.

- [ ] **Step 3: Document and test preview-first commands**

```bash
rtk run "cd legislation-tracker-backend && .venv/bin/python manage.py backfill_contracts --session 119 --limit 25"
rtk run "cd legislation-tracker-backend && .venv/bin/python manage.py backfill_contracts --session 119 --limit 25 --execute"
```

Preview must print `generation_reason=schema_backfill`, target schema/extractor, selected count, ID range, and active/inactive counts. `--execute` must fail before enqueueing anything when `LEGAL_NLP_V21_WRITE_ENABLED=False`; test that refusal explicitly. With the flag enabled, execution enqueues durable work and never extracts synchronously.

- [ ] **Step 4: Run backend configuration, formatting, migration, and full tests**

```bash
rtk run "cd legislation-tracker-backend && .venv/bin/python manage.py check"
rtk run "cd legislation-tracker-backend && .venv/bin/python manage.py makemigrations --check --dry-run"
rtk run "cd legislation-tracker-backend && .venv/bin/black --check ."
rtk run "cd legislation-tracker-backend && .venv/bin/ruff check ."
rtk run "cd legislation-tracker-backend && .venv/bin/pytest --create-db -q"
```

Expected: every command exits 0.

- [ ] **Step 5: Run frontend tests, type checking, lint, and production build**

```bash
rtk run "cd legislation-tracker-client && pnpm test"
rtk run "cd legislation-tracker-client && pnpm typecheck"
rtk run "cd legislation-tracker-client && pnpm lint"
rtk run "cd legislation-tracker-client && pnpm build --webpack"
```

Expected: every command exits 0.

- [ ] **Step 6: Run Playwright and extension regression tests**

```bash
rtk run "cd legislation-tracker-client && pnpm test:e2e"
rtk run "cd legislation-tracker-extension && node --test tests/*.test.js"
rtk run "cd legislation-tracker-extension && node --check content.js && node --check extension-utils.js && node --check popup.js"
```

Expected: every command exits 0.

- [ ] **Step 7: Perform a local rollout rehearsal**

With the writer disabled, verify 2.0 generation and seeded 2.1 reads. Enable the writer, ingest one fixture bill, verify 2.1 compact/detail and every bounded reader/financial/timeline/definition/evidence API, execute a one-document `schema_backfill`, and assert no `contract_update` or `topic_update` ChangeLog, activity-timestamp change, activity-sequence advance, or unread update. Disable the writer and verify the persisted 2.1 bill remains readable.

- [ ] **Step 8: Commit documentation and rollout controls**

```bash
rtk git add README.md legislation-tracker-backend/apps/legislation/README.md legislation-tracker-backend/docs/PHASE_5_CONTRACT.md legislation-tracker-backend/docs/PRODUCTION_OPERATIONS.md .env.production.example legislation-tracker-client/README.md
rtk git commit -m "docs(brief): document reader-first rollout"
```

---

## Acceptance Checklist

- [ ] An unauthenticated reader sees the latest attributed CRS revision when one exists.
- [ ] CRS corrections/republications cannot be lost or overwritten by a stale response.
- [ ] A missing CRS summary is stated honestly and still provides title, explicit purpose when found, policy areas, counts, and the complete recognized breakdown.
- [ ] Controlled text contains no known note/page/quotation artifacts from the observed H.R. 1 output.
- [ ] Raw evidence remains exact and evidence over 4,000 characters reconstructs without loss.
- [ ] The structural path preserves divisions, titles, subchapters, accounts, sections, and nested provisions.
- [ ] Offset-derived IDs are never used to match different bill versions.
- [ ] Prepending text before unchanged provisions creates no false comparison churn.
- [ ] Equivalent 2.0 and 2.1 contracts create no semantic bill change.
- [ ] A schema backfill creates no user-visible change, unread count, or recent activity.
- [ ] Multiple monetary clauses in one sentence produce multiple financial items.
- [ ] Appropriations, authorizations, allocations, transfers, rescissions, reductions, cancellations, set-asides, limitations, percentages, ceilings, and such-sums remain distinct.
- [ ] Every recognized financial provision remains accessible with no top-N cap and no naive total.
- [ ] Money attaches to a line item only with exact clause or explicit program/account evidence; otherwise it appears once at section level.
- [ ] Standalone deadlines/effective dates and linked/unlinked definitions remain reader-accessible.
- [ ] Compact bill detail embeds neither substantive arrays nor evidence quotations.
- [ ] Reader, financial, timeline, definition, and evidence pages are bounded; association previews are source ordered rather than ranked; evidence and full official summaries are requested only after user action.
- [ ] Search indexes reader text once and excludes internal IDs/evidence metadata.
- [ ] Every bill roll call and returned member position remains accessible, grouped, searchable, and deterministically ordered.
- [ ] Legacy and 2.0 contracts continue rendering and comparing.
- [ ] The 2.1 writer is disabled by default and can be turned off without making persisted 2.1 contracts unreadable.
- [ ] Full backend, frontend, E2E, production-build, and extension verification passes.
