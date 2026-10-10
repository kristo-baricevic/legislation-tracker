# Final local readiness review — October 10, 2026

Reviewed combined head: `ee533dda60645a36b8238dadffb1623df6129347`, parent security-only `be371f8db70fe01694ad65384d8a66f438dac978`, parent integration `271a9f860c97310ca3402c7254889000cdbee800`. Original layout `c5251a7d01614edc9f64aa32e9c7e1365ee8f7f4` remains preserved. Final review uses task-2/final-review, branch integration/final-readiness, a separate local checkout sharing read-only objects with task-11. Source worktrees are unchanged.

## Review outcome and source repair

Fresh independent review found no actionable combined application defects. Reviewer ran 40 focused component tests across profiles, recommendations, generation guards and telemetry. Verified documented flag defaults, sample labeling, staff-only explicit ingestion with retry keys/backend claim uniqueness, readiness separated from historical gaps, stale basis invalidation, nested teardown/focus/scroll, private generation rejection, and visible donor/election/coverage limitations.

The broader browser harness initially passed 17 tests and skipped one, but nine older tests failed because they addressed hardcoded API port18000. After isolated-port support, the seeded run exposed two stale reader expectations and a cold catalog gate. Repairs: four older tests honor E2E_API_URL; Playwright sets matching API/client origins from validated E2E_API_PORT/E2E_CLIENT_PORT (defaults remain18000/13100); seed adds an explicitly synthetic profile and dated/tagged bill required by the integration test; reader test verifies navigation to the full-text document page and a real text API200, while key-term pagination checks use current request parameters.

The real profile seam explicitly reads the actual directory, resolves its synthetic member ID, and verifies an actual catalog200 before opening the UI. Both catalog and UI reads are real API requests; no interception in that test. Prewarming avoids deliberate concurrent cold-catalog503s during React development duplicate reads. It is success-path coverage, not a cold-concurrency UX claim. Existing cold-gate failures display an honest unavailable message and Retry activity. Independent review cleared the final harness diff.

## Evidence and gates

Fresh final-review checks:126 component tests/24files;38 Node API tests;26 browser tests passed,1 optional live Wikipedia skip,0 failures/flaky; TypeScript and full client ESLint; seed Ruff and Black; whitespace; unchanged default Turbopack production build (task-2/evidence/final-build.log). Browser evidence: task-2/evidence/final-browser-repaired.json. Synthetic SQLite database is task-2/final-review-e2e.sqlite3; API18042, frontend13402, fake local LLM provider and filesystem Celery broker. Browser-managed services stop after the run. Initial failed runs remain in the evidence folder, distinguished from the final successful run.

Inherited verified combined/security gates (not rerun as unchanged application/backend/dependency surfaces):1056 PostgreSQL backend tests passed/3 skips;11 extension tests; Django check/migration drift/full Ruff; macOS and Linux/arm64 Alpine default Turbopack builds/nativeSWC/sharp/real image optimizer smoke. Full backend Black has34 unchanged baseline files. Backend skips are SQLite fallback, opt-in benchmark, and unavailable Redis cross-process check. No shared migration, ingestion, external credential, push or deployment happened.

Current real synthetic profile screenshots are task-2/final-review/legislation-tracker-client/test-results/profile-prioritized-real-api-desktop.png and profile-prioritized-real-api-mobile.png. Fixture screenshots are separately recognizable from test fixtures. Library upload remains unavailable: helper exit1, `library upload failed: Library prepare_uploads is not available`; no alternate transfer route attempted.

## Dependency reachability and proposed scoped repairs

Security agent audit JSON at task-11/security-evidence/audit-production.json reports0 production findings. Full audit reports31 advisories:3critical,18high,8moderate,2low across9 package families. This review inspected that recorded audit and actual installed/source call paths; it did not perform a new registry audit or change dependencies. A zero production-only audit is not a full tooling/build security clearance.

| Family | Actual boundary and prerequisite | Proposed bounded follow-up |
| --- | --- | --- |
| Vite6.2.7 (7 advisories) | Used by Vitest; app dev/build use Next. No exposed Vite host configured. Network file-read paths need reachable dev server/WebSocket; some findings are Windows-specific. | Same-major Vite6.4.3 floor, frozen lock and full126 component/38API/lint/type/build/browser checks. |
| Vitest3.2.4 (critical UI + moderate redirect) and @vitest/mocker (moderate redirect) | jsdom CLI tests; no UI/API host/browser mode or public mocker/interceptor plugin configured/imported. Current exposed-server prerequisite absent; do not expose test servers. | Vitest3.2.6 can address UI advisory; complete redirect fix requires reviewed Vitest4.1.11 migration with companion packages. Separate compatibility plan before major change. |
| Tinypool1.1.1 (2 critical) | Vitest does call pool.run(data,{name,channel}) without own filename: vulnerable gadget is reachable in tooling. Exploit requires prior parent-process prototype pollution; none identified in project application/test configuration. Tests/repo code already execute in tooling trust boundary. Not proven categorically unexploitable. | Prefer supported Vitest migration removing/updating affected pool. Do not force Tinypool2.1.2 beneath Vitest3 without compatibility proof. |
| PostCSS8.5.15 (2) | Actual Tailwind and Vite resolve vulnerable version; therefore build/test reachable despite dev classification. Source-map read needs attacker-controlled CSS/metadata; build uses tracked CSS, no runtime user CSS compilation. Patched8.5.23 also installed for Next. | Scoped8.5.23 resolution within existing major; validate Tailwind output/build and source-map behavior. |
| Nanoid3.3.15 (2) | Actual PostCSS uses non-secure nanoid(6), fixed positive size; no project custom/negative/zero size call. | Scoped3.3.18 resolution alongside PostCSS; verify callers. |
| brace-expansion1.1.15/5.0.6 (12), braces3.0.3 (1) | ESLint/minimatch/TypeScript parser and Next lint fast-glob paths. Hostile patterns can exhaust tooling; no user-request path passes patterns to these packages. Untrusted repository/config lint remains relevant. | Same-major brace-expansion1.1.21/5.0.12 and braces3.0.4 resolutions; lint all source and glob compatibility checks. |
| js-yaml4.3.0 (2) | ESLint legacy configuration loader. Project uses tracked flat JS config; hostile YAML needed for merge/omap exhaustion. | Same-major4.3.2 resolution; ESLint config-load/lint validation. |

Advisory sources inspected: https://github.com/advisories/GHSA-5xrq-8626-4rwp (Vitest UI), https://github.com/advisories/GHSA-82fw-gwwq-j7x9 (redirect mock), https://github.com/advisories/GHSA-85c8-ppgw-ccpr (Tinypool run options), https://github.com/advisories/GHSA-p9ff-h696-f583 (Vite WebSocket). Remaining versions/floors come from the recorded audit. Proposals are unapplied; each needs fresh audit/lock validation before approval. No broad upgrade or technology switch is implied.

## Remaining real-source requirements

Election and donor fields remain unavailable. The bounded task-11 pilot deliberately did not import its standalone public House target. Its accessible directory observations do not establish the three requested date facts or complete donor ranking. Certified Vermont winning-result PDF links returned403; no bypass is authorized.

To populate dates: obtain official certified winning results for first and most recent election independently, verify selected Congress term-start source separately, and preserve identity/crosswalk/source/retrieval/precision for each fact. Election event date, first service, certification and oath dates are distinct; none substitutes automatically.

To populate verified PAC donors: inspect underlying official Form1/Form2 registration and2024 candidate/committee linkage; select one complete reporting period and final superseding amendment chain; retrieve/reconcile complete relevant11(c)/20(c) contribution/refund schedules; verify recipient and donor PAC committee types/identities within approved bounds; exclude individuals/party transfers/loans/outside spending; deduplicate economic events and resolve memo entries; disclose aggregation/currency/period and separately label refunds. The accessible2024 directory only covers through July24,2024 and is insufficient. No personal donor records, real imports or rankings were produced.

## Readiness boundary

Ready for the parent's local source/UI once-over with honest unavailable states and documented rollback flags. Production readiness remains unclaimed: development advisories and unchanged formatting debt remain; live provider/Redis performance/source completeness/deployment checks are outside this authorized run.
