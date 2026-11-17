# Read-path optimizations

## Behavior preserved

- Search still returns up to three highlighted excerpts per bill, with the same rank and ID tie-breaking. PostgreSQL now selects their IDs before invoking `ts_headline`.
- Bill cards receive the same list payload. List queries no longer join full contracts or prefetch document text.
- Outside-spending totals, period selection, partial-result warnings, and published-snapshot fallback are preserved.
- Enhancement sharing still checks source identity and output validation; it does not call an LLM.

## Reuse and invalidation

- Outside-spending revisions are scoped to one representative. Database triggers cover snapshot, scan, total, and research-run mutations, including bulk updates and deletion. Unrelated bill ingestion does not invalidate spending pages.
- The client appends pages from the same revision. Polling checks the first page; an unchanged revision retains the visible prefix. Changed revisions replace the prefix atomically. Revision conflicts are retried at most three times; aborts and network errors are not retried by this loader.
- Totals are cached by revision. The one-hour cache lifetime only bounds storage of obsolete generations; writes invalidate immediately through a new revision. Cache failures fall back to the database. Coverage/status is checked live rather than cached across worker state transitions.
- Stored generated columns hash document text and enhancement result/source JSON. The database recomputes them on writes, including `QuerySet.update`. Validation verdicts include the validator version. Warm lookups do not load the large JSON fields.

## Regression evidence

- Six-period outside-spending fixture: original warm request used 33 queries; regression caps the optimized request at 12 and verifies no repeated SUM query. A bulk amount change invalidates totals and old page revisions.
- A 100-chunk-per-bill fixture returns only three ranked chunks per bill; PostgreSQL integration verifies the displayed excerpts still highlight the requested term.
- For twenty obsolete enhancement results, the regression caps source/history lookup at three queries, without selecting large source/result payloads.
- Client loader tests cover append, unchanged polling, changed ordering, mid-pagination revision conflicts, bounded retries, and cancellation.

## Rollout

Apply backend migrations before starting the updated backend:

- `legislation.0025_reader_lookup_digests` adds stored generated columns and PostgreSQL's `pgcrypto` extension. It computes hashes for existing rows; allow for migration time and table locks on a large database. The migration role needs extension-creation permission.
- `campaign_finance.0010_outside_revision_triggers` adds the representative-scoped revision table and mutation triggers.

No analysis regeneration, paid API calls, or source-text changes are required. Tests use isolated databases; production throughput and browser rendering have not been benchmarked by this change.
