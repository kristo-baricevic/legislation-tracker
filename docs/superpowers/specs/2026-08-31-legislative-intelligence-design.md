# Legislative Intelligence Design

**Status:** Implemented foundations and product surfaces; representative source backfills remain operational follow-up

**Date:** 2026-08-31

**Scope:** Bill discovery, representative insights, and signed-in bill-change history

## Summary

This design adds three independently shippable product tracks on one PostgreSQL-first architecture:

1. Bill discovery: full-text search, highlighted matches, filters, saved searches, and recent-activity sorting.
2. Representative insights: voting summaries, sponsorship and co-sponsorship history, committee membership, and two-member comparison.
3. What changed: a signed-in user's unread bill changes, a unified change timeline, and bounded contract/document comparisons.

The tracks ship in that order. Discovery owns the shared activity timestamp and centralized change-recording service. Representative insights then adds the relationship data needed for richer member pages. What changed builds its cursor and comparison APIs on the same canonical change stream.

## Implementation status (2026-08-31)

- Discovery is implemented: bounded bill search indexing, full-text query/highlight API, recent-activity sorting, private saved searches, and the public URL-backed search UI.
- What changed is implemented: normalized activity events, signed timeline cursors, signed-in view state, explicit acknowledgement, and bounded contract/document comparison APIs and UI.
- Representative product and persistence foundations are implemented: Congress-scoped canonical vote identities, committee/cosponsor tables, exact-identity dependency blocking, representative detail/comparison APIs, and UI.
- The remaining operational work is to add official complete House/Senate roll-call discovery, official committee-roster snapshot synchronization, and the preview-first historical backfill command before representative voting/committee coverage can be labelled complete.

## Goals

- Make bills discoverable by words in metadata, the latest contract, and the active document text.
- Keep all search, activity, and saved-search state in PostgreSQL.
- Show factual, explainable representative statistics sourced from canonical votes and legislative relationships.
- Tell a signed-in user exactly what changed since that user last acknowledged a bill timeline.
- Preserve durable ingestion semantics: new derived data is queued, retryable, observable, and backfillable.
- Keep every response bounded so a pathological bill or document cannot exhaust API workers or browsers.

## Non-goals

- RSS feeds, newsletters, email delivery, or saved-search notifications.
- Elasticsearch, OpenSearch, or another external search service.
- Anonymous or browser-local last-view persistence.
- Ideology scores, predictive ratings, or inferred party-line labels.
- LLM-generated search, summaries, comparisons, or representative insights.
- Historical committee-roster reconstruction in the first release.
- GitHub Actions or unrelated deployment work.

## Approved decisions

- View state is persisted only for authenticated users.
- Search uses PostgreSQL full-text search.
- Representative data starts with the current Congress and continues forward. Historical backfill is preview-first and explicitly invoked.
- Saved searches support save, rerun, and a count of matching bills with activity since the search was last opened. They do not send anything.
- Comparison initially accepts exactly two representatives.
- The three tracks share foundations but remain separate implementation plans and release gates.

## Shared architecture

### Canonical activity time

Add indexed `Bill.last_activity_at` and `Bill.last_activity_sequence`. The timestamp is the newest successfully committed `ChangeLog.created_at` for display/sorting; the sequence is the lossless ordering boundary used by saved-search result watermarks. Neither is a proxy for `Bill.updated_at` or the upstream `last_action_at`.

All application code records bill changes through `apps.changelog.services.record_bill_change`. The service requires a non-null `new_value` mapping and an optional deterministic `event_key`; there is no empty-payload default. It locks a singleton `BillActivityClock` before the bill, allocates the next global sequence, deduplicates the first-class `ChangeLog.event_key` column, creates the `ChangeLog` row, and advances both bill activity fields in one transaction. Holding the clock row until commit means a result-snapshot transaction can wait for all earlier activity writers and force every later writer to receive a greater sequence. Existing direct `ChangeLog.objects.create` call sites migrate to this service.

`last_activity_at` is backfilled only from `Max(ChangeLog.created_at)`. Bills with changes receive deterministic global sequences ordered by their latest `(created_at, id)`; bills without changes keep both activity fields null. `last_action_at` and `updated_at` are not silently promoted into activity. A display-only `effective_activity_at = Coalesce(last_activity_at, last_action_at, updated_at)` annotation may be used for fallback ordering, but saved-search counts use only canonical activity sequence.

Document ingestion owns the `new_version` producer in Release 1. After object storage upload succeeds, the worker locks the bill before its document, persists the document storage/text fields, records a deterministic `new_version` event, and advances activity in one database transaction. The unchanged/retry path runs the same event reconciliation so a crash after upload cannot leave a stored version permanently absent from the activity stream.

This provides one definition for recent-activity sort, saved-search new-result counts, tracking feeds, and bill-detail unread state.

### Durable derived work

Search indexing and relationship ingestion use the existing persistent `IngestionWorkItem` queue. Producers enqueue work only after canonical writes commit. Work uses deterministic dedupe keys and source timestamps, so retries are safe and stale work cannot overwrite fresher derived state.

New work kinds:

- `search_index`, keyed as `bill:<bill-id>`.
- `bill_relationships`, keyed by the existing upstream bill identity.
- `representative_detail`, keyed as `bioguide:<bioguide-id>`.
- `roll_call_vote`, keyed as `vote:<congress>:<chamber>:<session>:<roll-number>`.

The existing retry, dead-letter, and replay controls apply. A relationship item whose representative dependency is missing enqueues `representative_detail` and returns to a dependency-wait state; a normal dependency miss is not dead-lettered. Per-Congress/chamber/session roll-call discovery cursors are persistent so polling restarts without gaps. Backfill commands preview counts by default and require `--execute` before writes or queueing.

### API rules

- Query serializers reject unknown parameters and invalid enum values.
- Collections use the existing page/page-size envelope and maximum page size.
- User-owned resources always filter by `request.user`; an ID alone never grants access.
- Expensive comparisons, headlines, and shared-vote results have explicit size limits and truncation metadata.
- Search and comparison endpoints have separate authenticated and anonymous throttle scopes. Search rejects oversized query bytes/tokens before PostgreSQL parsing; comparison validates source ownership, text availability, and caps before loading or diffing bodies.
- Frontend URL state is the authority for public search filters; authenticated saved state only stores a validated copy of that query.

## Track 1: Bill discovery

### Search index

Add `BillSearchChunk` in the legislation app:

| Field | Purpose |
| --- | --- |
| `bill` | Owning bill |
| `document` | Optional source document |
| `contract` | Optional source contract |
| `kind` | `metadata`, `document`, or `contract` |
| `source_key` | Stable identity within the kind |
| `ordinal` | Stable chunk order |
| `text` | Plain source text used for snippets |
| `search_vector` | PostgreSQL `SearchVectorField` |
| `source_hash` | Detects unchanged input |
| timestamps | Audit and rebuild visibility |

The unique key is `(bill, kind, source_key, ordinal)`. A GIN index covers `search_vector`; ordinary indexes support bill/kind cleanup.

Metadata is one weighted-A chunk containing the bill number, title, summary, status, sponsor identity, and assigned topic names. The latest contract is normalized into weighted-B, field-labelled text. Only the active document is indexed, in bounded paragraph/section-aware chunks weighted C. The indexer atomically replaces one bill's chunk set after all new chunks are prepared.

Full document text is not stored in one `tsvector`. Chunks are capped at 20,000 characters, do not split a paragraph unless a single paragraph exceeds the cap, and retain a deterministic ordinal.

### Query behavior

`GET /api/bills/` accepts:

- `q`: PostgreSQL `websearch` query.
- Existing bill/session/status/sponsor/topic filters.
- `sort`: `relevance`, `recent_activity`, `last_action`, or `introduced`.

When `q` is present, the service ranks metadata above contracts above document text, selects the best matching chunks per bill, and returns at most three sanitized highlight fragments. Search markers are converted to structured segments by the client; raw server-produced HTML is never injected into the DOM.

`sort=relevance` is valid only with `q`. Without an explicit sort, requests with `q` use relevance and requests without `q` use recent activity. SQLite supports deterministic metadata-only fallback for unit tests; PostgreSQL integration tests are authoritative for ranking and highlighting.

### Saved searches

Add `accounts.SavedBillSearch`:

- `user`
- `name`, unique per user
- `query_json`, containing only the normalized public search parameters
- `normalized_hash`, indexed for duplicate detection
- `last_opened_at`
- `last_opened_activity_sequence`
- timestamps

The API supports list, create, rename/update, delete, `GET /api/saved-searches/{id}/results/`, and `POST /api/saved-searches/{id}/open/`. The owner-scoped results endpoint executes the stored normalized query and is the only endpoint that issues a saved-search-bound watermark. Creation and update run the same search-query serializer used by `/api/bills/`; extra keys and unbounded values fail validation. A user may own at most 25 saved searches.

`new_result_count` is the count of bills matching the current saved query whose `last_activity_sequence` is greater than the acknowledged sequence. A never-opened saved search counts every currently matching bill with a non-null activity sequence. `last_opened_at` records the snapshot time for display, not ordering.

Opening a saved search is a two-step, lossless protocol. In one short PostgreSQL transaction, the bill-list request locks `BillActivityClock`, reads its committed sequence and database timestamp, executes the bounded result query, and returns both as a versioned, signed `result_watermark` bound to the owner, saved-search ID, and normalized query hash. Writers that committed first are visible before the snapshot; writers that commit later receive a greater sequence. After the page renders, `POST /api/saved-searches/{id}/open/` verifies the watermark and monotonically stores its sequence/timestamp rather than request-arrival time. Activity committed after the result snapshot but before acknowledgement therefore remains new. Updating a saved query resets both acknowledged fields.

### Frontend

The bills page gains a debounced search box, sort control, match snippets, an authenticated Save Search action, and a saved-search drawer/list. A dedicated `lib/bill-search.ts` owns parsing, normalization, and serialization so filter links, pagination, history navigation, and tests use one contract.

## Track 2: Representative insights

### Data model

Before adding representative analytics, make roll calls first-class current-Congress records. `Vote` gains a non-null `congress`, a stable identity of `(congress, chamber, session_number, roll_number)`, and optional question/source metadata. `Vote.bill` becomes nullable because procedural, nomination, and other roll calls are part of the denominator even when they do not identify a bill. Existing bill-linked votes are backfilled before constraints change.

Add:

- `Committee`: Congress system code, name, chamber, type, optional parent, website, current flag, and source timestamp.
- `CommitteeMembership`: committee, representative, Congress, rank, normalized role, optional party side, current flag, and source timestamp.
- `BillCommittee`: bill, committee, relationship/activity label, and source timestamp.
- `BillCosponsor`: bill, representative, sponsorship date, original-cosponsor flag, optional withdrawal date, and source timestamp.

All upstream identities have database uniqueness constraints. Synchronization upserts by those identities. Committee adapters preserve the raw source code but resolve it through `normalize_committee_system_code(source, chamber, raw_code)`: House `II00` becomes `hsii00`, Senate codes receive the `ss` prefix, joint committees receive `js`, and canonical codes are lowercase. House assignment XML and Congress.gov bill committee payloads must resolve to the same canonical `Committee` row.

A roster parser returns a `CommitteeRosterSnapshot` containing Congress, chamber, publication time, source URL/hash, and assignments. Before changing current flags, synchronization verifies that the embedded Congress matches the requested Congress, the publication time satisfies the configured freshness window, the snapshot is non-empty, and its representative/committee coverage is not materially incomplete. A failed validation leaves the prior current roster intact.

### Upstream sources

- Bill committees and cosponsors come from the [Congress.gov API](https://api.congress.gov/) bill endpoints and its [official OpenAPI description](https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/openapi.json).
- Committee identities come from the official [committee endpoint documentation](https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/CommitteeEndpoint.md).
- Current House assignments come from the [House Clerk member XML](https://clerk.house.gov/xml/lists/MemberData.xml), listed on the House's [legislative branch data page](https://xml.house.gov/resources/SelectedList-LegisBranchData.htm).
- Current Senate assignments come from the Senate's [member and committee XML sources](https://www.senate.gov/general/XML.htm), using the [current senator assignment feed](https://www.senate.gov/legislative/LIS_MEMBER/cvc_member_data.xml).
- House roll calls come from the Congress.gov House vote list/detail endpoints; Senate roll calls come from the official Senate roll-call list/detail XML feeds. Discovery enumerates every current-Congress roll call, not only vote references attached to bills already ingested.

Fetchers enforce timeouts, response-size limits, XML/JSON shape validation, and exact Bioguide joins. An empty or materially incomplete snapshot fails closed and leaves the previous current roster intact.

Missing or partial member identities are repaired through durable `representative_detail` work. Relationship work records its dependency, queues the exact Bioguide detail, and resumes only after the representative upsert commits. This path covers current, departed, and former members referenced by current-Congress bills or roll calls.

### Descriptive analytics

`apps.congress.insights` computes results from canonical rows, initially without summary tables:

- Vote totals and rates for yes, no, present, not voting, and other/abstain.
- Participation rate with an explicit numerator and denominator.
- Sponsored and active cosponsored bill counts and paginated histories.
- Current committee memberships and leadership roles.
- Pairwise voting agreement for exactly two representatives.
- Coverage metadata for vote-derived results: first/last vote dates, total discovered roll calls, ingested roll calls, and `coverage_complete`.

Agreement includes only roll calls where both members cast yes or no. Present, not voting, and abstentions are excluded from the denominator and reported separately. The API returns raw counts alongside percentages so the result is auditable.

The participation denominator is every successfully discovered current-Congress roll call for the member's chamber and service interval, including non-bill votes. APIs display partial results only with explicit coverage metadata and never label a partial bill-linked subset as the member's voting pattern.

### API and UI

Add representative insight, sponsored-bill, cosponsored-bill, committee, and compare endpoints. The frontend adds a representative detail route and a comparison route with exactly two selected current members. Empty, incomplete, and low-sample states use factual copy and never imply ideology.

Current Congress ingestion runs on the existing schedule. A preview-first management command exposes historical backfill by Congress and limit, but historical committee membership completeness is not a release requirement.

## Track 3: What changed

### View state and cursors

Add `accounts.BillViewState` with a unique `(user, bill)` key and:

- `last_viewed_at`
- `last_seen_change_created_at`
- `last_seen_change_id`
- update timestamp

The stored cursor is the tuple `(ChangeLog.created_at, ChangeLog.id)`. It deliberately does not use a foreign key to the date-partitioned change table. API cursors are versioned, signed, opaque values containing the bill ID, direction, purpose, timestamp, and event ID. Tuple ordering prevents events with equal timestamps from being skipped; bill and purpose binding prevents cross-bill or browse-cursor acknowledgement.

A page GET never marks changes read. After the timeline renders successfully, the authenticated client posts the newest returned cursor to an acknowledgement endpoint. The server validates that the cursor references the same bill and advances state monotonically, making repeated or out-of-order acknowledgements safe.

Anonymous users can read the recent public timeline but receive no personalized unread count and cannot acknowledge it.

### Complete change stream

The centralized change service records truthful, field-specific events. Initial ingestion emits `bill_created`; later metadata diffs emit `status_update` only for a status change and use `title_update`, `summary_update`, `sponsor_update`, `introduced_date_update`, and `action_update` for their respective fields. Summary-only or sponsor-only refreshes never masquerade as status changes. It continues to record vote, contract, topic, and the Release-1 document `new_version` events. Representative ingestion may add normalized `cosponsor_update` and `committee_update` events once its relationship snapshot has committed.

Event payloads contain stable IDs and concise before/after facts, not copied document bodies or secrets.

### Timeline and comparison APIs

Add:

- `GET /api/bills/{id}/changes/`
- `POST /api/bills/{id}/changes/acknowledge/`
- `GET /api/bills/{id}/compare/contracts/`
- `GET /api/bills/{id}/compare/documents/`

The timeline has two distinct navigation contracts. `after_cursor` requests unread progression strictly newer than the supplied tuple and returns events oldest-first. `before_cursor` requests older history strictly before the supplied tuple and returns a bounded newest-first database page normalized into display order. An initial request returns the newest bounded window. Responses expose `page_end_cursor`, `older_cursor`, `stream_head_cursor`, `has_more_newer`, `has_more_older`, and authenticated `unread_count`.

Only an initial canonical page or an unfiltered `after_cursor` page returns an acknowledgement-purpose `page_end_cursor`. `before_cursor` is browse-only. The API rejects a server-side `type` parameter; type filters remain client-side, so acknowledgement can never leap over hidden events.

Contract comparison is a schema-aware JSON diff. A versioned `CONTRACT_ITEM_IDENTITIES` registry defines the normalized field tuple for every array category. Duplicate identity keys are ambiguous and produce bounded add/remove records rather than an invented modification. Results are capped at 200 changes and report truncation.

Document comparison accepts inactive historical predecessors as long as both documents belong to the requested bill and have accessible stored/extracted text. It rejects cross-bill IDs and missing or inaccessible text. The service first segments text with the existing federal structure parser and keys sections by full ancestor path plus same-path occurrence ordinal, so repeated `(a)`/`(1)` labels in different sections cannot collide. It reports added, removed, and modified sections by hash. A requested modified section receives a bounded line diff: at most 50,000 characters from each side and 500 operations. Legacy/non-federal documents fall back to bounded paragraph blocks. The service never runs an unbounded whole-document diff.

### Frontend

Bill detail gains a unified change timeline, unread badge, type filters, and links to the relevant vote, document, contract, or member. Existing contract history and vote history remain. Compare actions open accessible contract/document diffs using semantic additions and deletions rather than color alone.

The client acknowledges only the returned page-end cursor after every event through that cursor has rendered for the current bill. Fetch errors, render errors, or a route change never acknowledge unseen data. If more unread pages or a concurrently arriving event remain, the next response continues after the stored page-end cursor.

## Security and privacy

- Saved searches and bill view states are private to their owner.
- Signed cursors are verified and cross-checked against the requested bill.
- Saved-search result watermarks are signed and bound to the owning user, saved-search ID, and normalized query hash.
- Search highlights are plain structured segments, not trusted HTML.
- Source URLs are treated as data and never fetched from client input.
- XML parsers disable external entities and enforce payload limits.
- No API key, LLM credential, or private enhancement content enters search chunks or change payloads.

## Performance budgets

- Bill list queries remain paginated and return no raw search chunks.
- Search returns at most three snippets per bill and uses a GIN index in PostgreSQL.
- Saved-search counts are computed in a batched service, not one query per card.
- The global activity-clock lock is held only by one bounded saved-search result page or one canonical event transaction; record lock wait time and keep network/object-storage work outside it.
- Representative list/detail endpoints prefetch bounded related data and expose paginated histories.
- Comparison endpoints enforce input and output caps before diffing.
- Timeline pagination uses `(created_at, id)` keyset ordering rather than deep offsets.
- `ChangeLog` has a PostgreSQL parent index on `(bill_id, created_at, id)` and verification confirms usable child-partition indexes.
- Versioned comparison results are cached only by comparison kind, both source hashes, selected section key, and algorithm version; user credentials and mutable URLs never enter a shared cache value.

## Testing strategy

Each track follows test-driven development at four levels:

1. Pure unit tests for normalization, parsers, cursor logic, chunking, and diff caps.
2. Django API/service tests for authorization, validation, idempotency, and query counts.
3. PostgreSQL integration tests for full-text ranking/highlights, signed saved-search watermarks, tuple cursors in both directions, partition indexes, row-lock concurrency, and complete roll-call coverage.
4. Frontend component tests plus Playwright journeys that exercise actual interactions and negative states.

Tests must assert behavior and persisted state. Source-string tests are not accepted as coverage for these features.

## Delivery order and release gates

### Release 1: Discovery

- Central change service, activity timestamp/sequence, and singleton clock are backfilled.
- Stored document versions produce atomic, retry-safe `new_version` events before saved-search activity counts launch.
- Search index is built for the target Congress and queue lag is healthy.
- Search, filters, sorting, saved searches, and new counts pass PostgreSQL and browser tests.

### Release 2: Representative insights

- Current House and Senate memberships validate against current representative identities and cross-source committee identities.
- Every current-Congress House and Senate roll call is discoverable through a persistent cursor and its detail work is durable/replayable.
- Current-Congress bill relationships are ingested without unresolved-identity drift.
- Detail and two-member comparison pages pass accuracy, query-count, and browser tests.

### Release 3: What changed

- Every supported canonical change uses the centralized service.
- Timeline forward/browse cursor and acknowledgement tests pass under equal timestamps, older pagination, cross-bill attempts, and out-of-order requests.
- Contract/document comparisons respect caps on adversarial inputs.
- Authenticated revisit behavior passes end to end.

Each release can be disabled at the frontend route/action layer while its ingestion backfill runs. Database migrations are additive; destructive cleanup is deferred until metrics and data checks confirm the new paths are authoritative.

## Acceptance criteria

- A user can find a bill from a phrase appearing only in its active text and see a safe highlighted fragment.
- A signed-in user can save that query, reopen it, and see a correct count of matching bills active since the prior successful result snapshot, including activity committed between result rendering and acknowledgement or by a writer that overlapped snapshot creation.
- A representative page explains vote participation across all current-Congress roll calls, sponsorship, co-sponsorship, and current committee assignments with raw counts and coverage metadata.
- A user can compare exactly two representatives and audit the shared votes behind the agreement rate.
- A signed-in user can revisit a bill, see all changes after the last acknowledged cursor, inspect bounded contract/document differences, and acknowledge them without losing equal-timestamp or concurrently arriving events.
