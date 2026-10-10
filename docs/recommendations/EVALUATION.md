# Verification and evaluation limits

Recorded on 2026-10-10 against the recommendation branch and verified dashboard baseline. No production data, shared database, ingestion service, external political profile, or production deployment was used. Test outcomes below apply to this branch before profile/telemetry integration.

## Independent review

An independent adversarial reviewer assessed the proposals before technology approval/implementation. Repairs made the sparse-data policy, exact scoring, cache bounds, public/private boundary, missing-date handling, and neutral explanation contract concrete. The approved specifications retain the resulting requirements.

A fresh independent code reviewer inspected the implementation and found seven backend issues, all repaired: stale snapshot-slot continuity, API error/cache failure handling, foreign expired cursor ownership, latest uncertain passage selection, uncertain-only passage topics, complete cross-chamber history labeling, and PostgreSQL nonfinite topic confidence. Subsequent reviews also checked January 3 boundaries, account-generation guards, abandoned transition recovery, shared refresh cancellation, recommendation dialog ownership, disappearing follow-control focus, unique action names, refresh controls, and the valid topic-filter URL. Final report: **no remaining actionable findings in recommendation-owned source**. Independent final checks passed 18 component/generation tests, 6 API/auth tests, and 15 topic-activity tests. The reviewer edited no implementation files.

Native browser QA caught a focus defect: disabling a pending followed-card button made Chromium move focus to the document body before row invalidation could detect ownership. The row now records the focus intent before disabling the button and restores the persistent heading. The browser assertions were retained and passed after repair.

## Verification ledger

Every command below was executed through RTK. Backend commands used a new task-owned PostgreSQL 16.13 cluster on isolated loopback port 58468 and an isolated `recommendations_task10` database; it did not use the telemetry database or shared services. Client browser checks used isolated port 60350, never telemetry port 13280 or Extend XT ports. Python/frontend dependencies were the existing lockfile dependencies; there were no dependency declarations or lockfile changes.

| Check | Actual result | Scope |
| --- | --- | --- |
| `.venv/bin/python -m pytest -q --tb=short --create-db -k 'not test_replayed_manual_bill_work_fulfills_the_original_tracking_request'` with isolated `DATABASE_URL` | **981 passed, 2 skipped, 1 deselected** | Fresh PostgreSQL aggregate; includes 45 recommendation/activity cases. Two existing Django 6 deprecation warnings. |
| Synthetic benchmark below | **1 passed** | PostgreSQL query counts, local timing budgets, compact catalog bytes, Python allocation peak, EXPLAIN ANALYZE BUFFERS. |
| `node_modules/.bin/vitest run` | **104 passed, 21 files** | Full existing client component suite, including recommendation states, generation regressions, and visible/unfocusable fallback focus targets. |
| `node --disable-warning=ExperimentalWarning --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --experimental-strip-types --test 'tests/*.test.ts'` | **35 passed** | Full client Node API/contract suite. |
| `node_modules/.bin/eslint .` | Exit 0 | Whole client. |
| `node_modules/.bin/tsc --noEmit` | Exit 0 | Whole client. |
| `node_modules/.bin/next build` | Exit 0 | Next 16.3.1 production build, existing font fetch. |
| `env RECOMMENDATIONS_CLIENT_PORT=60350 node_modules/.bin/playwright test --config=playwright.recommendations.config.ts` | **2 passed** | Native Chromium fixture-backed dashboard QA. |
| Ruff on nine recommendation/activity Python files; Black `--check` on the same files | Exit 0 | New backend source/tests. |
| Django `check`; `makemigrations --check --dry-run` | No issues; no changes detected | Existing isolated test settings/database. |
| Existing extension Node tests | **11 passed** | Unchanged extension contract regression coverage. |

The deselected **preexisting** test is `apps/ingestion/tests/test_views.py::test_replayed_manual_bill_work_fulfills_the_original_tracking_request`. It mocks `bill_detail`, leaves a `bill_summaries` upstream read unmocked, and fails with 403 without a Congress API key. It is not a recommendation failure; the parent/telemetry owner must make that test fixture hermetic and rerun the complete aggregate in integration. No production credentials were requested or used to mask it.

An earlier aggregate run with `--reuse-db` failed four baseline tests after focused transactional tests flushed migration-seeded canonical topics and the BillActivityClock. Rerunning against `--create-db` restored seed data and produced the aggregate result above. The benchmark and reported aggregate use freshly constructed test data, not that stale reused fixture state.

Coverage includes sparse/no follows, unsupported broad follows, no matches, crossover ranking, unrelated candidates, duplicate tags/follows, missing/NaN/infinite metadata, withdrawn cosponsors, deterministic ties, own-follow exclusion, stable page snapshots, cursor owner/expiry, changed follows, deleted candidates, cache/database failures, private error headers, real PostgreSQL concurrent follow changes, rolling/calendar/January 3 boundaries, raw/grouped thresholds, multi-tag fractions, unknown service exposure, latest uncertain passage and cross-chamber records, current candidate/former reference rules, and separate public activity rendering.

Client regressions cover A→B stale responses and 401 replay, CSRF generation changes before POST, abort before replay, interest invalidation, cross-tab clearing, focus during login, abandoned transition recovery, and shared refresh where an aborted caller does not cancel another current caller. Three final focus helper cases verify visible-heading priority, hidden/missing targets, and continuation after a visible but unfocusable target; independent review reran all three. Browser tests cover default-off opt-in persistence, factual explanations, shared baseline bill modal/Escape focus, persisted follow fixture and reload, desktop/tablet/mobile overflow, disappearing card focus, 503/retry, refresh/no matches, logout clearing, preference rollback, and main dashboard rollback.

Browser API calls are intercepted deterministic fixtures; PostgreSQL API tests establish actual backend behavior separately. The populated representative adapter and rolling public activity are component-tested. **Combined profile/activity route rendering and nested dialog fallback browser tests still belong to final parent integration**, since this branch does not copy another agent's StackDialog/ProfileProvider/BillDeckModal.

## Synthetic performance

Run with a task-owned empty PostgreSQL database and the existing backend test settings:

```sh
rtk proxy env DATABASE_URL=postgres://kristo@127.0.0.1:58468/recommendations_task10 RUN_RECOMMENDATION_BENCHMARK=1 .venv/bin/python -m pytest -q -s --create-db apps/accounts/tests/test_recommendations_performance.py
```

The opt-in test creates 10,000 federal bills, 500 representatives, 30 topics, 30,000 usable topic edges, 30,000 cosponsor edges, 100 passage rolls and 40,000 vote records. It runs ANALYZE before measurement. Default aggregate runs skip it. Results are written to [synthetic-performance.json](synthetic-performance.json), with the actual [bill candidate PostgreSQL plan](bill-candidate-explain.json).

| Request/work | Milliseconds | Data queries | Transaction/control queries |
| --- | ---: | ---: | ---: |
| First route/import plus initial bill ranking | 505.06 | 7 | 3 |
| Fresh initial bill ranking after import | 276.35 | 7 | 3 |
| Stable bill continuation | 25.35 | 5 | 3 |
| Cold public activity catalog | 1617.45 | 8 | 11 |
| Cached representative ranking | 220.14 | 2 | 3 |

The steady initial request creates a **new** ranking; it is not served from the preceding private snapshot. The first request separately includes one-time Django URL/module imports. Local test budgets are 500/150/2000/250 ms respectively for steady initial/continuation/cold activity/cached representatives; query ceilings are 15/8/12/5. These single local samples are not production percentiles, throughput, quality scores, or a before/after improvement claim.

The catalog is **15,130,625 bytes** of compact JSON, below its 16 MiB cap. Rebuilding under `tracemalloc` peaked at **127,017,084 bytes** (~121.1 MiB) of Python allocations. This is not process RSS or a guaranteed production memory bound. A larger/richer corpus may exceed the byte limit, rebuilding resource budget, or timeout and intentionally return 503. Activity examples are bounded, but source data are streamed and exact evidence is computed before serialization; corpus-scale memory remains a limitation to evaluate before rollout. Existing public cache backend configuration controls shared reuse and gate semantics.

## Quality evaluation still required

Correctness, privacy, explanations, and bounded local cost have evidence. Discovery usefulness has not been measured. There is no held-out user engagement or representative political-preference target. Candidate limits, facet weights, evidence thresholds, title grouping, and MMR tradeoffs are provisional policy.

A future consented evaluation should compare this interpretable baseline against the same baseline without MMR; measure relevant catalog coverage, duplicates/repetition, explanation accuracy, useful discovery feedback and subgroup exposure to sparse metadata; report cold-start and ingestion-coverage strata separately. Collaborative/item-to-item approaches should only be reconsidered after adequate behavior density, explicit privacy approval, and an evaluation design exist. Vote agreement, ideology inference, party preference, and persuasion are outside the objective.

## Visual evidence

Fixture-backed screenshots are [desktop](recommendations-desktop.png), [tablet](recommendations-tablet.png), and [mobile](recommendations-mobile.png). The mobile capture was visually inspected; no page overflow or unreadable card content was observed. Test names and exact native focus assertions are in [recommendations.spec.ts](../../legislation-tracker-client/e2e/recommendations.spec.ts).
