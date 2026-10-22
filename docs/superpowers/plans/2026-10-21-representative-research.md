# Representative Research Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans, task by task, in the main agent. No subagents. This document is a plan, not authorization to start implementation or external research jobs.

**Goal:** Give every federal representative an on-demand, persistent research profile containing a readable biography, portrait, campaign contributors, and evidence-backed connections to legislative topics.

**Architecture:** A Research button creates durable background work. Source adapters fetch authoritative records, normalize them into PostgreSQL, and publish versioned research snapshots. Pages read saved data only; an explorable relationship view traverses contributions, representatives, bills, and topics without requiring a graph database.

**Tech Stack:** Existing Django/DRF, PostgreSQL, Celery/Redis, object storage, Next.js/React, pytest, component tests, and Playwright.

**Spec:** The user request in this conversation, with the proposed product contract below. Source selection, federal-first scope, authenticated triggering, and default cycle are recommendations, not previously approved requirements.

## Product contract

### What a reader sees

- The existing representative page and modal retain their current styling and gain a shared Research control. The list offers the same action without forcing navigation.
- Before research: existing official facts and any existing portrait remain visible; missing biography/donor information says “Not researched yet,” not “No donors.”
- On click: “Researching…” with separate biography, photo, and campaign-finance states. Navigation or reload does not lose the job. Successful sections appear even if another source fails.
- After research: a portrait, a short factual biography, a cycle-selectable contributor table, source links, and “Last researched” date. The control becomes “Refresh research.” Saved results do not expire or disappear because a cache TTL elapsed.
- Biography: 2–4 complete, readable sentences, sourced to verified identity. Start with official member/service facts and a clean source excerpt; no LLM or user AI key required. Do not invent education, career history, motivations, or policy positions. When only service facts are available, say so in source details.
- Contributors: name, type, reported contribution amount, recipient committee, period, and source. Show contributions and refunds separately; only show a net amount where supported reconciliation exists. Explicitly distinguish “No matching records,” “Not researched,” “Partial,” and “Source unavailable.”
- A “Connections” section opens an expandable donor → representative → bill → topic view. Every connection opens its evidence. Include an accessible list/table equivalent. No separate donors page in this release.
- Do not place raw JSON, technical logs, or an enormous graph above the biography. Source details and diagnostics are secondary.

### Scope and interpretation

Start with federal House and Senate members already in the database. Default finance scope is the current two-year FEC reporting period, clearly labeled and selectable; it is not the same thing as a Congress or a senator's six-year election campaign. Historical periods are researched on request, not automatically fetched for every member.

“Donor” means a disclosed contributor to a verified authorized campaign committee in the selected scope. Candidate self-funding, loans, other receipts, transfers, and refunds have separate classifications. Leadership PACs, party committees, independent expenditures, and untraceable ultimate funding are not silently rolled into direct campaign contributions. Outside spending is a future distinct relationship, not a donation to a representative.

Employer names reported by individual contributors do not make the employer the donor. PACs remain separate from associated businesses. Unitemized money has no inferred donor identities. Unresolved people remain separate reported identities rather than being merged by name.

The graph means “this contributor gave to a campaign whose representative acted on these bills.” It does **not** establish that the contributor supports each topic, paid for a vote, or caused a legislative outcome. A yes/no vote on a bill is not support/opposition to every topic in that bill. Use “Connected legislative activity,” not “Issues this donor supports.”

## Existing code to build on

- `legislation-tracker-backend/apps/congress/models.py`: Representative already has `bioguide_id`, `official_website_url`, and `image_url`; service terms, committees, cosponsorships, and vote records exist.
- `apps/congress/biography.py`: identity-checked Wikimedia excerpt fetching exists but stores results in cache. Preserve its identity checks and attribution; move network work behind Research and persist accepted results.
- `apps/congress/views.py`: public profile, biography, and topic-activity actions exist. Its viewset explicitly disables authentication; authenticated research writes need separate views or explicitly configured action authentication, not merely an IsAuthenticated permission added to the existing class.
- `apps/congress/topic_activity.py`: already distinguishes sponsorship, active cosponsorship, and passage-vote evidence. Reuse semantics, not recommendation scores or the short-lived catalog as the financial graph's source of truth.
- `apps/ingestion/work_queue.py`: persistent work, deduplication, and dispatch patterns exist. Extend these rather than creating an in-memory scraping queue.
- Frontend entry points: `app/representatives/page.tsx`, `app/representatives/[id]/page.tsx`, `app/components/LegislatorProfileModal.tsx`, and `app/components/LegislatorName.tsx`.

## Sources and acquisition

1. **Campaign finance:** OpenFEC API for candidate identities, authorized committees, processed contributions, refunds, and committee totals. Obtain a server-side `FEC_API_KEY`; never reuse an OpenAI key or expose source keys in the browser. Confirm exact endpoint/filter/cursor semantics against fixtures before implementing normalization. [Official API documentation](https://api.open.fec.gov/developers/).
2. **Portrait and member facts:** existing Congress.gov member ingestion and its depiction data first. Preserve attribution and verify reuse terms before storing a portrait; do not treat every government-hosted image as automatically unrestricted. [Official member endpoint documentation](https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/MemberEndpoint.md).
3. **Biography:** official Bioguide/member website when accessible, then the existing exact-Bioguide-ID Wikimedia adapter. Preserve source URL, revision/hash, attribution, and applicable license. Official biography pages may be promotional; use factual extracts, not unsupported praise.
4. **Scraping:** a bounded adapter for verified official biography pages only when structured data is insufficient. Respect source terms and robots policy; no CAPTCHA, login, paywall, or access-control bypass. A denied page is an explicit unavailable source, not an invitation to scrape mirrors.

There is no verified universal Bioguide-to-FEC mapping in the current app. Candidate search is discovery, not identity proof: match office, state, historical district, name/aliases, and applicable election periods. Record evidence for accepted mappings. Ambiguous matches require staff resolution before finance publication. Support multiple candidate IDs over a representative's career.

**Individual contributor release prerequisite:** document the intended use and obtain appropriate review of FEC sale/use restrictions before enabling individual-level publication or exports. This plan does not conclude that the app automatically qualifies for an exception. Committee data and source-provided aggregate figures can be developed independently. Do not collect contact details or provide donor outreach tools. [FEC guidance](https://www.fec.gov/updates/sale-or-use-contributor-information/).

## Global constraints

- No paid LLM calls; no donors page, newsletter, RSS, or GitHub Actions work.
- No stack shutdown/restart, full-database backfill, or automatic all-member research during implementation without separate authorization.
- Shared public research records; signed-in users may trigger research, not staff only. Staff-only identity resolution and dead-letter replay.
- Every displayed biography claim, photo, money row, and graph edge has provenance. No arbitrary user-submitted scrape URLs.
- Persist data indefinitely under an explicit retention policy; caches accelerate reads but are not authoritative. Manual refresh is the initial freshness policy.
- Provider-budget controls must queue work and explain the wait, not silently disable the Research button. Honor actual provider backoff and configured deployment limits.
- Use RTK for all shell commands. No live upstream calls in routine tests.

## Review focus

1. Same-name people, changed districts, and multiple campaign committees must not create false financial connections — tasks 1/2.
2. Amended filings, conduit/memo entries, and refunds must not double-count money — task 3.
3. Crash or source outage halfway through pagination must not replace complete results with an apparently complete subset — task 4.
4. Shared donors, overlapping bill topics, and procedural votes must not manufacture issue endorsements or attributed dollars — task 6.
5. Modal closure, refresh failure, and a worker disappearing must not leave controls stuck or erase saved results — tasks 4/5/7.

## Data model

Add an `apps.research` Django app for orchestration/provenance and `apps.campaign_finance` for reusable finance entities. Keep Representative as the existing stable identity.

| Model | Responsibility / identity |
| --- | --- |
| ResearchRun | Representative, requested scope/period, requester, generation, status, per-section state, timestamps, heartbeat, sanitized failure, and saved-result references. One active run per representative/period; concurrent callers join it. |
| ResearchSource | Provider, canonical public URL, fetched time, source revision/hash, parser version, attribution/license, and restricted object reference for necessary evidence. Never persist API keys in URLs. |
| RepresentativeBiography | Versioned accepted text, representative, source FK, fact/excerpt evidence, and publication state. Preserve old valid revisions. |
| RepresentativePortrait | Source, object key, content hash, MIME/dimensions, attribution/license, and active revision. Existing image_url remains a compatibility fallback. |
| CandidateIdentity | FEC candidate ID (unique), office and source facts. |
| RepresentativeCandidate | Representative/candidate relation, applicable periods, verification state/method and evidence; unique pair, never a name-only join. |
| CampaignCommittee / CandidateCommittee | Unique FEC committee ID; candidate relationship, designation, applicable periods and source evidence. No assumption that every linked committee is authorized. |
| Contributor / ContributorIdentity | Stable internal entity plus source identities. FEC committee IDs can support cross-recipient joins; individuals without durable identifiers remain source-scoped/unresolved unless verified. Store merge decisions with evidence and allow reversal. |
| FinanceSnapshot | Immutable published scope: representative, period, included verified committees, provider cutoff/coverage, normalization version, and totals. Active pointer advances only after validation. |
| FinanceTransaction | Snapshot membership, raw-record/revision identity, recipient, contributor if resolved, signed Decimal USD amount, date, type, election designation, filing/transaction IDs, memo/conduit flags, effective/superseded status and source. Raw revisions are separate from effective economic transactions. |
| FinanceResearchCheckpoint | Run/source/committee/period/filter fingerprint, cursor, processed-page hashes and completion state; atomically committed with each page's records. |

Add DB indexes for representative/period, recipient/period, contributor/period, and source record/revision. Keep new migrations additive. Do not renumber representatives, modify historical terms, or duplicate the existing BillTopic and VoteRecord models. Snapshot membership can use a join table so unchanged transactions are not recopied on every refresh.

Raw evidence must be private, minimized, and access-controlled. Strip addresses, contact fields and secrets before persistence when unnecessary. Source links and filing IDs provide auditability without serving whole contributor payloads to clients. Define deletion/retention rules for restricted artifacts before release.

## API contract

- `POST /api/representatives/{id}/research/` accepts `{period: 2026}`: authenticated/CSRF-protected; returns `202` with a durable run ID or the existing active run. Server selects sources; no URL/model/key fields.
- `GET /api/representatives/{id}/research/` returns saved bio/photo, active snapshot references and latest run/section states. No network fetching.
- `GET /api/representatives/{id}/research-runs/{run_id}/` returns progress, next retry time, safe errors, and terminal state; enforce representative/run ownership of the route, redact requester details.
- `GET /api/representatives/{id}/contributors/?period=2026&snapshot=...&cursor=...` returns stable snapshot pagination, classification, sources and coverage. Only allow documented filters/sorts.
- `GET /api/representatives/{id}/connections/?period=2026&snapshot=...` returns typed nodes/edges with evidence references and expansion cursors. Separate finance period from legislative date/Congress filters; display both.
- Existing biography GET becomes a compatibility projection of DB-backed data. Do not trigger research on page open or GET.

Shared frontend types: `ResearchState = not_started | queued | running | succeeded | partial | failed | needs_review`; per-section status additionally supports `not_available`. No-record findings are outcomes with coverage, not generic errors. A failed refresh returns previous saved data plus the failure state.

## Implementation tasks

Paths below are relative to the repo. Backend paths abbreviate `legislation-tracker-backend/` as **B/** and frontend paths abbreviate `legislation-tracker-client/` as **F/**.

### 1. Persist research and campaign identities

**Files:** create `B/apps/research/{models,services,admin}.py`, `B/apps/campaign_finance/{models,identity,admin}.py`, app configs/migrations, `B/apps/research/tests/test_models.py`, `B/apps/campaign_finance/tests/test_identity.py`; register apps in settings.

**Interfaces:** `resolve_candidate(representative_id: int, period: int) -> IdentityResolution` with `verified`, `needs_review`, or `not_found`; `request_research(representative_id: int, period: int, user_id: int) -> ResearchRun`.

- [ ] Write failing tests for multiple candidate IDs, same-name candidates, district changes, unverified exclusion, reversible identity correction, and concurrent run uniqueness.
- [ ] Run focused pytest modules and confirm failures are missing behavior, not environment failures.
- [ ] Implement additive models/constraints and evidence-backed resolution; ambiguous candidates never attach automatically. A changed identity invalidates affected active finance snapshots pending recomputation.
- [ ] Run model/identity tests on PostgreSQL for constraints/concurrency and forward/reverse migration tests against disposable data.
- [ ] Commit this bounded persistence change.

### 2. Fetch and store biography and portrait

**Files:** create `B/apps/research/{sources,biographies,portraits}.py` and tests `test_sources.py`, `test_biographies.py`, `test_portraits.py`; adapt `B/apps/congress/biography.py` without deleting its proven identity checks.

**Interfaces:** `research_biography(run_id: UUID) -> SectionResult`; `research_portrait(run_id: UUID) -> SectionResult`; `SectionResult` carries state, saved revision ID, source IDs, safe error/retry data.

- [ ] Add fixtures for official facts, identity-matched excerpts, wrong-person pages, missing portraits, HTML changes, attribution, malicious redirects, oversized images and compressed responses.
- [ ] Run these tests to establish failures.
- [ ] Implement deterministic factual synopsis/excerpt generation and provenance storage. Output complete sentences; retain full source separately. Scraping cleans scripts/navigation and never renders raw HTML.
- [ ] Implement HTTPS/source allowlists, private/loopback/link-local destination blocking including redirects and DNS rebinding protection, fixed source adapters, time/byte/decompression limits, image decode/dimension checks, and safe raster output. No arbitrary browser image proxy or SVG passthrough.
- [ ] Verify missing/denied sources preserve valid previous data, and copying/rehosting respects recorded licensing decisions. Run focused tests; commit.

### 3. Normalize finance records correctly

**Files:** create `B/apps/campaign_finance/{fec_client,normalization,snapshots}.py`, fixture directory and `tests/{test_fec_client,test_normalization,test_snapshots}.py`; configure FEC server credentials in env example and deployment documentation without secrets.

**Interfaces:** `fetch_finance_page(scope: FinanceScope, cursor: dict | None) -> FinancePage`; `normalize_finance_records(records: list[dict]) -> NormalizedPage`; `validate_finance_snapshot(snapshot_id: UUID) -> ValidationReport`.

- [ ] Pin official API response fixtures and document processed Schedule A identity/amendment semantics, authorized-committee linkage, refund source semantics, and endpoint-specific cursor contract. Do not assume `transaction_id` alone is globally unique or combine raw and processed feeds without reconciliation.
- [ ] Write failing tests: duplicate pages, amendment replacing $100 with $150 (result $150, not $250), deleted/replaced transactions, memo records, conduit/earmarked pairs, $100 receipt plus supported $25 refund, ambiguous refund matching, employer vs contributor, loans/self-funding, unitemized totals, and source totals with differing reporting cutoffs.
- [ ] Implement normalization with Decimal, source-specific revision identity, explicit effective-transaction rules and excluded-record reasons. Never guess away uncertain double-counting; quarantine ambiguous records and mark coverage partial.
- [ ] Reconcile comparable categories and identical committee/date scopes against official totals. Do not equate all receipts with donations; mismatches prevent a “complete” label and remain inspectable.
- [ ] Run all finance tests and verify fixture sums by hand; commit. No live bulk ingestion yet.

### 4. Durable research execution and refresh

**Files:** create `B/apps/research/{tasks,views,serializers,urls}.py`, `tests/{test_jobs,test_api}.py`; extend `B/apps/ingestion/{models,work_queue,tasks}.py` at existing dispatch integration points; register URLs and worker routing.

**Interfaces:** tasks consume run IDs; `publish_finance_snapshot(run_id: UUID) -> UUID` atomically changes the active snapshot only after validation. A run consists of independent bio, portrait, identity and finance stages; identity gates finance, not biography.

- [ ] Write failure-injection tests for broker outage after DB commit, duplicate delivery, concurrent clicks, crash after page persistence, expired lease, old worker finishing after replacement, source 429/5xx, missing credentials, and failed refresh with prior valid results.
- [ ] Implement persisted tasks/checkpoints, leased claims with fencing tokens, transactional page writes/cursor updates, on-commit dispatch and periodic recovery. Reuse existing durable queue recovery. Give research a distinct route so it cannot starve bill completion.
- [ ] Honor Retry-After; retry transient failures with bounded backoff, classify permanent failures, and expose terminal state/replay. Large runs continue in bounded pages without silently declaring a truncated collection complete.
- [ ] Refresh whole selected reporting periods initially to capture old amendments; no timestamp-only incremental shortcut. Reuse unchanged content hashes. Record the provider observation window, and report partial/inconsistent results if the upstream changed mid-run rather than claiming an atomic upstream snapshot.
- [ ] Implement API contracts with actual authentication configured, CSRF tests, anonymous read permissions, safe error responses, active-job joining and provider-budget queue states.
- [ ] Run job/API/PostgreSQL concurrency tests; commit.

### 5. Integrate readable research UI

**Files:** create `F/app/components/{RepresentativeResearch,RepresentativeContributors}.tsx`, `F/lib/representative-research.ts`; modify representative page/detail and `LegislatorProfileModal.tsx`; add `F/tests/components/representative-research.test.tsx` and API-client tests.

**Interfaces:** shared components accept `representativeId` and selected `period`; API client exposes `getResearch`, `startResearch`, `getRun`, and `getContributors` against task 4 contracts.

- [ ] Write behavioral tests for click-to-start, running state, reload recovery, retry after failure, previously saved data during refresh, needs-review identity, unavailable source, and anonymous sign-in prompt.
- [ ] Add compact Research/Refresh control, portrait fallback, biography, source details, cycle selector, sortable contributor rows and stable pagination. Keep existing official fields working. Never claim missing source data means zero funding.
- [ ] Poll only active runs; stop on terminal states/unmount, abort outdated requests, and ignore results for the previous representative or period. Refresh saved sections after publication. Different tabs may join the same job.
- [ ] Replace modal/page automatic biography network fetch behavior with saved reads. Preserve Wikipedia attribution wherever its text is shown.
- [ ] Run component/API tests and `rtk proxy pnpm typecheck` from F; commit.

### 6. Build the evidence-backed connections view

**Files:** create `B/apps/campaign_finance/{connections,connection_serializers}.py`, `tests/test_connections.py`; create `F/app/components/RepresentativeConnections.tsx` and `F/tests/components/representative-connections.test.tsx`; integrate API route and representative detail/modal expansion.

**Interfaces:** `get_connections(representative_id: int, finance_snapshot_id: UUID, legislative_scope: LegislativeScope, cursor: str | None) -> ConnectionPage`.

- [ ] Write fixtures with shared committee donors, unresolved same-name individuals, overlapping topics, withdrawn cosponsors, multiple votes including procedural votes, opposing passage votes, and contributions outside the legislative time window.
- [ ] Build relational projection with typed edges: contributed-to committee, authorized-for candidate/representative, sponsored, cosponsored, recorded-vote, and bill-tagged-topic. Preserve withdrawal/date and vote question/direction. No stored donor-to-topic endorsement edge and no inferred per-topic dollar allocation.
- [ ] Implement query bounds with visible pagination/expansion: initial 20 contributors and first 10 distinct bills per expanded representative, always with totals and “Load more.” These are display bounds, not ingestion caps. Cache by finance snapshot + legislative revision/filter identity; invalidate on contribution, identity, vote, cosponsorship or topic changes, not an arbitrary five-minute timer.
- [ ] Render an explicit, expandable node-link view with semantic edge labels and a synchronized keyboard-accessible list. Start representative-centered; expand shared verified contributors to other researched representatives. Mark unresearched branches rather than interpreting absence as no relationship.
- [ ] Verify every displayed edge resolves to financial/source or bill/vote evidence, repeated relations do not inflate counts, and non-passage votes are never labeled passage support. Run backend/component tests and typecheck; commit.

### 7. End-to-end acceptance and operator handoff

**Files:** create `F/e2e/representative-research.spec.ts`, `B/apps/research/management/commands/research_representative.py`, `B/docs/REPRESENTATIVE_RESEARCH.md`; update env/deployment docs and existing representative tests.

- [ ] Add an isolated full-path test with recorded HTTP fixtures: signed-in Research click → durable job → bio/photo + finance snapshot → rendered rows → contribution evidence → representative/bill/topic connection. Mock only upstream providers, not the app's own API or job persistence.
- [ ] Verify three profiles: House member, senator with multiple candidate/committee relationships, and identity/source-unavailable member. Include worker interruption and resume. Run without touching live production data or making paid requests.
- [ ] Run `rtk proxy python -m pytest apps/research/tests apps/campaign_finance/tests apps/congress/tests apps/ingestion/tests` with the repository's test interpreter/settings and isolated database; run frontend `rtk proxy pnpm test`, `rtk proxy pnpm typecheck`, and `rtk proxy pnpm exec playwright test e2e/representative-research.spec.ts` against a disposable stack. Do not restart the user's running stack to make tests easier.
- [ ] Document credentials, provider-specific request budgets, recovery/replay, ambiguous identity resolution, data-use review, portrait licensing, retention, and distinguishing missing vs partial vs complete finance data.
- [ ] With explicit authorization and FEC credentials, perform a bounded live smoke test for the three profiles and compare a sample of amounts/identity/source links against official records. A fixture-only pass is not proof of live-provider compatibility.
- [ ] Commit the verified implementation; push/open or update a PR only when authorized.

## Release gates

- Clicking Research creates durable work and reaches a terminal or explicitly resumable state; page refresh does not lose it.
- Bio/photo/finance are stored and survive cache loss. A failing refresh preserves prior accepted results.
- No false candidate identity joins, receipt double-counting, employee-as-employer attribution, or fabricated donor-topic endorsements in the benchmark fixtures.
- Finance coverage and reporting period are visible; complete labels require reconciliation and pagination completion. Every published money row and graph edge has evidence.
- Representative page, list action, and modal behave consistently; controls recover after failure and work by keyboard on narrow screens.
- Individual contributor publication satisfies the documented data-use review; no exposed addresses/contact data, source keys, internal payloads or scraping escape paths.
- No regressions in bill ingestion, existing representative biographies, votes, recommendations, or current user-facing profiles.

## Delivery order and prerequisites

Implement tasks 1–5 first as a complete Research feature, then task 6 as the connections view, and task 7 as release verification. No separate donor navigation is needed; the contributor identities, transactions, snapshots and connections API form its future foundation.

Before live finance research: provision a server-side FEC API credential and confirm the individual-contributor data-use policy. Missing credentials must not block biography/photo research. Before implementation, confirm this plan's proposed defaults; no additional planning platform is necessary.
