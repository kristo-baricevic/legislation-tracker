# Bill Change Experience Implementation Plan

> **Status (2026-08-31):** Implemented. This file retains the original TDD execution checklist as historical design context; current behavior is documented in the linked specification.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give authenticated users a reliable unread bill-change experience, a unified event timeline, and safe contract/document comparisons while keeping the public timeline readable without persistence.

**Architecture:** The canonical partitioned `ChangeLog` is read with bill- and purpose-bound signed `(created_at, id)` keyset cursors for separate unread-forward and older-history directions. `BillViewState` stores only an acknowledgement cursor explicitly submitted after a signed-in user's canonical page renders. A page read never marks events seen. Contract and document comparison services produce identity-aware, cached, capped results from persisted versions and the existing federal structure parser.

**Tech Stack:** Django 5, Django REST Framework, PostgreSQL partitioned tables, Django signing, Next.js 16, React 19, TypeScript, Vitest/Testing Library, Playwright

**Spec:** `docs/superpowers/specs/2026-08-31-legislative-intelligence-design.md`

## Global Constraints

- Complete the centralized `record_bill_change` and `Bill.last_activity_at` foundation in `2026-08-31-bill-discovery-search.md` first.
- If representative relationships are implemented, consume their normalized change events; do not make them a prerequisite for the initial timeline.
- Use `rtk` for every shell command and `apply_patch` for hand-authored edits.
- Persist view state only for authenticated users.
- Do not acknowledge on page load, fetch completion alone, render failure, or stale route state.
- Never diff unbounded full documents or arrays by raw JSON index alone.
- Do not add a foreign key from view state to the partitioned `ChangeLog` table.
- Consume the atomic `new_version` producer implemented by the discovery plan; this track must not add a second document event path.
- Use `.venv/bin/python`, `.venv/bin/pytest`, and `.venv/bin/ruff` for backend commands, and execute timeline/concurrency/E2E release gates on PostgreSQL.

---

## Task 1: Make the canonical change stream complete and normalized

**Files:**

- Modify: `legislation-tracker-backend/apps/changelog/models.py`
- Modify: `legislation-tracker-backend/apps/changelog/services.py`
- Modify: `legislation-tracker-backend/apps/ingestion/tasks.py`
- Modify: `legislation-tracker-backend/apps/legislation/tasks.py`
- Create: `legislation-tracker-backend/apps/changelog/events.py`
- Create: `legislation-tracker-backend/apps/changelog/tests/test_events.py`
- Modify: relevant task tests under `legislation-tracker-backend/apps/ingestion/tests/` and `legislation-tracker-backend/apps/legislation/tests/`

- [ ] Inventory supported direct change writes with:

```bash
rtk grep -R -n "ChangeLog.objects.create\|record_bill_change" legislation-tracker-backend/apps
```

Write a failing test for each supported producer: bill creation, every metadata field diff, vote, contract, topic, and the discovery plan's existing document version producer. If representative insights already exists, include committee and cosponsor changes.

- [ ] Define stable event types and payload serializers in `events.py`. Initial ingestion emits `bill_created`. Later metadata changes emit `status_update`, `title_update`, `summary_update`, `sponsor_update`, `introduced_date_update`, or `action_update` only when the corresponding value changed. Each serializer strips the reserved internal `_event_key`, then returns one public shape with `type`, `occurred_at`, `summary`, optional before/after facts, and typed related-resource IDs. Reject every other payload key not declared for that event type.

Define the metadata diff inputs/outputs explicitly:

```python
@dataclass(frozen=True)
class BillMetadataSnapshot:
    title: str
    summary: str | None
    status: str
    sponsor_id: int | None
    introduced_at: date | None
    last_action_at: datetime | None

@dataclass(frozen=True)
class PendingBillChange:
    change_type: str
    old_value: dict | None
    new_value: dict
    event_key: str
```

- [ ] Implement `diff_bill_metadata(before: BillMetadataSnapshot, after: BillMetadataSnapshot) -> tuple[PendingBillChange, ...]` and call it inside the canonical bill-write transaction. Add regressions proving summary-only, sponsor-only, title-only, and last-action-only refreshes never emit `status_update`; unchanged refreshes emit nothing.

- [ ] Normalize the discovery plan's existing `new_version` payload for public output. Include document ID, version label, content hash, and whether it became active; do not move production out of the document transaction and do not include document text or presigned URLs.

- [ ] Ensure idempotent ingestion does not emit duplicate events. Add an event dedupe strategy tied to source identity/version hash, using an existing source identity where available or a deterministic dedupe key stored in event payload and checked under the bill transaction.

- [ ] Run:

```bash
rtk run "cd legislation-tracker-backend && .venv/bin/pytest apps/changelog/tests/test_events.py apps/ingestion/tests apps/legislation/tests/test_tasks.py -q"
rtk run "cd legislation-tracker-backend && .venv/bin/ruff check apps/changelog apps/ingestion apps/legislation"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-backend/apps/changelog legislation-tracker-backend/apps/ingestion legislation-tracker-backend/apps/legislation
rtk git commit -m "feat(changes): normalize the canonical bill change stream"
```

## Task 2: Add signed tuple cursors

**Files:**

- Create: `legislation-tracker-backend/apps/changelog/cursors.py`
- Modify: `legislation-tracker-backend/apps/changelog/models.py`
- Create: `legislation-tracker-backend/apps/changelog/migrations/0005_timeline_keyset_index.py`
- Create: `legislation-tracker-backend/apps/changelog/tests/test_cursors.py`

- [ ] Write failing tests for round-trip, timezone preservation, tampering, malformed signature data, missing fields, noninteger IDs, future schema versions, wrong bill, wrong direction/purpose, browse-cursor acknowledgement, and two events sharing the same timestamp. Cursors do not expire: persisted view state must remain usable after long absences.

- [ ] Implement a versioned signed cursor:

```python
@dataclass(frozen=True)
class ChangeCursor:
    version: int
    bill_id: int
    direction: Literal["after", "before", "head"]
    purpose: Literal["acknowledge", "browse", "stream_head"]
    created_at: datetime
    event_id: int

    @property
    def position(self) -> tuple[datetime, int]:
        return (self.created_at, self.event_id)
```

Implement exact interfaces `encode_change_cursor(cursor: ChangeCursor) -> str` and `decode_change_cursor(value: str, *, expected_bill_id: int, allowed_purposes: frozenset[str], allowed_directions: frozenset[str]) -> ChangeCursor`. Use `django.core.signing.dumps/loads` with a dedicated salt and compact JSON. Normalize to UTC. An acknowledgement-purpose cursor may be used as `after_cursor` or posted to acknowledgement; a browse cursor is accepted only as `before_cursor`; a stream-head cursor is informational only. Invalid cursors raise a typed validation exception that the API maps to HTTP 400. Do not silently fall back to the beginning.

- [ ] Add query helpers expressing strictly-after and strictly-before tuple predicates:

```python
Q(created_at__gt=ts) | Q(created_at=ts, id__gt=event_id)
```

and the matching strict-before inverse. Test ordering by `created_at`, then `id` in both directions.

- [ ] Add model state and migration for `Index(fields=["bill", "created_at", "id"], name="changelog_bill_cursor_idx")`. Because `ChangeLog` is a PostgreSQL partitioned table with custom migration state, create the parent partitioned index in database operations and keep state synchronized with `SeparateDatabaseAndState` where required. PostgreSQL tests query `pg_indexes`/partition catalogs to prove each active child has an attached usable index; migration reversal removes only this index.

- [ ] Run:

```bash
rtk run "cd legislation-tracker-backend && DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/legislation_e2e .venv/bin/pytest apps/changelog/tests/test_cursors.py -q"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-backend/apps/changelog
rtk git commit -m "feat(changes): add signed change cursors"
```

## Task 3: Persist authenticated bill view state safely

**Files:**

- Modify: `legislation-tracker-backend/apps/accounts/models.py`
- Create: `legislation-tracker-backend/apps/accounts/migrations/0008_billviewstate.py`
- Create: `legislation-tracker-backend/apps/accounts/bill_views.py`
- Create: `legislation-tracker-backend/apps/accounts/tests/test_bill_view_state.py`

- [ ] Write failing tests for one row per user/bill, independent users, no `ChangeLog` foreign key, first acknowledgement, repeated acknowledgement, older out-of-order acknowledgement, equal timestamp with larger/smaller ID, and concurrent monotonic updates.

- [ ] Add `BillViewState` with user, bill, nullable `last_viewed_at`, nullable `last_seen_change_created_at`, nullable `last_seen_change_id`, and `updated_at`; add a unique `(user, bill)` constraint and index `(user, updated_at)`.

- [ ] Implement:

```python
def acknowledge_bill_changes(
    *, user: User, bill: Bill, cursor: ChangeCursor, acknowledged_at: datetime
) -> BillViewState:
    """Monotonically store a bill-bound acknowledgement-purpose cursor."""
```

Within one transaction, require `cursor.bill_id == bill.id`, `purpose == "acknowledge"`, and an existing exact event for the requested bill. Use a row lock or conditional tuple update so an older request cannot move state backward. `last_viewed_at` records the successful acknowledgement time, not the source event time. Browse and stream-head cursors must be rejected.

- [ ] Add a service for resolving the stored cursor and unread count without creating a state row during GET.

- [ ] Run:

```bash
rtk run "cd legislation-tracker-backend && DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/legislation_e2e .venv/bin/pytest apps/accounts/tests/test_bill_view_state.py -q"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-backend/apps/accounts
rtk git commit -m "feat(changes): persist authenticated bill view state"
```

## Task 4: Expose a keyset-paginated bill timeline and acknowledgement API

**Files:**

- Create: `legislation-tracker-backend/apps/changelog/serializers.py`
- Create: `legislation-tracker-backend/apps/changelog/views.py`
- Modify: `legislation-tracker-backend/config/urls.py`
- Create: `legislation-tracker-backend/apps/changelog/tests/test_timeline_api.py`

- [ ] Write failing API tests for public reads, authenticated unread state, no state creation on GET, stored-cursor default, explicit `after_cursor`, initial newest window, `before_cursor` older pagination, same-timestamp events in both directions, page-size bounds, rejection of unknown parameters including `type`, invalid/tampered/wrong-purpose cursors, anonymous acknowledgement, cross-user isolation, cross-bill acknowledgement, an older acknowledgement, and an event arriving between GET and POST.

- [ ] Add:

```text
GET  /api/bills/{bill_id}/changes/?after_cursor=&before_cursor=&page_size=
POST /api/bills/{bill_id}/changes/acknowledge/
```

`after_cursor` and `before_cursor` are mutually exclusive. An explicit/stored `after_cursor` selects strictly newer canonical events oldest-first by `(created_at, id)`. `before_cursor` selects strictly older events with a newest-first database query, then normalizes that bounded page into chronological display. With neither cursor, GET selects the newest bounded window and reverses it for display. It returns:

```json
{
  "results": [],
  "page_end_cursor": "signed-value-or-null",
  "stream_head_cursor": "signed-value",
  "older_cursor": "signed-value",
  "has_more_newer": false,
  "has_more_older": true,
  "unread_count": 0,
  "personalized": true,
  "initial_window_truncated": true
}
```

For anonymous users, `unread_count` is null and `personalized` is false. When an authenticated request omits both cursors, use stored state for unread progression; when no state exists, return the bounded recent history and count within that advertised window rather than an unbounded count. Only an initial canonical page or an unfiltered after-page returns acknowledgement-purpose `page_end_cursor`; an older-page response returns it as null. `older_cursor` is browse-purpose and `stream_head_cursor` is informational. The query serializer rejects `type`; filters are client-side, so pagination and acknowledgement cannot skip hidden events.

- [ ] Acknowledgement accepts only `{"cursor": "signed-value"}`, validates that the exact event belongs to the bill, advances monotonically, and returns the stored cursor plus the count of events now newer than it. The client sends `page_end_cursor`, never `stream_head_cursor`. This preserves unread work when another page exists or a change arrives between load and acknowledgement.

- [ ] Fetch related bill/document/contract/vote identifiers without per-event queries. Test an upper query-count bound for a full page.

- [ ] Run:

```bash
rtk run "cd legislation-tracker-backend && DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/legislation_e2e .venv/bin/pytest apps/changelog/tests/test_timeline_api.py -q"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-backend/apps/changelog legislation-tracker-backend/config/urls.py
rtk git commit -m "feat(changes): expose bill timeline and acknowledgement"
```

## Task 5: Implement schema-aware contract comparisons

**Files:**

- Create: `legislation-tracker-backend/apps/legislation/comparison.py`
- Create: `legislation-tracker-backend/apps/legislation/tests/test_contract_comparison.py`

- [ ] Write fixtures/tests for scalar add/remove/change, nested objects, reordered arrays, every contract array category, missing identities, duplicate/colliding identities, schema-version differences, null vs absent, 200-entry truncation, and deterministic output order.

- [ ] Implement public types:

```python
@dataclass(frozen=True)
class ContractChange:
    path: str
    operation: Literal["added", "removed", "changed"]
    before: JSONValue | None
    after: JSONValue | None
```

Implement exact interface `compare_contracts(*, before: BillContract, after: BillContract, limit: int = 200) -> ContractDiff`.

- [ ] Define a versioned `CONTRACT_ITEM_IDENTITIES` registry for every list in the current deterministic contract schema. Each entry names the exact normalized field tuple used as identity (including section/evidence anchors where present). Build both sides into identity multimaps; a key appearing more than once on either side is ambiguous and must emit bounded add/remove operations, never a fabricated `changed`. For an unknown list without a registered identity, compare normalized values as a multiset and report the enclosing path; do not present index movement as a legal change.

Use these v1 identities after Unicode whitespace/case normalization (preserve original values in output):

| Array path | Identity tuple |
| --- | --- |
| `key_provisions` | `(section_label, kind, heading)` |
| `requirements` | `(section_label, modality, actor, action, object)` |
| `funding_items` | `(section_label, amount_type, currency, purpose)` |
| `timeline_items` | `(section_label, timeline_type, trigger)` |
| `definitions` | `(section_label, term)` |
| `applicability` | `(section_label, subject, applicability_type)` |
| `amendment_operations` | `(section_label, target, operation)` |
| `requirements[*].conditions` | normalized string multiset |
| `funding_items[*].fiscal_years` | integer multiset |
| `extraction.warnings`, `limitations` | normalized string multiset |

Fields intentionally omitted from an identity are eligible to appear as `changed` values. If one of the identity tuples collides, report the colliding items as adds/removes; do not use array position as a tie-breaker.

- [ ] Bound serialized before/after values per change and return `total_change_count`, `returned_change_count`, and `truncated`. Reject comparisons across different bills.

- [ ] Run:

```bash
rtk run "cd legislation-tracker-backend && .venv/bin/pytest apps/legislation/tests/test_contract_comparison.py -q"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-backend/apps/legislation/comparison.py legislation-tracker-backend/apps/legislation/tests/test_contract_comparison.py
rtk git commit -m "feat(changes): add bounded contract comparisons"
```

## Task 6: Implement section-aware document comparisons

**Files:**

- Modify: `legislation-tracker-backend/apps/legislation/comparison.py`
- Reuse: `legislation-tracker-backend/apps/legislation/extraction/federal_structure.py`
- Create: `legislation-tracker-backend/apps/legislation/tests/test_document_comparison.py`

- [ ] Write tests for added/removed/unchanged/modified federal sections, reordered unchanged sections, repeated `(a)`/`(1)` labels under different ancestors, duplicate same-path headings, inactive predecessor versus active current document, legacy paragraph fallback, empty/inaccessible text, one enormous line, repeated adversarial text, 50,000-character per-side cap, 500-operation cap, and deterministic hashes.

- [ ] Implement two exact interfaces: `compare_document_sections(*, before: BillDocument, after: BillDocument) -> DocumentSectionDiff` and `compare_document_section(*, before: BillDocument, after: BillDocument, section_key: str) -> DocumentLineDiff`.

Walk the existing parser output in source-offset order. Resolve each `parent_label` to the nearest preceding section whose span contains the child, append the normalized current label to that parent's full path, then append an occurrence ordinal counted only among identical full paths. Hash the section content with SHA-256. This produces keys such as `title-i/sec-2/(a)#1` without conflating another section's `(a)`. Return summaries first. Only diff one requested modified section, and apply limits of 50,000 characters and 2,000 lines per side before diffing, then cap returned operations at 500.

- [ ] For non-federal or unparseable text, construct bounded paragraph blocks with deterministic keys. Use a bounded line/paragraph algorithm; never call `SequenceMatcher` over both complete document bodies.

- [ ] Return cap/truncation reasons explicitly. Allow inactive historical documents when both IDs belong to the requested bill and accessible stored/extracted text exists. Reject different-bill comparisons, missing text, or inaccessible storage with a typed domain error.

- [ ] Run:

```bash
rtk run "cd legislation-tracker-backend && .venv/bin/pytest apps/legislation/tests/test_document_comparison.py -q"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-backend/apps/legislation/comparison.py legislation-tracker-backend/apps/legislation/tests/test_document_comparison.py
rtk git commit -m "feat(changes): add bounded document comparisons"
```

## Task 7: Expose comparison APIs

**Files:**

- Modify: `legislation-tracker-backend/apps/legislation/serializers.py`
- Modify: `legislation-tracker-backend/apps/legislation/views.py`
- Modify: `legislation-tracker-backend/apps/legislation/throttles.py`
- Modify: `legislation-tracker-backend/config/settings/base.py`
- Modify: `legislation-tracker-backend/config/urls.py`
- Create: `legislation-tracker-backend/apps/legislation/tests/test_comparison_api.py`

- [ ] Write tests for:

```text
GET /api/bills/{bill_id}/compare/contracts/?from={contract_id}&to={contract_id}
GET /api/bills/{bill_id}/compare/documents/?from={document_id}&to={document_id}
GET /api/bills/{bill_id}/compare/documents/?from={document_id}&to={document_id}&section={key}
```

Cover missing/invalid IDs, same version, reversed chronology, cross-bill IDs, inactive same-bill predecessors, unavailable document text, encoded section keys, input/output caps, stable response schemas, authenticated/anonymous throttle buckets, and a 429 before body loading/diff work.

- [ ] Add strict query serializers. Allow either chronological direction but label `from` and `to` exactly as requested. Return 404 for a source version outside the requested bill without revealing that another bill owns it.

- [ ] Include source metadata needed by the UI: IDs, labels, timestamps, content/contract hashes, active/latest flags, counts, and truncation fields. Do not return entire source JSON or document text alongside the diff.

- [ ] Attach `BillComparisonThrottle` with scopes `bill_compare_anon` and `bill_compare_user`, defaulting to `10/min` and `60/min`, with environment overrides `BILL_COMPARE_ANON_RATE` and `BILL_COMPARE_USER_RATE`. Cache successful bounded results by `(comparison_kind, before_hash, after_hash, section_key, algorithm_version)` only after ownership/text validation; never cache an authorization failure, presigned URL, credential, or mutable model serialization. Add tests for versioned invalidation and absence of cross-request private data.

- [ ] Run:

```bash
rtk run "cd legislation-tracker-backend && .venv/bin/pytest apps/legislation/tests/test_comparison_api.py -q"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-backend/apps/legislation legislation-tracker-backend/config/urls.py
rtk git commit -m "feat(changes): expose bill comparison APIs"
```

## Task 8: Define frontend change and comparison contracts

**Files:**

- Modify: `legislation-tracker-client/lib/api.ts`
- Create: `legislation-tracker-client/lib/bill-changes.ts`
- Create: `legislation-tracker-client/tests/api-changes.test.ts`

- [ ] Write failing runtime parsing tests for every normalized event, unknown future event types, nullable anonymous unread state, forward/browse cursor fields and flags, malformed cursors, contract changes, section summaries, line operations, and truncation metadata.

- [ ] Define discriminated unions for event types and comparison operations. Unknown future event types must render through a safe generic event rather than crashing the timeline.

- [ ] Add API functions for timeline fetch, acknowledgement, contract comparison, document section summary, and one-section detail. Acknowledgement must require the existing authenticated request path and CSRF/session behavior.

- [ ] Implement a pure acknowledgement guard that accepts bill ID, request generation, rendered cursor, and current route bill ID, and returns true only when all refer to the newest successful render for the current bill.

- [ ] Run:

```bash
rtk run "cd legislation-tracker-client && node --disable-warning=ExperimentalWarning --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --experimental-strip-types --test tests/api-changes.test.ts"
rtk run "cd legislation-tracker-client && pnpm typecheck"
```

- [ ] Commit:

```bash
rtk git add legislation-tracker-client/lib legislation-tracker-client/tests/api-changes.test.ts
rtk git commit -m "feat(changes): define frontend timeline contracts"
```

## Task 9: Build the bill timeline without false acknowledgement

**Files:**

- Modify: `legislation-tracker-client/app/bills/[id]/page.tsx`
- Create: `legislation-tracker-client/app/bills/[id]/change-timeline.tsx`
- Create: `legislation-tracker-client/app/bills/[id]/change-event.tsx`
- Modify: `legislation-tracker-client/tests/components/bill-detail-page.test.tsx`
- Create: `legislation-tracker-client/tests/components/change-timeline.test.tsx`

- [ ] Write interaction tests for public vs signed-in display, unread badge, equal-timestamp events, client-side type filters, loading older history, unread forward pagination, links, unknown event fallback, load failure, retry, acknowledgement failure, event arrival between fetch/ack, unmount, and navigating from bill A to bill B before A resolves.

- [ ] Add the timeline to bill detail without removing existing contract and vote history. Render event types with accessible names and semantic timestamps. Filters affect display only; the acknowledgement cursor remains the newest cursor from the unfiltered canonical response.

- [ ] After a successful initial/forward timeline page render commits for the current bill, acknowledge only its acknowledgement-purpose `page_end_cursor`. Never acknowledge `older_cursor` or `stream_head_cursor`. Cancel or ignore stale requests through `AbortController` and a monotonically increasing request generation. If `has_more_newer` is true, leave remaining events unread until the next after-page renders. Loading `has_more_older` history must not change unread state. On acknowledgement response, retain any server-reported newer unread events.

- [ ] Do not retry acknowledgement in a tight loop. Show a nonblocking “could not mark as viewed” state and retry only on a later successful refresh or explicit user retry.

- [ ] Run:

```bash
rtk run "cd legislation-tracker-client && pnpm exec vitest run tests/components/bill-detail-page.test.tsx tests/components/change-timeline.test.tsx"
rtk run "cd legislation-tracker-client && pnpm typecheck"
```

- [ ] Commit:

```bash
rtk git add "legislation-tracker-client/app/bills/[id]" legislation-tracker-client/tests/components
rtk git commit -m "feat(changes): add reliable bill change timeline"
```

## Task 10: Build accessible contract and document diff views

**Files:**

- Modify: `legislation-tracker-client/app/bills/[id]/contract-section.tsx`
- Create: `legislation-tracker-client/app/bills/[id]/contract-diff.tsx`
- Create: `legislation-tracker-client/app/bills/[id]/document-diff.tsx`
- Create: `legislation-tracker-client/app/bills/[id]/version-compare-controls.tsx`
- Create: `legislation-tracker-client/tests/components/contract-diff.test.tsx`
- Create: `legislation-tracker-client/tests/components/document-diff.test.tsx`

- [ ] Write component tests for version selection, default inactive predecessor versus active current document, invalid same-version selection, add/remove/change labels, nested paths, section summary navigation, lazy one-section load, truncated results, unavailable text, retry, keyboard navigation, and screen-reader-visible operation labels.

- [ ] Add Compare actions to the existing contract/document history sections. Default `to` to the newest version and `from` to its immediate predecessor, while allowing explicit selection.

- [ ] Render additions with `<ins>` and removals with `<del>` plus text labels/icons so meaning does not depend on color. Keep long values collapsed with explicit expansion and never inject raw HTML.

- [ ] Load document section summaries first and request detailed operations only when a user opens a modified section. Surface server truncation accurately rather than suggesting a complete diff.

- [ ] Run:

```bash
rtk run "cd legislation-tracker-client && pnpm exec vitest run tests/components/contract-diff.test.tsx tests/components/document-diff.test.tsx"
rtk run "cd legislation-tracker-client && pnpm lint"
rtk run "cd legislation-tracker-client && pnpm typecheck"
```

- [ ] Commit:

```bash
rtk git add "legislation-tracker-client/app/bills/[id]" legislation-tracker-client/tests/components
rtk git commit -m "feat(changes): add accessible version comparisons"
```

## Task 11: Integrate tracking UI and add end-to-end verification

**Files:**

- Modify: `legislation-tracker-backend/apps/accounts/views.py`
- Modify: `legislation-tracker-backend/apps/accounts/serializers.py`
- Modify: `legislation-tracker-client/components/Dashboard.tsx`
- Modify: `legislation-tracker-client/tests/components/dashboard.test.tsx`
- Create: `legislation-tracker-client/e2e/bill-changes.spec.ts`
- Modify: `legislation-tracker-backend/docker-compose.e2e-postgres.yml`
- Modify: `legislation-tracker-backend/scripts/start-e2e-api.sh`
- Modify: `legislation-tracker-backend/scripts/seed-e2e-legislative-intelligence.py`
- Modify: `legislation-tracker-backend/apps/changelog/README.md`
- Modify: `legislation-tracker-client/README.md`

- [ ] Reuse the normalized event serializer and bill view state in the tracked-change feed. Add batched unread counts without changing a user's view state. Write a bounded query-count test for a dashboard page.

- [ ] Update dashboard event labels/links and unread badges while preserving the existing tracked-bill/topic/member semantics.

- [ ] Seed multiple timeline partitions, equal timestamps, an inactive predecessor document, repeated federal subsection labels, and contract identity collisions in the PostgreSQL E2E database. Add a Playwright journey that signs in, opens a bill and acknowledges its initial timeline, injects status/version/contract/vote fixtures, revisits to see each unread change, browses older history without changing unread state, opens contract and inactive-to-active document comparisons, acknowledges, and verifies a later revisit has no unread changes. Add an event-between-load-and-ack case and a timeline-fetch failure case.

- [ ] Document cursor semantics, anonymous behavior, acknowledgement timing, event producer requirements, diff caps, partition compatibility, and debugging queries for state/event mismatches.

- [ ] Run the complete release gate:

```bash
rtk docker compose -f legislation-tracker-backend/docker-compose.e2e-postgres.yml up -d
rtk run "cd legislation-tracker-backend && DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/legislation_e2e .venv/bin/pytest -q"
rtk run "cd legislation-tracker-backend && .venv/bin/ruff check ."
rtk run "cd legislation-tracker-client && pnpm test"
rtk run "cd legislation-tracker-client && pnpm typecheck"
rtk run "cd legislation-tracker-client && pnpm lint"
rtk run "cd legislation-tracker-client && pnpm build"
rtk run "cd legislation-tracker-client && E2E_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/legislation_e2e pnpm test:e2e -- e2e/bill-changes.spec.ts"
rtk git diff --check
```

- [ ] Manually verify the PostgreSQL query plan for newest and strictly-after timeline queries uses the partition/index ordering, and record this separately from automated test results.

- [ ] Commit:

```bash
rtk git add legislation-tracker-backend legislation-tracker-client
rtk git commit -m "test(changes): cover unread timelines and version diffs"
```

## Completion criteria

- Public users can read a bounded recent bill timeline without persistent state.
- Signed-in users never lose same-timestamp, concurrent, or route-raced events and only advance state after a successful render/acknowledgement.
- Signed-in users can page older history independently without advancing unread state, and wrong-bill/browse cursors cannot be acknowledged.
- Bill creation, field-specific metadata, vote, contract, topic, and durable document-version changes share one truthful normalized event contract.
- Contract comparisons are schema-aware and capped; document comparisons are section-aware, lazy, and capped.
- Inactive historical document versions remain comparable to active successors when both have accessible text.
- Bill detail and dashboard behavior are covered by real component and Playwright interactions, including failure states.
