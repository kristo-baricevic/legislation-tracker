# Legislator profiles implementation and remaining data work

Parent approved the reviewed proposal against committed dashboard baseline `4c5302bcbd36c19fb1d04dcb1c4adb27fe38b4f7`. Work is isolated in branch `codex/legislator-profiles`, task11 checkout. No new dependencies, model changes, shared migrations, subscriptions, credentials, push, deployment or production ingestion.

## Implemented profile scope

- Stable numeric representative ID and Bioguide identity; equal names never join records. Bill lists now include nullable sponsor ID/Bioguide and a supported federal bill-page projection. Latest stored affiliation stays separate from historical service observations.
- Public strict `GET /api/representatives/{id}/profile/?congress=119[&chamber=house]` returns `legislator-profile-v1`. Service observations retain year precision, including uncertain boundary years; no synthetic January3 date becomes an election or exact term-start date. At most100 observations; truncation is disclosed.
- Existing `sponsored-bills` endpoint supplies primary sponsorship only. Live pages replace rows. Profiles label historical/source gaps and exclude cosponsors. Introductions cover both chambers in the selected Congress.
- Public `voting-record` endpoint reads actual `VoteRecord` rows independently of the latest chamber or derived service-window filters. Optional actual chamber filter, deterministic date/ID ordering, pagination<=100/page, live-page timestamp, direct count, unknown-session count, member completeness unknown, chamber provider coverage, and separately labeled legacy service-window checks. At most200 derived windows are displayed with a truncation notice.
- House and Senate reader URLs are projected from validated Congress/session/roll identifiers and Washington civil year. Session-list fallbacks must match Congress and known session. API URLs, API keys, unsafe schemes and unrelated lists are never exposed. UI labels projections as derived and shows unavailable links explicitly.
- Public `biography` endpoint independently resolves exact Bioguide→WikidataP1157→English Wikipedia, verifies the current nondeprecated claim and page Wikidata identity, and rejects ambiguous matches, redirects, disambiguation, malformed/deleted/empty pages and inconsistent revision metadata. Plain introductory excerpt<=500characters, factual source text, attribution/page/license links, fetched timestamp and separately observed article revision. The revision URL is not claimed to pin the excerpt. Every excerpt discloses source limiting, with local shortening separately disclosed.
- Wikipedia is operator-off by default (`LEGISLATOR_WIKIPEDIA_ENABLED=False`). Approved local preview enables it. Fixed public endpoints and private `requests.Session(trust_env=False)` prevent netrc/environment credential forwarding; no cookies/auth/image fetches. No redirects. Each response<=512000bytes; an8second request budget is checked between calls and streamed bytes with connect/read timeouts<=2seconds. Requests/DNS are not a hard realtime wall-clock guarantee. Cache24hours fresh/7days maximum stale, negative15minutes, global provider lock, per-IP12/minute throttle, denial/rate-limit Retry-After backoff, cache outage fails closed without enrichment. User-triggered interactive requests omit optional maxlag per MediaWiki guidance; returned maxlag errors still fail gracefully. No background ingestion.
- Accessible native sibling dialogs share central scroll locking, top-only keyboard/cancel/backdrop handling, unique titles, focus restoration and a connected page-control fallback. Four-dialog limit and cycle fallback preserve full-page navigation. Bill→profile→different bill works without discarding parent data/version selection. Route pathname/search changes and rollback close the stack and abort reads. Repeated clicks consume the current profile; late responses cannot populate another person.
- Root `ProfileProvider` enables names on dashboard cards, bill lists/details, bill roll-call member records and directory rows. User/browser profile preference is separately reversible and defaults off; dashboard rollback remains independent. Names retain full-page anchors and modified-click behavior. Avatar is a small SVG person icon, no photograph.

## Actual local source verification

Approved bounded public reads on2026-10-10 verified S000033→Q359442→Wikipedia page361176, article revision1378464460 observed2026-10-04T16:55:30Z. The actual API returned a verified available excerpt with fetched timestamp2026-10-10T04:12:17+00:00; the live browser test displayed its source and attribution links. A cold development StrictMode remount may receive `provider_busy` while the canceled request populates cache; the unavailable section offers explicit Retry. No automatic retry bypasses provider backoff.

The initial optional maxlag5 request returned `source_maxlag`. MediaWiki explicitly permits interactive tasks to omit maxlag: [Manual:Maxlag parameter](https://www.mediawiki.org/wiki/Manual:Maxlag_parameter). This profile adapter runs only for user reads; no bot/bulk job was changed.

## Election data remains a real gap

Neither ingested `Representative` nor its year-derived `RepresentativeTerm` rows stores verified election results or exact term starts. First elected, most recent election won and exact term start therefore each remain unavailable, per chamber, with distinct reasons. A Senate office must not inherit a previous House election; appointments must not be labeled election wins.

Official [House/Clerk election statistics](https://history.house.gov/Institution/Election-Statistics/Election-Statistics/) provides federal state/territory election totals from1920 through the latest2024 report. A future pipeline needs verified representative/office/state/district/term identity, dated official winner results (including specials and appointments) and separate official service-start evidence from [Bioguide](https://bioguide.congress.gov/). CongressAPI member terms alone provide startYear/endYear, not an exact election date: [Member endpoint](https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/MemberEndpoint.md). The smallest next decision is approval for a bounded official-result verification pilot and reviewed provenance storage; no election importer or manual factual overrides were added here.

## Donor feasibility and smallest next decision

Environment-presence checks found no existing FEC_API_KEY/FEC_API_TOKEN/OPENFEC_API_KEY. Only presence booleans were inspected. An unauthenticated bounded OpenFEC candidates request returned403. No new credential/account/subscription was created and no denied request was retried with another credential.

Official [FEC bulk index](https://www.fec.gov/data/browse-data/?tab=bulk-data) exposes candidate master, committee master, candidate-committee linkage and transaction downloads by cycle, including2023–2024 and2025–2026. It does not require a new API credential to discover/download these published files. Index metadata was reviewed; no bulk file was downloaded or ingested. [OpenFEC API](https://api.open.fec.gov/developers/) is the alternative if existing authorized access is later provided through an approved secret channel.

Reviewed [candidate master schema](https://www.fec.gov/campaign-finance-data/candidate-master-file-description/) includes CAND_ID, office/state/district/election year and principal committee CAND_PCC; it contains no Bioguide field. CAND_ID persists only while a candidate runs for the same office. Candidate status is not an election win. [Candidate-committee linkage](https://www.fec.gov/campaign-finance-data/candidate-committee-linkage-file-description/) adds cycle/committee linkage, not a verified Congress identity crosswalk. Names alone are insufficient.

Smallest safe future pilot: one approved completed reporting cycle and a small manually verified Bioguide→office-specific FEC candidate→authorized candidate-committee mapping, retaining official verification URLs/timestamps. Acquire only approved source files or existing-authorized API data. Review amendments/latest filings, itemization coverage, memo/double-counted conduit entries, entity/type codes, refunds, transfers and receipt/disbursement differences before publishing totals. Separate direct candidate-committee receipts from outside spending. Display USD amounts, cycle, exact reporting window, source/retrieval timestamp and methodology. Avoid contributor addresses/ZIPs and unnecessary personal details; ambiguous individual identities remain unmerged.

[Individual contribution schema](https://www.fec.gov/campaign-finance-data/contributions-individuals-file-description/) carries employer/occupation, amendment/memo/transaction fields and personal location fields. Employer-associated individual donations must be labeled as individuals reporting that employer, never as corporate donations. PAC/committee identities can be mapped by official IDs; a first phase confined to political committees should be titled “Top contributing political committees,” not silently represented as all donors. No finance payload currently exposes individual donor data.

FEC [sale/use guidance](https://www.fec.gov/updates/sale-or-use-contributor-information/) restricts commercial/solicitation uses of individual contributor information and distinguishes political committee names and certain communications/research uses. Access to public files does not by itself establish this product's permitted reuse. Before a personal-donor pilot, the operator must resolve intended product reuse against that guidance. This is a precise unresolved assessment, not a blanket assertion that all factual campaign-finance display is forbidden.

Next decision: authorize a bounded public-bulk political-committee pilot with verified mappings/cycle, or provide already-authorized OpenFEC access for that same scope. Personal-donor/employer aggregation requires the additional reuse assessment and reviewed methodology. No production ingestion follows from either pilot approval without separate authorization.

## Recommendation integration contract

Recommendation agent owns `apps/congress/topic_activity.py`, private accounts routes, auth generation changes and `RepresentativeActivity`. These files were not cherry-picked/copied from its uncommitted checkout.

Profile branch owns strict public `GET /api/representatives/{id}/topic-activity/`. It calls `representative_topic_activity(id,captured_at=timezone.now())`; no Congress/chamber query is accepted because this activity uses a separate rolling window. In this standalone profile build the helper is absent and returns503unavailable. After parent integrates the recommendation module, the route exposes its existing DTO unchanged. The helper's own read-only repeatable-read transaction requires ATOMIC_REQUESTS=False.

Frontend exports:

```tsx
type ProfileScope = {
  representativeId: number;
  congress: number;
  chamber?: "house" | "senate";
};
// LegislatorName: {id:number|null,name:string,congress:number,chamber?:...}
// ProfileProvider: {children,renderActivity?:(scope:ProfileScope)=>ReactNode}
```

Parent's concrete renderer wiring after branch integration:

```tsx
"use client";
import React from "react";
import ProfileProvider from "./ProfileProvider";
import RepresentativeActivity from "./RepresentativeActivity";
export default function ProfileExperience({children}:{children:React.ReactNode}) {
  return <ProfileProvider renderActivity={scope =>
    <RepresentativeActivity scope={scope} />}>{children}</ProfileProvider>;
}
```

Replace the RootLayout's `ProfileProvider` import/wrapper with this client `ProfileExperience`; never pass a function across a server/client boundary. Recommendation rows may use `renderName={({id,name,chamber})=><LegislatorName id={id} name={name} congress={currentCongress} chamber={chamber==='house'||chamber==='senate'?chamber:undefined}/>} `.

Final generation exports agreed with agent: capturePersonalizedScope(), isPersonalizedScopeCurrent(scope), subscribePersonalizedChanges(listener); PersonalizedScope={sessionGeneration,interestGeneration}; personalized request options={scope?,signal?}. Clear private UI immediately on session/tracking/revalidate events and reload under a new capture. Account/tracking generation checks surround CSRF/send/refresh/replay/response. The profile APIs and excerpt contain public facts and add no private follow mutation. Parent must integrate existing BillDeck follow controls with that generation lifecycle and rerun auth/follow cross-account tests; this branch does not claim that broader integration reviewed.

`BillDeckModal` and `StackDialog` accept optional `fallbackFocus?:()=>void`. A connected opener has priority; a remaining parent dialog keeps focus inside it. When the final dialog closes and its root opener disappeared or cannot focus, the current root callback runs before the generic page-control fallback. Parent supplies this callback only for recommendation-owned bills and closes only those bills on recommendation invalidation; ordinary public bill dialogs stay open across personalized revalidation.

Concrete parent seam (the persistent dashboard heading needs an agreed ID and `tabIndex={-1}`):

```tsx
const restoreInPriorityOrder = () => {
  for (const selector of ['#bill-recommendations-title',
    '[data-recommendations-toggle]', '#dashboard-title']) {
    const target = document.querySelector<HTMLElement>(selector);
    if (target && !target.closest('[hidden], [inert]')) {
      target.focus();
      if (document.activeElement === target) return;
    }
  }
};
<BillDeckModal bill={bill} onClose={closeBill}
  fallbackFocus={recommendationOwned ? restoreInPriorityOrder : undefined} />
```

## Verification and review evidence

- Focused profile API tests:22passed; biography tests27passed (49total). Tests cover equal names, chamber changes/boundary years, unavailable elections/donors, primary vs cosponsor, direct/billless votes, present/not-voting/absent/other, public auth access, strict invalid query/IDs/pages, mutable page deletion/refresh, civil-year/source projection, throttle/cache outage, ambiguous/deprecated/mismatched identity, revision race/recovery, stale/cache expiry, disabled network, locks/backoff, timeout,403/429/redirect/maxlag/oversize/malformed payloads, and no external auth.
- Profile UI tests10passed; new API guard tests3passed within38API tests. UI covers rollback, nested unique dialogs/focus/scroll, unsafe links/text, lazy votes, stale person response, coherent corrected sponsor pair, query-only teardown/abort, disconnected opener fallback, repeated-click deduplication, connected opener priority and latest owner callback after a row disappears. API guards cover source allowlists, unsafe/credential URLs, AbortSignal, ignoring untrusted next URLs, malformed or wrong-person/scope data and invalid scope/pages.
- Native Chromium Playwright8passed: five existing dashboard scenarios and three profile scenarios, including bill→profile→bill keyboard flows, same-name IDs, live page replacement, responsive layouts and actual enabled Wikipedia transport/UI. Screenshot evidence in client/test-results/profile-{desktop,tablet,mobile,live-wikipedia}.png was inspected. Browser plugin runtime unavailable; existing installed Playwright was used after skill/tool discovery. No browser dependencies were added.
- Final frontend full suite93component tests+38API tests passed, including the owner-focus seam. Final TypeScript and changed-file ESLint passed. Final optimized Next production build passed using the installed bundled `--webpack` compiler; final Turbopack attempts hit a CSS-worker local-port permission error even with the permitted retry, while an ordinary loopback-bind check succeeded. The webpack build needed permitted network access for existing configured Google fonts. No dependencies/configuration/package scripts changed. Django check passed and makemigrations --check --dry-run found no changes. Black/Ruff and git diff --check passed after formatting.
- Extension utilities11passed. Production dependency audit failed:14existing advisories (3critical,6high,4moderate,1low) across Next, sharp, browserslist and source-map-js. Lock/dependencies match the dashboard baseline; no upgrade was authorized or made. Complete audit JSON is `/tmp/profile-pnpm-audit.json`. Audit-reported patched thresholds: Next>=16.3.8 for all listed Next advisories, sharp>=0.35.5, browserslist>=4.28.7 and source-map-js>=1.2.2. Actual exposure depends on platform/features; this is not a claim that every advisory is exploitable in this preview. Parent should assess/authorize the baseline dependency repair before production rollout. Critical Next records: [Windows RCE](https://github.com/advisories/GHSA-p293-qw3h-jr36), [AVIF image-optimization RCE](https://github.com/advisories/GHSA-2xp9-vwfh-vxw4), [next/og ImageResponse RCE](https://github.com/advisories/GHSA-vcvr-r3jv-pc5j).
- Aggregate plain backend run:981passed,1skipped,1existing ingestion failure. `test_replayed_manual_bill_work_fulfills_the_original_tracking_request` mocks bill_detail but not bill_summaries; without Congress credentials it makes an unintended public summary request and fails403. No tracked ingestion files were changed. A temporary `/tmp/profile-hermetic-pytest.py` plugin mocks only that test's bill_summaries to[]; final aggregate run with it:986passed,1skipped. Parent should add that one fixture line in its telemetry integration and rerun the plain suite; this is not represented as a plain unmodified aggregate pass.
- Independent read-only plan review repaired two passes; final no actionable plan findings before parent approval. Independent implementation review repaired cache-throttle outage, sponsor ID/name coherence, source limiting/derived-link disclosures, full route teardown, actual legacy check evidence and disconnected focus fallback; final delta review found no actionable findings. Reviewer independently reran UI8 and API guards3, injected wrong-sponsor/wrong-Congress rows and confirmed rejection; earlier independently reran biography27. Final owner-focus seam review also found no actionable findings and independently reran UI10passed, including nested restoration and latest callback. Recommendation/personalized integration remains separately pending.

## Preview and isolated resources

Frontend http://127.0.0.1:13290, API http://127.0.0.1:18011, dedicated Postgres15441/legislator_profiles. Directory contains the known biography identity S000033; bill is explicitly labeled synthetic local QA fixture. No real finance/election/vote corpus was ingested. Check “Enable legislator profiles” in the header, open Bernie Sanders from Representatives, and use explicit Retry biography if a cold local development remount temporarily receives provider_busy. Production source flag stays off. Final handoff records whether these preview processes remain running.

Final preview uses the built standalone server, with ignored static/public build assets copied into its generated directory. The three isolated services remain running for parent review. Reproduce final client checks from the client directory (each needs appropriate loopback/network permissions):

```sh
rtk pnpm test
rtk pnpm exec tsc --noEmit
rtk proxy env NEXT_PUBLIC_API_URL=http://127.0.0.1:18011 pnpm run build --webpack
rtk proxy cp -R public .next/standalone/public
rtk proxy cp -R .next/static .next/standalone/.next/static
rtk proxy env HOSTNAME=127.0.0.1 PORT=13290 node .next/standalone/server.js
rtk proxy env PROFILE_LIVE_PREVIEW=true pnpm exec playwright test --config=playwright.profiles.config.ts
```

Focused backend tests use only the isolated database:

```sh
rtk proxy env DATABASE_URL=postgresql://kristo@127.0.0.1:15441/legislator_profiles .venv/bin/pytest apps/congress/tests/test_profiles_api.py apps/congress/tests/test_biography.py -q
```

All shell commands were routed through RTK. Other agents' checkout, port13280 and XT resources were untouched.
