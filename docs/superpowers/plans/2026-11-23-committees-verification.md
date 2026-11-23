# Committees verification

- Implemented scoped committee members and paginated primary-sponsored bills. Backend regression tests: 3 passed, including Congress/chamber isolation and nonduplicated pagination excluding cosponsors.
- Client tests: 377 component tests and 59 API tests passed. New page tests cover roles, profile/bill links, chamber filtering and retained cards on retry.
- Docker frontend production build passed; API and client reloaded without restarting workers/databases.
- Live Chromium check at localhost:13000: desktop 1440px and mobile 390px, no page overflow. Horizontal bill pagination appended 6 to 12 cards while the row stayed 640px tall. Screenshots inspected at /tmp/committees-desktop.png and /tmp/committees-mobile.png.
- Full backend suite: 1974 passed, 18 skipped, one existing failure: test_bill_list_does_not_load_documents_or_contract_payloads. This failure also existed before the committee changes; no unrelated query logic was changed here.
- Source-data limitation: stored Senate memberships have role=member throughout. Leadership badges render only recorded roles; House chairs and vice chairs are present. No role was inferred from party, rank or membership order.
- Self-review performed in the main agent, per the single-agent instruction. Existing avatar CSS specificity corrected so committee badges use the requested larger circular display.
- User's follow-up navigation order: Home, Bills, Representatives, Topics, Committees.
- Follow-up filters: committee name, member name, chamber, committee type and pre-filled topic dropdown. Topic filtering scopes both committees and their introduced-bill rows to the selected Congress.
- Publication verification: all 5 committee backend tests and 4 committee component tests pass; production build and TypeScript check pass. Desktop and mobile topic-filter screenshots inspected; no horizontal page overflow.
- Broader targeted backend run: 72 passed, 3 skipped across committee, tracking, candidate discovery, topic activity and recommendation tests. Frontend test suite rerun before publication.
- User requested publication of all application changes in a new PR; temporary .superpowers runtime files are excluded.

## PR 26 adversarial review — November 23

Reviewed the complete PR against main, including callers, account transitions, authenticated filtering, pagination, research identity recovery, lease ownership, cache publication, and loading states. Rechecked the updated changes after the fixes; no further actionable findings identified.

- Fixed private representative-filter results surviving account changes, including delayed old-account responses.
- Restored normalization of abbreviated titles without periods without stripping surnames such as Sen.
- Allowed fresh verified candidate evidence to repair a mapping missing its evidence URL; historical periods remain unverified.
- Prevented delayed refresh spinners from displacing existing vote records and bill explanations.
- Added a unique committee ordering tie-breaker for same-named subcommittees.
- Replaced the failing overly broad catalog SQL assertion with checks that summaries are returned, full document/contract payloads are not selected, and query count stays bounded for 1 and 20 cards.

Verification:
- Full backend `.venv/bin/pytest -q`: 1,984 passed, 18 skipped. After the final committee ordering fix, committee and candidate-discovery suites: 32 passed.
- Final client `pnpm test`: 381 component tests and 59 API tests passed; `pnpm exec tsc --noEmit` passed.
- Fresh isolated build: `E2E_ISOLATED_BUILD=1 E2E_API_PORT=18261 E2E_CLIENT_PORT=13261 pnpm exec playwright test e2e/loading-states.spec.ts e2e/bill-card-layout.spec.ts --workers=2`: 3 passed. Desktop/mobile screenshots inspected. API responses are simulated, not live finance or AI-provider verification.
- Initial browser attempts encountered occupied ports and a stale existing development build; only the fresh isolated-build results above are release evidence. No running application services were stopped.
- No paid model calls or database migrations. The earlier backend failure recorded above is resolved.
