# Authorized local feature integration

Integrated on `integrate/authorized-features` in the isolated task-2 worktree. Source checkouts remain untouched. Verified common dashboard baseline: `4c5302bcbd36c19fb1d04dcb1c4adb27fe38b4f7`.

Verified source commits, in application order:

1. Telemetry `aac9aa3479daa6bae0201f606e81262b442ad716`.
2. Recommendations `f4b7e7e844779bc93f63f628ef201bce7a7ce7db`.
3. Profiles `2540b9ec8382ba0d728fb7cbe5752625c5a947e5`.
4. Hermetic ingestion replay fixture `8d6672ce566915847fb581a4202bb353a4866983`.

The first three histories each descend directly from the verified baseline; the fixture repair descends from profiles. Recommendations and profiles were fetched from their local repositories; no remote fetch/push occurred.

## Integrated behavior

BillDeck retains identity-based sponsor filters, guarded private tracking/follow behavior, recommendation-owned dialog dismissal/focus fallback, and staff telemetry. Recommendation representative names use the API filter-options current Congress and validated house/senate chamber; directory failure leaves normal public links. Bill sponsors retain each bill's historical Congress. `ProfileExperience` creates `renderActivity` inside a client boundary. The public profile-owned topic-activity endpoint calls `apps.congress.topic_activity.representative_topic_activity` and keeps its rolling window independent of profile Congress/chamber.

Removing a dialog now closes its descendants, aborts their public reads, releases scroll locking, and restores owner focus once after cleanup. Ordinary public bill dialogs survive account changes. Profile preference storage listeners react only to their own flag or a storage clear. Malformed/wrong-person activity responses fail closed instead of crashing the modal.

Dashboard cards retain default on with legacy dashboard rollback. Recommendation and profile browser preferences retain default off; telemetry preview retains default on in explicitly labeled sample mode. Wikipedia remains operator-off. Donor, verified election and exact term-start facts remain unavailable. Other pages retain their existing full-page navigation.

## Verification and evidence

Every shell invocation used RTK. Existing installed dependencies were copied/read; package manifests and lockfiles are unchanged. Commands below run from the respective backend/client/extension directories and use existing source Python environment executables where appropriate.

- Full backend: `rtk proxy env DATABASE_URL=<isolated database> <existing venv>/bin/pytest -q --junitxml=<evidence>/backend.xml`: 1,056 passed, 3 skipped, 2 deprecation warnings. PostgreSQL integration cluster is loopback port 15452, database `integration`; tests create its dedicated test database.
- Client components: `rtk proxy node node_modules/vitest/vitest.mjs run`: 126 passed across 24 files.
- Client API: `rtk proxy node --experimental-strip-types --test tests/*.test.ts`: 38 passed.
- Extension: `rtk proxy node --test tests/*.test.js`: 11 passed.
- Chromium: `rtk proxy node node_modules/@playwright/test/cli.js test --config=playwright.integration.config.ts --reporter=json`: 16 passed, 1 skipped, zero unexpected/flaky results.
- `rtk proxy node node_modules/typescript/bin/tsc --noEmit`, full client ESLint, full backend Ruff, Django check, migration drift check, changed-Python Black (36 files), optimized Next webpack build, and git whitespace check passed.
- Full-repository Black was run and reports 34 unchanged baseline files requiring formatting. They are outside this integration's changed Python set; no claim of a clean repository-wide formatting baseline.
- Independent adversarial review repaired root-descendant lifetime/focus, public dialog ownership, profile storage filtering and displayed activity-scalar guards. Final review: no actionable findings; independently reran 22 recommendation/profile tests.

Browser fixtures intercept all API traffic for nesting, Escape/Tab/Back, focus/scroll, follow/refresh/account generation changes, delayed private responses, feature rollback, and staff telemetry idempotency/readiness. Operational ingestion clicks in those tests are intercepted fixtures; no live ingestion was run. Separate real HTTP checks authenticated a local synthetic staff account and verified seven endpoints: filter options, profile, topic activity, bill recommendations, representative recommendations, telemetry and readiness. A separate browser test uses the real API to display the synthetic member profile and activity through the client wrapper. Real API evidence is `real-api.json`; fixture results are `browser.json`. Screenshots are packaged separately and visually inspected for nested dialogs, mobile profile layout, real API profile and readiness distinctions.

## Limitations and local resources

No push, deployment, shared migration, live ingestion, external enrichment, credential setup, dependencies or Extend XT changes. Telemetry migration 0008 was applied only to the isolated integration database. Data/account are explicitly synthetic; no real election, donation or vote corpus was acquired. Preview services use frontend 13302/API 18022/PostgreSQL 15452, isolated from source-agent ports.

Three backend skips: SQLite-only fallback (PostgreSQL used), opt-in synthetic performance benchmark, and Redis cross-process sharing (redis-server unavailable). Shared Redis cache behavior is not newly validated. The browser's live Wikipedia test is deliberately skipped.

Baseline production audit remains unresolved: 14 advisories (3 critical, 6 high, 4 moderate, 1 low). Source task-11 audit JSON and reachability assessment accompany this review bundle; they are existing baseline evidence, not a fresh dependency audit. No upgrades or production-readiness claim. Complete donor/election data work and dependency remediation remain separately authorized follow-ups.
