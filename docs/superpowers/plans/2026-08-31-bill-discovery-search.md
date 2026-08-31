# Bill Discovery and Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add PostgreSQL full-text bill search with safe highlights, URL-backed filters, recent-activity sorting, and authenticated saved searches with new-result counts.

**Architecture:** Bill metadata, the latest contract, and active document text are projected into bounded `BillSearchChunk` rows and rebuilt through the persistent ingestion queue. A centralized change-recording service maintains bill activity timestamp plus a commit-serialized global sequence, and document persistence records `new_version` atomically before activity-based features launch. Saved searches store only a validated, normalized copy of public query parameters and acknowledge signed sequence watermarks so overlapping writers cannot be lost.

**Tech Stack:** Django 5, Django REST Framework, PostgreSQL full-text search, Celery, Next.js 16, React 19, TypeScript, Vitest/Testing Library, Playwright

**Spec:** `docs/superpowers/specs/2026-08-31-legislative-intelligence-design.md`

## Global Constraints

- Use `rtk` for every shell command.
- Use `apply_patch` for hand-authored file edits.
- Preserve the existing SQLite unit-test path, but treat PostgreSQL integration tests as authoritative for ranking, headlines, indexes, and query plans.
- Do not index credentials, user enhancements, inactive document versions, or superseded contracts.
- Do not return raw `BillSearchChunk.text` or server-authored HTML.
- Backfill commands preview by default and require `--execute` to mutate state.
- Keep the frontend URL as the authority for public search state.
- Treat PostgreSQL as the required release-gate database; SQLite tests are supplemental only.
- Use the backend virtual environment executables (`.venv/bin/python`, `.venv/bin/pytest`, and `.venv/bin/ruff`) in every backend verification command.

---

## Task 1: Centralize bill activity recording

**Files:**

- Modify: `legislation-tracker-backend/apps/legislation/models.py`
- Create: `legislation-tracker-backend/apps/legislation/migrations/0008_bill_activity_fields.py`
- Modify: `legislation-tracker-backend/apps/changelog/models.py`
- Create: `legislation-tracker-backend/apps/changelog/migrations/0004_bill_activity_clock.py`
- Create: `legislation-tracker-backend/apps/changelog/services.py`
- Modify: `legislation-tracker-backend/apps/ingestion/tasks.py`
- Modify: `legislation-tracker-backend/apps/ingestion/document_download.py`
- Modify: `legislation-tracker-backend/apps/legislation/tasks.py`
- Modify: every production file found by `rtk grep -R -n "ChangeLog.objects.create" legislation-tracker-backend/apps`
- Create: `legislation-tracker-backend/apps/changelog/tests/test_services.py`
- Modify: `legislation-tracker-backend/apps/ingestion/tests/test_tasks.py`
- Create: `legislation-tracker-backend/docker-compose.e2e-postgres.yml`

- [ ] Write failing service tests proving that one call requires a non-null payload, creates the expected change row, advances both activity fields, allocates globally increasing sequences, never moves activity backward, deduplicates a repeated deterministic `event_key` under locks, and rolls the event, sequence, and bill writes back together on failure.

- [ ] Add the nullable, indexed field:

```python
last_activity_at = models.DateTimeField(null=True, blank=True, db_index=True)
last_activity_sequence = models.BigIntegerField(null=True, blank=True, db_index=True)
```

Add a singleton `BillActivityClock` with primary key constrained to `1` and nonnegative `committed_sequence`. The service and saved-search snapshot path always acquire this row before any bill row; this lock order is global.

- [ ] Implement one entry point with an explicit signature:

```python
def record_bill_change(
    *,
    bill: Bill,
    change_type: str,
    new_value: dict,
    old_value: dict | None = None,
    event_key: str | None = None,
    document: BillDocument | None = None,
    contract: BillContract | None = None,
) -> ChangeLog:
    """Create or reconcile one canonical change and advance bill activity."""
```

The concrete implementation must reject `new_value is None`, enter `transaction.atomic()`, lock `BillActivityClock` and then `Bill` with `select_for_update()`, return the existing row without allocating when the same non-null `event_key` is found for that bill/type, increment the clock and create the change otherwise, and update the bill timestamp plus allocated sequence. Store the event key in the first-class `ChangeLog.event_key` column; the bill lock makes application-level dedupe race-safe even though the partitioned change table has no global unique key. The clock lock is held through commit so a saved-search snapshot cannot pass an uncommitted earlier writer.

- [ ] Keep HTTP requests, object uploads, parsing, and search-query validation outside the clock transaction. Add structured duration logging for clock-lock wait/hold time and a test that a failed event transaction does not consume a sequence.

- [ ] Replace every direct production `ChangeLog.objects.create` call with the service. Leave migrations and tests that deliberately construct fixtures alone.

- [ ] In changelog migration `0004`, create/seed the singleton clock at sequence 0. Make legislation migration `0008` depend on changelog `0004`, add both bill fields, then run a data migration that sets each bill's timestamp to its maximum existing change timestamp, assigns deterministic global sequences ordered by each bill's latest `(created_at, id)`, and updates the clock to the maximum assigned sequence. Bills without a change remain null in both fields; `last_action_at` and `updated_at` are never substituted. The reverse clears both bill fields; normal reverse dependency order then removes the clock model.

- [ ] Add a disposable `postgres:16-alpine` service (matching the repository compose stack) bound to `127.0.0.1:55432` with database `legislation_e2e`, health check, and a named test-data volume. All subsequent PostgreSQL commands in these three plans use this service; start it with `rtk docker compose -f legislation-tracker-backend/docker-compose.e2e-postgres.yml up -d` before the first PostgreSQL test.

- [ ] Add failing document-ingestion tests for: successful object upload followed by one atomic document-field/`new_version`/activity commit; database failure after object upload leaving no partial database state; retry of that uploaded object reconciling exactly one event; and an unchanged stored document repairing a historically missing event. Use event key `document:<document-id>:<content-sha256>`.

- [ ] Change document persistence to upload first, then enter one database transaction, lock `BillActivityClock`, the bill, and the document in that order, revalidate/save the stored-object key/URL, extracted text, and active/version fields, then call the re-entrant change service with `new_value={"document_id": document.pk, "version_code": document.version_code, "content_sha256": content_sha256}` and `event_key=f"document:{document.pk}:{content_sha256}"`. The unchanged/retry path executes the same event reconciliation before reporting a no-op. Queue search indexing with `transaction.on_commit` only after the transaction succeeds.

- [ ] Run focused tests and formatting:

```bash
rtk run "cd legislation-tracker-backend && .venv/bin/pytest apps/changelog/tests/test_services.py apps/ingestion/tests/test_tasks.py apps/legislation/tests/test_tasks.py -q"
rtk run "cd legislation-tracker-backend && .venv/bin/ruff check apps/changelog apps/ingestion apps/legislation"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-backend/apps/changelog legislation-tracker-backend/apps/legislation legislation-tracker-backend/apps/ingestion
rtk git commit -m "feat(discovery): centralize bill activity recording"
```

## Task 2: Add bounded search chunks and deterministic projection

**Files:**

- Modify: `legislation-tracker-backend/config/settings/base.py`
- Modify: `legislation-tracker-backend/apps/legislation/models.py`
- Create: `legislation-tracker-backend/apps/legislation/migrations/0009_billsearchchunk.py`
- Create: `legislation-tracker-backend/apps/legislation/search_index.py`
- Create: `legislation-tracker-backend/apps/legislation/tests/test_search_index.py`

- [ ] Write failing tests for metadata normalization, nested-contract flattening, paragraph-aware 20,000-character chunking, oversized-paragraph splitting, deterministic ordinals/hashes, active-document selection, and no-op rebuild when all hashes match.

- [ ] Add `django.contrib.postgres` to `INSTALLED_APPS` and define `BillSearchChunk` with `kind` choices `metadata`, `contract`, and `document`; nullable document/contract foreign keys; `source_key`; `ordinal`; `text`; `SearchVectorField`; `source_hash`; timestamps; a unique constraint on `(bill, kind, source_key, ordinal)`; and a GIN index on `search_vector`.

- [ ] Implement the exact interfaces `project_bill_search_sources(bill: Bill) -> list[SearchSource]`, `chunk_search_text(text: str, *, max_chars: int = 20_000) -> list[str]`, and `rebuild_bill_search_index(*, bill_id: int) -> SearchIndexResult`.

`SearchSource` must identify its kind, stable source key, optional source row IDs, weight, text, and source hash. Metadata text must include bill number, title, summary, status, sponsor name/Bioguide ID, and topic names. Contract text must include field labels. Document projection must select exactly the active document. Rebuild must prepare all rows before atomically replacing the bill's current rows.

- [ ] Populate `search_vector` in PostgreSQL with weights A/B/C for metadata/contract/document. Under SQLite, retain rows and hashes but leave the database vector null so unit tests remain deterministic.

- [ ] Run migration checks and focused tests:

```bash
rtk run "cd legislation-tracker-backend && .venv/bin/python manage.py makemigrations --check --dry-run"
rtk run "cd legislation-tracker-backend && .venv/bin/pytest apps/legislation/tests/test_search_index.py -q"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-backend/config/settings/base.py legislation-tracker-backend/apps/legislation
rtk git commit -m "feat(discovery): add bounded bill search index"
```

## Task 3: Make search indexing durable and backfillable

**Files:**

- Modify: `legislation-tracker-backend/apps/ingestion/tasks.py`
- Modify: canonical bill/document/contract write services that enqueue existing work
- Create: `legislation-tracker-backend/apps/legislation/management/commands/backfill_bill_search.py`
- Create: `legislation-tracker-backend/apps/ingestion/tests/test_search_index_work.py`
- Create: `legislation-tracker-backend/apps/legislation/tests/test_backfill_bill_search_command.py`

- [ ] Write failing tests proving `search_index` work uses dedupe key `bill:<id>`, duplicate enqueue coalesces, stale work does not replace a fresher index, transient failures retry, terminal failures enter existing dead-letter controls, and replay is idempotent.

- [ ] Add a `WORK_KIND_SEARCH_INDEX = "search_index"` constant and dispatch it to `rebuild_bill_search_index`. `IngestionWorkItem.kind` is intentionally an unconstrained string, so this does not require a schema migration. Enqueue from `transaction.on_commit` after bill metadata, active document, latest contract, or topic projection changes.

- [ ] Carry the canonical row's update/computation timestamp as `source_updated_at`. The handler must lock or re-read current state and report stale work as a successful no-op.

- [ ] Implement `backfill_bill_search` with required narrowing by `--congress`, optional `--limit`, preview output containing candidate and already-current counts, and writes only with `--execute`. Execution enqueues durable work; it does not rebuild inline.

- [ ] Run:

```bash
rtk run "cd legislation-tracker-backend && .venv/bin/pytest apps/ingestion/tests/test_search_index_work.py apps/legislation/tests/test_backfill_bill_search_command.py -q"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-backend/apps/ingestion legislation-tracker-backend/apps/legislation/management
rtk git commit -m "feat(discovery): queue and backfill search indexing"
```

## Task 4: Add the PostgreSQL search service and bill-list contract

**Files:**

- Create: `legislation-tracker-backend/apps/legislation/search.py`
- Create: `legislation-tracker-backend/apps/legislation/throttles.py`
- Modify: `legislation-tracker-backend/apps/legislation/serializers.py`
- Modify: `legislation-tracker-backend/apps/legislation/views.py`
- Modify: `legislation-tracker-backend/config/settings/base.py`
- Modify: `legislation-tracker-backend/apps/legislation/tests/test_public_api.py`
- Create: `legislation-tracker-backend/apps/legislation/tests/test_search_postgres.py`

- [ ] Add failing query-serializer tests for `q`, sort choices, defaults, `sort=relevance` without `q`, query byte/token limits, unknown parameters, combined existing filters, and stable pagination. Add throttle tests that prove separate authenticated/anonymous buckets return 429 before search SQL and cannot be bypassed with malformed parameters.

- [ ] Add PostgreSQL-only integration fixtures where a term appears independently in metadata, a contract, and a document. Assert metadata ranks first, filters apply before pagination, recent activity is descending with a stable ID tie-breaker, and headlines contain only bounded marker-delimited text.

- [ ] Implement:

```python
@dataclass(frozen=True)
class BillSearchHit:
    bill_id: int
    rank: float
    highlights: tuple[SearchHighlight, ...]
```

Implement exact interface `search_bills(*, queryset: QuerySet[Bill], query: BillSearchQuery) -> BillSearchPage`. Use `SearchQuery(query.q, search_type="websearch", config="english")`, weighted `SearchRank`, and `SearchHeadline`. Configure non-HTML sentinel values for `StartSel`/`StopSel`, strip those sentinel code points from indexed source text, and parse the returned headline into plain matched/unmatched segments. Select no more than three best chunks per bill. Enforce 512 UTF-8 bytes, 32 parsed tokens, and page-size limits before evaluating SQL. Attach `BillSearchThrottle` with scopes `bill_search_anon` and `bill_search_user`, defaulting to `30/min` and `120/min`; allow environment overrides `BILL_SEARCH_ANON_RATE` and `BILL_SEARCH_USER_RATE` rather than sharing the general API scope.

- [ ] Implement SQLite metadata-only `icontains` fallback with no numeric rank guarantee. Keep response shape identical and mark highlights by slicing plain text, not HTML.

- [ ] Extend `BillListQuerySerializer` with `q` and `sort`. Extend list results with nullable `search_rank` and:

```json
"highlights": [{"kind": "document", "segments": [{"text": "rural hospitals", "matched": true}]}]
```

Parse database headline markers into plain structured segments on the server and escape/drop malformed marker sequences.

- [ ] Run focused and PostgreSQL tests using the repository's configured database environment:

```bash
rtk run "cd legislation-tracker-backend && .venv/bin/pytest apps/legislation/tests/test_public_api.py -q"
rtk docker compose -f legislation-tracker-backend/docker-compose.e2e-postgres.yml up -d
rtk run "cd legislation-tracker-backend && DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/legislation_e2e .venv/bin/pytest apps/legislation/tests/test_search_postgres.py -q"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-backend/apps/legislation
rtk git commit -m "feat(discovery): expose ranked bill search"
```

## Task 5: Add private saved-search persistence and APIs

**Files:**

- Modify: `legislation-tracker-backend/apps/accounts/models.py`
- Create: `legislation-tracker-backend/apps/accounts/migrations/0007_savedbillsearch.py`
- Modify: `legislation-tracker-backend/apps/accounts/serializers.py`
- Modify: `legislation-tracker-backend/apps/accounts/views.py`
- Modify: `legislation-tracker-backend/config/urls.py`
- Create: `legislation-tracker-backend/apps/accounts/saved_searches.py`
- Create: `legislation-tracker-backend/apps/accounts/tests/test_saved_search_api.py`

- [ ] Write failing tests for authentication, owner isolation (including results), a 25-search limit, per-user unique names, canonical normalization/hash generation, rejection of unknown query keys, duplicate normalized queries, update/delete ownership, query-update watermark reset, signed watermark validation, owner/search/query-hash binding, and monotonic opening.

- [ ] Add `SavedBillSearch` with `user`, `name`, `query_json`, `normalized_hash`, nullable `last_opened_at`, nullable `last_opened_activity_sequence`, and timestamps. Add unique `(user, name)` and `(user, normalized_hash)` constraints plus an index on `(user, updated_at)`. Lock the user row while enforcing the 25-search cap so concurrent creates cannot exceed it.

- [ ] Extract the public bill-query normalization from Task 4 into a callable shared by the bill endpoint and saved-search serializer. Persist only normalized non-default keys; never persist pagination.

- [ ] Implement `count_saved_search_new_results(searches)`. On PostgreSQL, combine parameterized per-search count querysets into one `UNION ALL` database round trip; never interpolate stored JSON into SQL. The SQLite test fallback may loop over the capped set. Count matching bills with `last_activity_sequence > last_opened_activity_sequence`; for a null sequence, count matching bills with non-null activity sequence. Assert one PostgreSQL count round trip for the 25-item list endpoint. Do not use display-only activity fallbacks.

- [ ] Implement `issue_saved_search_watermark(*, user_id: int, search: SavedBillSearch, sequence: int, captured_at: datetime) -> str` and `verify_saved_search_watermark(*, value: str, user_id: int, search: SavedBillSearch) -> SavedSearchWatermark` with a dedicated Django signing salt and versioned payload containing user ID, saved-search ID, normalized query hash, global sequence, and database timestamp. In one short `transaction.atomic()` block, the saved-search result request locks `BillActivityClock`, reads `committed_sequence` and `statement_timestamp()`, executes the bounded bill query, and returns the signed value. An activity writer that began earlier either commits before this snapshot or remains ahead of it with a greater sequence.

- [ ] Add:

```text
GET/POST      /api/saved-searches/
GET/PATCH/DELETE /api/saved-searches/{id}/
GET           /api/saved-searches/{id}/results/?page=&page_size=
POST          /api/saved-searches/{id}/open/
```

Register a `SavedBillSearchViewSet` as `saved-searches` on the existing DRF router. `results` uses the authenticated bill-search throttle, executes the row's stored normalized query through the Task 4 search service, and accepts no overrides except bounded pagination. It fully evaluates the returned page while holding the activity-clock transaction and adds `result_watermark` to the normal bill-list envelope. `open` requires `{ "result_watermark": "<signed value>" }`, returns prior/new sequence and timestamp, and uses a conditional sequence update so an older concurrent request cannot move either field backward. It must never substitute request-arrival time. Add PostgreSQL transaction tests for activity committed after the result query and for an activity writer already open when snapshot acquisition starts; both must remain visible or be included in the acknowledged snapshot, never disappear.

- [ ] Run:

```bash
rtk run "cd legislation-tracker-backend && DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/legislation_e2e .venv/bin/pytest apps/accounts/tests/test_saved_search_api.py apps/legislation/tests/test_public_api.py -q"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-backend/apps/accounts legislation-tracker-backend/config/urls.py
rtk git commit -m "feat(discovery): add authenticated saved searches"
```

## Task 6: Introduce one frontend search-state contract

**Files:**

- Create: `legislation-tracker-client/lib/bill-search.ts`
- Modify: `legislation-tracker-client/lib/api.ts`
- Modify: `legislation-tracker-client/tests/bill-filter-params.test.ts`
- Create: `legislation-tracker-client/tests/api-search.test.ts`

- [ ] Write failing tests for parsing/serializing every supported key, removing defaults, preserving repeated navigation, resetting page on filter changes, rejecting unknown sort values, and converting structured highlights without HTML injection.

- [ ] Define `BillSearchParams`, `BillSearchResult`, `SearchHighlight`, and `SavedBillSearch` types. Implement pure `parseBillSearchParams`, `serializeBillSearchParams`, and `withBillSearchUpdate` functions.

- [ ] Extend `api.ts` with bill-search response parsing and saved-search CRUD/results/open functions. Require authentication for saved-search functions through the existing authenticated request helper. `getSavedSearchResults(id, page)` uses the owner-scoped results route; `openSavedSearch(id, resultWatermark)` submits only the signed watermark returned with that successful result page.

- [ ] Run:

```bash
rtk run "cd legislation-tracker-client && node --disable-warning=ExperimentalWarning --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --experimental-strip-types --test tests/bill-filter-params.test.ts tests/api-search.test.ts"
rtk run "cd legislation-tracker-client && pnpm typecheck"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-client/lib legislation-tracker-client/tests
rtk git commit -m "feat(discovery): define frontend search contracts"
```

## Task 7: Build the bills discovery UI

**Files:**

- Modify: `legislation-tracker-client/app/bills/page.tsx`
- Create: `legislation-tracker-client/app/bills/bill-search-controls.tsx`
- Create: `legislation-tracker-client/app/bills/search-highlight.tsx`
- Create: `legislation-tracker-client/app/bills/saved-searches.tsx`
- Modify: `legislation-tracker-client/tests/components/bills-page.test.tsx`
- Create: `legislation-tracker-client/tests/components/saved-searches.test.tsx`

- [ ] Write interaction tests before components: typing is debounced; Enter searches immediately; filter/sort changes update the URL and reset page; back/forward restores controls; match segments render without `dangerouslySetInnerHTML`; signed-out users see a sign-in affordance; save/open/rename/delete errors preserve user input; opening submits the returned watermark only after bill results render; and activity arriving between result resolution and the open POST remains visible as new on refresh.

- [ ] Split controls and results into focused components. Keep the page's existing filters and add `q`, `sort`, highlights, loading states, no-result copy, and retry behavior.

- [ ] Add the authenticated saved-search panel with name validation, a maximum-state message, new-result badges, and a destructive-confirmation step for delete. Do not show email, RSS, or alert language.

- [ ] Ensure labels, keyboard focus, live result counts, and highlighted text are accessible without color. Verify narrow-screen layout does not require horizontal scrolling.

- [ ] Run:

```bash
rtk run "cd legislation-tracker-client && pnpm exec vitest run tests/components/bills-page.test.tsx tests/components/saved-searches.test.tsx"
rtk run "cd legislation-tracker-client && pnpm lint"
rtk run "cd legislation-tracker-client && pnpm typecheck"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-client/app/bills legislation-tracker-client/tests/components
rtk git commit -m "feat(discovery): build bill search experience"
```

## Task 8: Add real browser and operational coverage

**Files:**

- Create: `legislation-tracker-client/e2e/bill-discovery.spec.ts`
- Modify: `legislation-tracker-backend/docker-compose.e2e-postgres.yml`
- Modify: `legislation-tracker-backend/scripts/start-e2e-api.sh`
- Create: `legislation-tracker-backend/scripts/seed-e2e-legislative-intelligence.py`
- Modify: `legislation-tracker-backend/apps/legislation/admin.py`
- Modify: `legislation-tracker-backend/apps/ingestion/admin.py`
- Modify: `legislation-tracker-backend/README.md`
- Modify: `legislation-tracker-client/README.md`

- [ ] Add a dedicated PostgreSQL E2E service on port 55432/database `legislation_e2e`. Change `start-e2e-api.sh` to honor `E2E_DATABASE_URL`, using its existing disposable SQLite URL only when the variable is absent and deleting a file only for a SQLite URL. Add a deterministic seed script with independent metadata-, contract-, and document-only phrases plus saved-search race fixtures.

- [ ] Add Playwright coverage that signs in, searches for metadata/contract/document-only phrases against PostgreSQL, combines a filter, changes sort, saves the query, simulates newer matching and nonmatching activity through fixtures, verifies the badge, opens successfully with the result watermark, and verifies the count resets only through that snapshot. Include activity between result fetch and acknowledgement, failed-results, and unauthorized states.

- [ ] Expose read-only search chunk status and queue failure information in admin without exposing full document text in list views.

- [ ] Document index enqueue triggers, preview/execute backfill commands, PostgreSQL requirements, retry/dead-letter replay, and the exact fields excluded from indexing.

- [ ] Run the complete release gate:

```bash
rtk docker compose -f legislation-tracker-backend/docker-compose.e2e-postgres.yml up -d
rtk run "cd legislation-tracker-backend && DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/legislation_e2e .venv/bin/pytest -q"
rtk run "cd legislation-tracker-backend && .venv/bin/ruff check ."
rtk run "cd legislation-tracker-client && pnpm test"
rtk run "cd legislation-tracker-client && pnpm typecheck"
rtk run "cd legislation-tracker-client && pnpm lint"
rtk run "cd legislation-tracker-client && pnpm build"
rtk run "cd legislation-tracker-client && E2E_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/legislation_e2e pnpm test:e2e -- e2e/bill-discovery.spec.ts"
rtk git diff --check
```

- [ ] Inspect the PostgreSQL query plan for a representative multi-word search and record that the GIN index is used in the PR description. Record backfill preview counts and queue/dead-letter counts separately from test results.

- [ ] Commit:

```bash
rtk git add legislation-tracker-backend legislation-tracker-client
rtk git commit -m "test(discovery): cover search and saved-search journeys"
```

## Completion criteria

- Search finds phrases from metadata, the latest contract, and active document text with safe bounded highlights.
- Search/filter/sort state is reproducible from the URL.
- Saved searches are private, validated, capped, rerunnable, and show correct activity-based new-result counts.
- Stored document versions create exactly one canonical `new_version` event in the same commit as their database state.
- Saved-search acknowledgement uses a query-bound result watermark and cannot erase activity committed during rendering.
- Indexing survives retries and replay and can be previewed/backfilled without synchronous bulk work.
- PostgreSQL integration, component, and Playwright tests exercise behavior rather than source strings.
