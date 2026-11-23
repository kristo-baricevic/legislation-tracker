# Durable reader batching implementation plan

> Execute inline using test-driven development. No subagents, commits, pushes, or paid calls unless requested.

**Goal:** Process complete bills with bounded model-aware requests, durable recovery, and no duplicate calls for completed work.

**Architecture:** Keep Celery, the current validated-call cache and publication checks. Persist a tree of reader work units; account for actual dispatches separately from traversing/reusing work. Preserve complete source evidence while reducing the work assigned to each request.

**Tech stack:** Django/PostgreSQL, Celery, existing provider adapters and pytest.

**Spec:** Approved review in this conversation: all sections accounted for, shared results reused, targeted repairs, short final summary, budget exhaustion preserves progress.

## Constraints

- Preserve unrelated working-tree changes and existing source/financial validators.
- Default reasoning stays provider-controlled; pin the selected free model.
- Never blindly resend an ambiguously completed API request.
- No arbitrary increases to an existing confirmation's spending authorization.
- Test offline first; report live validation separately.

## Tasks and completion checks

### 1. Durable scheduling and real request accounting
- [x] Add failing combined recovery tests: cached siblings, truncation, restart, and exhausted budget.
- [x] Add per-attempt work nodes with stable keys, parent relationships, pending/expanded/validated states and immutable request payloads.
- [x] Persist expansion/completion under the attempt lease. Count only reserved API dispatches against authorization.
- [x] Pause at the spending/request boundary with a resumable user-confirmed retry, rather than reporting bad model output.

### 2. Bounded full-source review
- [x] Test source review output planning, weighted partitioning, context retention and exact ownership coverage.
- [x] Apply output planning to source reviews, not just NLP targets. Keep stable citation IDs when narrowing output ownership.
- [x] Treat input, visible answer and reasoning allowances separately; support per-model capacity configuration and conservative defaults.
- [x] Preserve governing context; do not claim missing/remote dependencies have been resolved.

### 3. Targeted validation and diagnostics
- [x] Test retaining valid independent findings while repairing invalid ownership groups.
- [x] Save validated partial units, not unvalidated response prose; retry only unresolved obligations.
- [x] Record reasoning/visible token usage when returned, effective model settings, failure paths and split ancestry.
- [x] Keep summary generation after inventory completion and final publication validation.

### 4. Integration verification
- [x] Run the backend suite and migration checks.
- [x] Reconstruct the failing bill locally, verify complete ownership coverage and no repeated successful calls under mixed simulated failures.
- [x] Review changed lifecycle, budgets, retries and compatibility; document remaining live-provider uncertainty.

## Review focus

Cache hits at the budget boundary; worker death after provider dispatch; cross-boundary exceptions; unsplittable single obligations; source/model/config changes during a run.

## Execution record

Implementation authorized by the user; proceed without a separate planning approval. Use an inline self-review per the user's single-agent instruction. Existing dirty changes will not be committed as part of this task.

### Decisions and verification

- Kept full section context during output subdivision instead of mechanically
  shrinking wire text: arbitrary trimming can remove governing exceptions. The
  required output and ownership shrink; genuine input overflow fails explicitly.
- Added a single bounded output increase for an indivisible truncated obligation,
  still subject to the original aggregate token/call authorization. It cannot loop.
- Combined real executor/cache/work-plan test exercises truncation, partial
  validation, one-call worker deliveries, budget pause, explicit retry and final
  publication checks. It asserts each provider request is sent once and every
  owned passage remains present. Additional tests cover checkpoint crashes,
  cross-reference remapping, stale leases, token budgets and model pinning.
- Self-review caught and fixed two recovery issues: a cached partial response's
  model pin was rolled back with its signalling exception; direct summaries needed
  resolved citations persisted for reconstruction. Both have regression tests.
- PostgreSQL-specific concurrency testing uses an isolated disposable test DB.
  The first host attempt could not connect because PostgreSQL has no published
  host port; the Docker-network run passed. App data was not modified.
- Real read-only plans: bill 460/document 537 = 25 planned calls, 81/81 passages,
  1.487 seconds; document 18343 = 495 planned calls, 4,852/4,852 passages,
  1,134/1,134 XML sections, 53.109 seconds. Zero omitted/duplicate assignments or
  oversized requests. These are scheduling checks, not live semantic evals.
- Other audit cases remain explicitly outside that pass: document 18340 uses
  legacy schema 1.3; document 11639 has stored XML/text misalignment. Document
  18343 still reports 53 incomplete-context chunks. No data was silently repaired.
- No AI calls, deploys, stack restarts, commits or pushes. Migrations 0027–0028
  must be applied before deploying the new API/worker code. Live model quality
  and provider latency remain unverified by this offline implementation.
- Verification evidence: full backend run 1,907 passed / 18 skipped; the final
  direct-summary checkpoint fix then passed all 47 reader work-plan/pipeline/
  large-bill regressions. PostgreSQL run: 20 passed, including cross-user
  reservation concurrency. Enhancement panel: 30 passed. TypeScript check,
  migration drift check and `git diff --check` passed. The broad SQLite run's
  skips include PostgreSQL-only cases; the dedicated PostgreSQL run did not skip
  the relevant reader tests. Other skipped tests were not claimed as executed.
