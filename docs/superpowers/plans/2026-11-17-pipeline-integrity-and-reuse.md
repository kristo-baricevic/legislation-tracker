# Pipeline integrity and reuse

## Goal

Correct the demonstrated financial validation failures, process large bills in bounded requests, and reuse completed work without repeating paid section calls. Preserve existing source evidence, user authorization, and ambiguous-outcome protections. Work in the current checkout, single-agent, with offline provider fixtures.

## Implemented

- [x] Independent currency/percentage validation against each item's cited passages. Equivalent dollar notation is allowed; invented amounts are rejected.
- [x] Explicit money and funding instructions cannot be omitted solely by labeling them `not_financial`. Financial explanations must collectively retain cited explicit dollar amounts.
- [x] Apply the checks to stored reviews, summaries, and target explanations. Revalidate old shared reader results with a content-addressed validation cache.
- [x] Durable shared call reservations and validated responses, independent of the paying user's attempt. Source reviews normalize reference IDs and document offsets while retaining governing-context hashes, schemas, prompts, provider/model and reasoning settings. Changed context invalidates reuse.
- [x] PostgreSQL concurrency regression: two callers cannot both dispatch the same paid request. Ambiguous calls remain reserved and are not automatically replayed.
- [x] Known truncation/validation failures survive worker continuations without being mistaken for ambiguous dispatches or paying again for completed calls.
- [x] Whole-source chunk coverage, bounded context for oversized sections, and a finite source-sized confirmation budget. A positive operator call cap remains enforced; zero derives the budget from the source plan.
- [x] Summary generation after full-source review, with bounded hierarchical summarization when the validated inventory does not fit one request. Only passages actually supplied to each summary call are selectable citations.
- [x] Yield after eight new provider calls per worker delivery by default. Continue the same attempt from durable results; cached calls do not consume the delivery allowance. Fence old dispatch tokens.
- [x] Reuse the request plan at checkpoints while checking live source, evidence, metadata, configuration and credentials. Aggregate token usage in SQL without loading response JSON.
- [x] Cache unchanged deterministic extraction and topic matching by input and implementation/taxonomy version. Explicit re-extraction and schema backfills bypass extraction reuse.
- [x] Bulk contribution-page persistence, preserving source revisions, refunds, duplicate detection and atomic cursor advancement.
- [x] Chunked FEC reads under an interruptible total deadline. Keep byte-at-a-time deadline checking on platforms where the timer cannot safely be armed.

## Verification

Tests use pinned sources and fake providers, not a paid model. Regressions were observed failing before the respective fixes. Coverage includes wrong amounts, omitted grants and percentage allocations, shifted source offsets, different users, source changes, process interruption, output truncation, bounded corrections, yielded deliveries, and a 90-section bill through final summary generation.

The 100-record contribution fixture previously made 701 queries; the regression now requires at most 15 and checks that an amended row rolls back both new records and cursor changes.

Full-suite verification: SQLite passed 1,739 tests (17 skipped); PostgreSQL passed 1,751 tests (3 skipped). The PostgreSQL run preceded the final continuation-replay correction; the final reader pipeline, shared-result and durable-call tests then passed separately against PostgreSQL (27 passed). SQLite cannot exercise PostgreSQL locks. The disposable PostgreSQL container was removed after verification without changing the running application or its database. No paid API calls were made.

## Deployment

Apply migrations `0023_shared_enhancement_calls` and `0024_processing_cache` (and the preceding `0022_similarity_checkpoints` from the earlier work) before deploying the workers. Restart the application's workers through the normal deployment process. No application database migration or paid regeneration was performed by this implementation task.

`LLM_READER_MAX_CALLS=0` uses the source-sized confirmed maximum; an explicit positive value remains a hard ceiling. `LLM_READER_CALLS_PER_DELIVERY=8` controls fairness, not the total approved paid-call budget. All actual requests remain byte-bounded and each attempt remains call-bounded.

Extractor changes must bump the active extractor version; topic algorithm changes must bump the processing-cache version. Reader validator changes must bump `VALIDATOR_VERSION`, so previously checked results are not trusted under a different validator.

## Broader audit items not completed in this change

- [ ] Replace duplicate NLP-target rewrites plus source-review interpretation with one unified fact inventory.
- [ ] Formal cross-chunk dependency resolution and semantic verification of percentage bases, actors, modalities, and all meaning-changing conditions. Numeric/citation gates are safeguards, not proof of complete legal accuracy; bounded local context does not resolve arbitrary distant references.
- [ ] Dollar-denominated reservations and cached-token pricing/accounting. Current confirmation bounds requests and tokens, not an invoice amount.
- [ ] Global broker admission control; the existing pending-dispatch lease can still republish a queued message. Atomic claims and shared call reservations prevent duplicate paid execution.
- [ ] Page-staged, resumable actions/relationships ingestion with atomic promotion, and resumable initial whole-document deterministic extraction. Unchanged extraction now reuses saved work, but its initial parse is still whole-document.
- [ ] Paid model-quality evaluation and a fresh constrained-production benchmark using the full database. Offline tests establish orchestration and validation behavior, not model comprehension or actual API invoice cost.
