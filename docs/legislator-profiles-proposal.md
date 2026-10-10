# Legislator profiles: proposal for parent approval

Status: planning only; no product code, migrations, ingestion, push, or deployment.
Independent adversarial plan review completed in three passes on 2026-10-10; final verdict: no actionable findings remain. Review and repairs are recorded in `docs/legislator-profiles-plan-review.md`.
Baseline verified 2026-10-10: `4c5302b` (`feat: add locally flagged legislation card dashboard`), cloned from `codex/dashboard-card-deck`. Isolated branch `codex/legislator-profiles`, checkout `/Users/kristo/Documents/Codex/2026-10-09/task-11/legislation-tracker`. No use of the task-8 checkout, port 13280, shared database, or Extend resources.

## Decision requested

Approve the additive data/API/UI implementation below, including explicit unavailable states for election dates and donors, optional Wikipedia enrichment disabled by default, and presentation of recurring-topic/recommendation evidence produced by the other agent. No new dependencies or database migration are proposed. Approval permits implementation and isolated verification; it does not permit push, deployment, shared database changes, credentials, or production ingestion.

This is a new profile interface over existing representative evidence. The profile lets readers inspect neutral, factual information and follow activity; it must not recommend a vote or turn inferred ideology into biography or support evidence.

## Actual repository evidence

Backend `apps/...` paths below are relative to `legislation-tracker-backend/`; frontend paths are relative to `legislation-tracker-client/`.

Federal Congress only is supported by the current schema. State legislature profiles are outside its current data model; `state` identifies the member's represented state, not a state legislative jurisdiction.

`apps/congress/models.py` contains a unique Bioguide identity and stored service intervals:

```python
bioguide_id = models.CharField(max_length=20, unique=True, db_index=True)
class RepresentativeTerm(models.Model):
    representative = models.ForeignKey(Representative, on_delete=models.CASCADE,
        related_name="service_terms")
    chamber = models.CharField(max_length=20)
    state = models.CharField(max_length=2, blank=True, default="")
    district = models.CharField(max_length=10, null=True, blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
```

The ingestion code does not establish exact service dates. `apps/ingestion/tasks.py:_member_terms` currently constructs these dates from years:

```python
start_year = int(term.get("startYear"))
raw_end_year = term.get("endYear")
end_year = int(raw_end_year) if raw_end_year not in (None, "") else None
# ...
"start_date": date(start_year, 1, 3),
"end_date": date(end_year, 1, 3) if end_year is not None else None,
```

Display those values with year precision. Do not reuse January 3 as an election, appointment, swearing-in, or precise term-start date. Do not change their current use in insight calculations as part of this feature.

`Bill.sponsor` is a foreign key to Representative (`related_name="sponsored_bills"`). `BillCosponsor` is separate, including withdrawal timestamps. Existing public `/api/representatives/{id}/sponsored-bills/?congress=N&page=P` correctly filters `representative.sponsored_bills.filter(session=N)` and uses bounded DRF pagination. This can power introduced legislation with an explicit sponsor label. It contains resolutions too, so the section is titled **Introduced bills and resolutions**, with original sponsor records only.

`BillDetailSerializer.get_congress_gov_url` already derives a public Congress.gov page for `HR` and `S` records, but currently lacks strict numeric validation and resolution support. Add a nullable `congress_gov_url` field to list output using a strict, fixed-host projection for supported federal HR/S identifiers, including correct Congress ordinal and positive bill number. Label it **Official bill page derived from stored identifier**; unsupported/malformed/state identifiers show **Official bill link unavailable**, while their internal full bill page still works. Do not expose `source_api_id` as a credential-requiring source URL or perform one detail request per list row. Preserve existing detail behavior unless parent approves sharing the hardened projection. Official Senate roll-call evidence already links to Congress.gov bill pages; direct Congress.gov page reads were restricted by the research tool, so that access restriction was respected. No website scraping is proposed.

Bill-list identity is missing: `BillListSerializer` returns `sponsor_name` but not the FK. Its actual implementation is:

```python
def get_sponsor_name(self, obj):
    if obj.sponsor_id is None:
        return None
    return str(obj.sponsor)
```

`Representative.__str__` returns `f"{self.name} ({self.state}-{self.chamber})"`. The dashboard currently matches this string against `rep.name`, which also creates state-lookup failures and name-collision risks. Add `sponsor_id` and `sponsor_bioguide_id` as nullable additive fields, retaining `sponsor_name` for compatibility. Use ID, never a name join, for profile clicks, deduplication, and directory state lookup. Resolve an unlisted/historical sponsor via its ID endpoint, not the current-member list. A missing FK remains non-clickable with an unavailable identity notice.

`VoteRecord` stores a unique `(vote, representative)`, normalized positions `yes/no/present/not_voting/other`, plus `raw_position`. `Vote` identity is `(congress,chamber,session_number,roll_number)`, with a separate legacy constraint for unknown session. It stores date, question, nullable bill, source URL and source update timestamp. Public vote APIs exist but no paginated representative-position endpoint exists. Existing representative insights provide ingestion coverage checks, not complete provider coverage or election facts.

Whole-repository source searches found no FEC/donor, Wikipedia/Wikidata, election-result, or biography integration in backend apps/settings or frontend API helpers. Existing funding extraction concerns money in bill text and cannot supply campaign donors. No live database was inspected; actual persisted coverage/counts must be read from the selected isolated data set during implementation, and the UI always labels its stored coverage.

Stack: Next 16.3.1, React 19.2.3, TypeScript, scoped CSS; Django/DRF/Postgres; existing requests/Redis cache. Tests: Vitest, Testing Library, Node API tests, Playwright, pytest. Client AGENTS.md requires installed Next documentation before implementation. Root RTK.md and .agents are absent in this clone; the user-supplied mandatory RTK rule is applied to all shell invocations.

## Source assessment (checked online 2026-10-10)

### Identity, service and introductions

[Library of Congress member endpoint documentation](https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/MemberEndpoint.md) says of Bioguide: “The unique ID value that originates in the Biographical Directory”; of `startYear`: “The year in which the member’s service in that Congress began.” These short excerpts support stable identity and year-level precision. The same source separately describes sponsored and cosponsored legislation. The current roster fields do not identify first elected or most recent election.

[Congress.gov API access](https://github.com/LibraryOfCongress/api.congress.gov/blob/main/README.md): “An API key is required for access.” Documented limit: 5,000 requests/hour. Reuse ingested records; do not call Congress.gov from a profile click or create a new credential. The docs authorize retrieval/reuse of machine-readable collections; continue source attribution and current provider coverage notices.

For **first elected** and **most recent election won**, use official state certified results and/or [House Clerk Election Statistics](https://history.house.gov/Institution/Election-Statistics/Election-Statistics/), whose source description is “official vote counts for federal elections from the official sources among the various states and territories.” These are not already linked in this repository. Bioguide or official member biographies can help establish service/appointment history, but must not be parsed into an election date from a service-year field. FEC candidate election year describes a campaign and is not evidence that an election was won.

Initial behavior: separate first elected, most recent election won, exact term start, and observed service intervals. Election and exact term-start facts are unavailable for each explicitly selected or observed chamber. Observed intervals have year precision and a Congress/Bioguide source link. Include appointment status only if explicitly verified. First observed service year is not labeled first-ever service when historical completeness is unknown. The request scope is a Congress with an optional explicit chamber; the response returns all stored intervals whose year ranges overlap that Congress, including chamber/state/district and their precision. An overlap is a stored service observation, not proof of membership for every date in that Congress. If chamber is omitted, show each observed chamber separately; if observations are missing, report historical chamber unknown rather than use the latest roster chamber. An explicitly requested chamber with no observation remains an unavailable historical context. Election import/mapping requires a separate approved pipeline, recording Bioguide, chamber, state/district as of event, election type, date precision, result, source URL, retrieval time and confidence/review status.

### Wikipedia biography

Use official MediaWiki Action API at `https://en.wikipedia.org/w/api.php`, with `action=query`, `prop=extracts|info|revisions|pageprops`, `exintro=1`, `explaintext=1`, `exchars=500`, `inprop=url`, `rvprop=ids|timestamp`, `formatversion=2`. [TextExtracts docs](https://www.mediawiki.org/wiki/Extension:TextExtracts#API): “Returns plain-text or limited HTML extracts of the given pages”; “Return only content before the first section.” Avoid `exsentences`, which the documentation warns is unreliable. Bound the final extract to 500 characters without cutting a word, indicate shortening, and do not generate ideology or other claims.

A real read of the Bernie Sanders API returned page ID `361176`, Wikidata item `Q359442`, revision `1378464460`, revision timestamp `2026-10-04T16:55:30Z`, and canonical `https://en.wikipedia.org/wiki/Bernie_Sanders`. This is a metadata/transport example, not an identity seed or a production bio. API response [source](https://en.wikipedia.org/w/api.php?action=query&format=json&formatversion=2&prop=extracts%7Cinfo%7Crevisions%7Cpageprops&inprop=url&rvprop=ids%7Ctimestamp&exintro=1&explaintext=1&exchars=500&titles=Bernie_Sanders).

Resolve by exact Bioguide crosswalk, never by first name/name search. [Wikidata P1157](https://www.wikidata.org/wiki/Property:P1157) is described as “identifier for a person on the Biographical Directory of the United States Congress”. The resolver uses a fixed, bounded Wikidata Query Service query for the exact ID (limit 2), accepts exactly one entity, confirms its current nondeprecated P1157 claim through entity data, and gets its English Wikipedia sitelink. The Wikipedia response must have that same `wikibase_item`, namespace 0, no missing/disambiguation flag, and valid canonical page/revision metadata. Multiple identities, mismatching IDs, or missing page mean unavailable. Wikidata supports [public data access](https://www.wikidata.org/wiki/Wikidata:Data_access) under CC0, but its crosswalk is community-maintained rather than an official congressional identity authority. Validate it and report that provenance. [Query Service documentation](https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service) now notes a 2026–2027 backend migration; keep the endpoint a fixed operator setting with an allowlist, and test the supported endpoint before enabling. The web research tool could not open the Wikidata JSON action endpoints, so complete transport verification remains an implementation prerequisite; never substitute fuzzy lookup if an endpoint denies access.

No credentials or paid Wikimedia service are required for public reads. [Wikimedia User-Agent policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy): “Scripts should use an informative User-Agent string with contact information”. Use the repository URL as public contact. [API etiquette](https://www.mediawiki.org/wiki/API:Etiquette) requires considerate serial requests, caching, and backoff. [Terms of Use](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use#7._Licensing_of_Content) requires attribution, license notice, and disclosure of changes; display **Wikipedia contributors**, article link, CC BY-SA 4.0 link, **Excerpt fetched [time]**, **Article revision observed [date/link]**, and **Excerpt shortened**. TextExtracts does not identify the revision that produced the extract: its [official implementation](https://raw.githubusercontent.com/wikimedia/mediawiki-extensions-TextExtracts/master/includes/ApiQueryExtracts.php) renders/caches the current page by title. Separately returned revision metadata is observed article metadata, not an immutable revision attribution for the excerpt. Exact revision-bound text would require a separate verified design. Text is rendered as React text only. No photos are requested or displayed.

Separate fast `/profile/` from `/biography/`; bio failure must never hide existing identity/bills/votes. External reads are operator-disabled by default (`LEGISLATOR_WIKIPEDIA_ENABLED=false`). Implementation uses mocked upstream fixtures and optionally parent-approved local read-only transport tests; no production ingestion/enabling. With explicit enabling after approval, the backend caches verified snapshots by `(Bioguide,language,provider/schema version)`: fresh for 24 hours; retain last valid same-identity extract for at most 7 days with stale notice and last-success timestamp. Identity mismatch/revocation clears any cached bio and fails closed. Negative results cache for 15 minutes; 403/429 honor Retry-After with no immediate retry; timeouts, malformed payloads and maxlag fail gracefully. Shared-cache locking prevents duplicate requests, with a global provider concurrency cap of one, per-IP throttling, an 8-second request budget checked between calls and streamed bytes, connect/read timeouts at most 2 seconds (Requests/DNS do not guarantee a hard wall-clock deadline), bounded body sizes, and no arbitrary URLs or caller-provided page titles. Cache outages return unavailable rather than unbounded upstream calls. Compare separately returned revision metadata with page `lastrevid` only as a metadata/race consistency check; if inconsistent, one bounded retry within the same deadline, otherwise unavailable. A passing check does not establish the extract's exact revision.

### Campaign finance

Preferred future authoritative source: [OpenFEC API](https://api.open.fec.gov/developers/) / FEC bulk public records. The API documentation offers an api.data.gov key; this task will not sign up or create one. Bulk downloads do not require an API key, but their availability does not provide a verified identity crosswalk or correct top-donor aggregation by itself. No existing source, mapping, credentials configuration, finance parser or stored finance data is usable in this repository.

[FEC individual contribution file](https://www.fec.gov/campaign-finance-data/contributions-individuals-file-description/) states: “This file is a subset of all itemized contributions made by individuals disclosed to the FEC.” It documents amendment, transaction, entity, memo and report identifiers. This excludes any claim that a top-itemized list represents all donors. [Candidate–committee linkage](https://www.fec.gov/campaign-finance-data/candidate-committee-linkage-file-description/) says candidate IDs remain stable across cycles only while running for the same office; committee IDs remain stable. Office switches require an explicit Bioguide-to-FEC mapping and cycle-specific authorized/principal committee records, not a name join.

[FEC use restrictions](https://www.fec.gov/updates/sale-or-use-contributor-information/) include “cannot be sold or used for soliciting contributions” and describe limits on commercial uses and exceptions. The future provider must be reviewed for this application's use, especially individual contributor data; do not assume that public access removes restrictions. Initial UI: **Top donors — Unavailable. Verified campaign finance data is not connected.** API status `unavailable`, reason `source_not_configured`, period/cycle null, donors array empty; the UI must not turn that into “no donors”, a zero amount, or an invented election cycle.

If a later source is approved, each snapshot must contain candidate ID, included receiving committee IDs, cycle and exact reporting interval/as-of, currency USD, source/report links, retrieved time, completeness and methodology version. Rank only verified itemized contributions to candidate authorized committees. Keep individual, PAC/committee and organization-supported entity types separate. Never label people grouped by employer as corporate donations. Do not group/merge individual donors by name alone. Handle amendments/replaced filings, memo/earmark double counting, conduit attribution, refunds and reattributions; define gross and refunds separately, and net only when the source supports the linkage. Exclude transfers, candidate self-funding, loans and outside/independent expenditures from donor ranking unless separately and explicitly labeled. No home addresses, ZIP, occupation, donor contact details or raw upstream receipt objects appear in API/UI/logs. An unvalidated aggregate remains unavailable. This methodology is a future contract, not permission to implement a finance importer now.

### Votes and coverage

[House roll-call API documentation](https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/HouseRollCallVoteEndpoint.md#coverage) describes individual positions as “Aye”, “Nay”, “Present”, and “Not Voting”. The **House API restriction** is legislation-linked votes in Congresses 118/119; non-legislative House votes are explicitly excluded. [Official Senate votes](https://www.senate.gov/legislative/votes_new.htm) publishes question, date and results; baseline `SenateVoteSource.discover` iterates all votes in an official session list, including those without bills. Senate provider scope is that official session list, with historical availability stated as unknown unless checked. Do not apply the House restriction to Senate or mixed-chamber records. The repository already consumes Senate XML and Congress House data; no new vote ingestion is proposed.

Paginate persisted `VoteRecord` rows directly by stable representative ID, requested Congress and optional explicit actual vote chamber, ordered `-vote__vote_date,-vote_id,-id`, selecting related vote/bill. Do not filter solely by the representative's current chamber or derived January-3 service interval, which can discard real historical or special-election records. Expose the actual chamber/session on each row; null session stays unknown. No sponsorship/party inference and no synthetic absent records for missing vote rows. Preserve `raw_position`: explicit absent remains **Absent (source wording)**, unspecified `not_voting` stays **Not voting**; present stays present; unknown remains Other with safe source wording. A row can have no bill (nomination/procedural vote or missing linkage); always show its recorded question, with **Bill link unavailable** where necessary.

Coverage metadata distinguishes provider restrictions, ingestion checks, and member-position completeness. The new direct record query returns `stored_record_count` for the requested person/Congress/chamber, chamber-specific `provider_scopes`, and `member_position_completeness="unknown"`. It does not compute a missing-member count or absences from derived service windows. Existing insight coverage becomes a separately nested `legacy_ingestion_check` with its own scopes, reason, discovered/persisted counts and **Service-window ingestion checks** label. Its synthetic service intervals/fallback scopes may differ from the direct record query. Its `coverage_complete=true` means the existing checks passed; it cannot establish member-position completeness or full official coverage. Show the historical unknown-session warning where applicable. Do not label an empty list a legislator who never voted.

Persisted URLs need reader-facing interpretation: House discovery stores key-requiring API links, and Senate discovery may store a session-list URL. Do not expose an API endpoint as a working evidence link or a list as a direct roll call. For validated canonical identity, construct safe public links: Senate `/legislative/LIS/roll_call_votes/vote{congress}{session}/vote_{congress}_{session}_{roll:05d}.htm` (verified [119/1/1 example](https://www.senate.gov/legislative/LIS/roll_call_votes/vote1191/vote_119_1_00001.htm)); House Clerk `/Votes/{year}{roll}` with validated session/year agreement and positive roll (verified [118/2/80 example](https://clerk.house.gov/Votes/202480)). When canonical session/date information is missing, retain only an allowlisted reader-facing URL and label it **Official session list** if that is what it is; otherwise **Source link unavailable**. No network validation occurs on a profile click. A derived link is explicitly described as an official roll-call link derived from the stored identity; malformed/inconsistent identity yields no derived link. Source update time is not assumed to be last ingestion time.

Pagination deliberately uses **live page replacement** with Previous/Next and Refresh to page 1. Keep the existing sponsored-bill order and the specified vote order; expose count and a `page_read_at` timestamp, and display **Stored records can change as sources are updated; refresh to revisit the current list.** Do not accumulate pages into an implied complete history. Each successful page replaces rows and its page label atomically; a failed/out-of-range next request keeps the previous page and offers refresh. Insertions, deletions and date/activity corrections can move rows between pages; no complete traversal guarantee is claimed. Static deterministic ordering plus ID deduplication alone is insufficient. Each list supports deliberate refresh/reset after a data change, and tests cover insertion, deletion and reordering between requests. Snapshot/cursor accumulation would be a separate design, not silently promised here.

## API proposal (additive, public factual data)

- Existing representative endpoints keep behavior and authentication. New `/api/representatives/{id}/profile/?congress=N&chamber=house|senate` returns identity, latest-stored roster fields separately from requested-Congress service observations, per-chamber election/service fact statuses, explicit donors status, and coverage metadata. `chamber` is optional and must never default from latest roster fields for a historical Congress. No external network or data mutation.
- New `/api/representatives/{id}/biography/` returns the independently loaded cached/enrichment result. Read-only public endpoint with per-IP throttling; disabled state causes no network traffic. It accepts no arbitrary upstream URL or title.
- Reuse existing sponsored-bills pagination with live page replacement and response-received timestamp (no API compatibility change needed there). Add bounded representative `/voting-record/?congress=N&chamber=house|senate&page=P&page_size=20`, count/next/previous/results, `page_read_at`, `pagination_mode="live_pages"` plus scoped coverage. Optional chamber filters actual stored vote chamber only. Strict unknown query rejection, positive IDs/Congress, page size at most 100. 404 for nonexistent representatives; no ID/name fallback.
- Add `sponsor_id`, `sponsor_bioguide_id` and safe `congress_gov_url` to BillListSerializer and corresponding frontend BillListItem and response validator; new fields nullable, tolerant of older responses for reversible rollout. Use BillDetail.sponsor for known detail IDs. Existing clients need no behavioral change.
- Additive helper implementations go in new `profile_api.py`, `profiles.py`, `biography.py`, and focused serializers, with a small import/action change in congress/views.py. No modification of the ingestion pipeline or existing insight math. Keep media URL/photo out of the new DTO.

Proposed core type sketch (contract, not implemented):

```ts
type FactStatus = "available" | "unavailable";
type DatedFact = {
  status: FactStatus; value: string | null;
  precision: "day" | "year" | null;
  reason: string | null; source_url: string | null;
  retrieved_at: string | null;
};
type Biography = {
  status: "available" | "stale" | "unavailable";
  text: string | null; reason: string | null;
  wikidata_id: string | null; page_id: number | null;
  observed_revision_id: number | null; observed_revision_at: string | null;
  page_url: string | null; observed_revision_url: string | null;
  fetched_at: string | null; shortened: boolean;
  attribution: "Wikipedia contributors"; license: "CC BY-SA 4.0";
};
type RecordedVote = {
  id: number; representative_id: number;
  vote_id: number; congress: number; chamber: "house" | "senate";
  session_number: number | null; roll_number: number;
  vote_date: string; question: string;
  position: "yes" | "no" | "present" | "not_voting" | "other";
  raw_position: string; bill: BillListItem | null;
  source_url: string | null; source_updated_at: string | null;
  source_link_kind: "roll_call" | "session_list" | "unavailable";
};
type ProfileScope = { congress: number; chamber: "house" | "senate" | null };
type VoteCoverage = {
  scope: ProfileScope; stored_record_count: number;
  member_position_completeness: "unknown";
  provider_scopes: Array<{ chamber: "house" | "senate"; description: string;
    source_url: string; historical_availability: "known" | "unknown" }>;
  legacy_ingestion_check: { scopes: unknown[]; reason: string | null;
    coverage_complete: boolean; discovered_count: number | null;
    persisted_count: number | null };
};
```

Use runtime validation before committing response data to UI; invalid shape is a recoverable section error, not renderable source text. Construct/reject URLs using HTTPS and exact host/path allowlists (Wikipedia, Wikidata, Congress, House Clerk, Senate and Bioguide as appropriate), disallow credentials, nonstandard ports, protocol-relative forms, javascript/data schemes and unsafe redirects. Never forward an upstream API key query string into a source link. Outbound requests are fixed hosts/paths with redirects disabled and bounded parsing. Source links use safe anchors, appropriate rel, and visible provenance.

## UI, rollback and navigation

Reuse the dashboard's off-white background, near-white panels, Geist type and muted navy/burgundy/green/teal accents. An inline person-outline SVG supplies the avatar (`aria-hidden` beside the name); no image library or photo. Responsive dialog: 2 columns on desktop, one column on mobile, max-height scrolling, long names/URLs wrap. Header shows name and current/former roster status; a separately labeled **Latest stored affiliation** identifies stored chamber/state/district/party. The **Selected Congress** service section lists observed historical chamber/state/district with year precision, or unknown. Multiple historical chambers remain separate. Do not label a former member's party current or retroject latest roster fields into a historical Congress. State badges may use stable-ID directory lookup only when labeled latest stored state; historical state comes from observed service, otherwise unknown.

Sections: service/elections; attributed Wikipedia bio; top donors unavailable; recurring topics; introduced bills/resolutions; **Show voting record** reveals paginated real records within the modal, with a Back to profile action. Full representative page remains available. Source/coverage notices appear beside their evidence, not hidden behind an info icon.

Use reusable `LegislatorProfileModal`, `LegislatorName` and profile API helpers. Initially wire dashboard sponsor names, sponsor in BillDeckModal, representative directory name links, bill-list/detail sponsor names, and member names in VotingRecord. Sponsor clicks carry that bill's `session` as Congress and leave chamber unspecified unless an authoritative historical field is available. Vote-name clicks carry the vote's Congress and actual chamber; directory clicks carry current Congress and its explicitly labeled latest chamber. Full-page anchor hrefs preserve the same Congress and optional chamber, as does nested navigation. Existing representative detail pages remain unchanged; currently supported Congress query keeps working and extra context must not alter their existing insight logic. The legacy Dashboard.tsx stays unchanged for rollback; parent may approve its names as a follow-on. Enabled primary click opens modal, modifier/middle clicks and disabled flag navigate normally.

An independent localStorage flag `legislation-tracker-legislator-profiles` defaults false during review. A named checkbox in the dashboard settings area makes local enabling possible; denial of localStorage defaults off, reports save failure and does not crash. The existing card-dashboard flag/rollback remains unchanged. No feature requests while flag is off; no remote flag SDK.

Use native `dialog.showModal()` with labeled title, initial focus, Tab/Shift+Tab containment, Escape and visible Close, background inert and preserved body scroll state. Retrofit **BillDeckModal.tsx** intentionally to use the same stack manager as every new profile/bill dialog; parent must reserve that shared edit. The baseline's per-dialog overflow restore, unguarded Tab/cancel handlers and fixed `bill-dialog-title` cannot remain for nested dialogs. Render stack entries as sibling portals, use unique React `useId` title IDs, guard all keyboard/cancel/backdrop handlers to the top entry and stop handled events from reaching another dialog. The manager alone saves/restores body overflow on zero→one / one→zero transitions. Closing restores the connected inner opener; if removed, focus a connected control in the underlying dialog, otherwise the original page opener or a documented page fallback. Parent data/selected version/scroll stay mounted while children are open. Avoid duplicate dialogs and profile→bill→same-profile cycles; limit depth and retain clearly labeled full-page links. Test bill→profile→different bill as well as profile→bill. Rollback/route navigation closes the entire stack and aborts requests. Backdrop closes only on outside-coordinate clicks for the top entry.

Each data section fetches independently with AbortController plus request identity/generation check for all initial, retry and page-navigation requests. Clear old person/Congress/chamber data immediately on a scope change. Duplicate clicks/page navigation use a synchronous in-flight guard; aborted/stale responses do not change rows, errors, loading, or page counters. Failed pagination leaves the displayed page and label intact and offers scoped retry/refresh. One lazy vote fetch upon the button click; no request per individual bill/vote. Replace successful pages rather than accumulating/deduping into a completeness claim.

## Recommendation-agent boundary

Agent `01a123c3-c316-73e5-962b-f658494720ec` owns recurring-topic detection, X threshold, ranking and backend endpoints. This task owns presentation and factual source integration only. Parent coordinates endpoint name/types and frontend merge ownership. Suggested UI props: `RepresentativeTopicEvidenceSection({representativeId,congress,provider})`; `RepresentativeLookalikesSection({representativeId,congress,provider,onOpenProfile,onFollow})`. New files should be separate from BillDeck.tsx until parent approves the small integration patch.

Recurring topics receive observation start/end, source coverage, method/version, X threshold and whether recurrence criterion met. Every topic shows separate introduced, active/withdrawn cosponsored, and voted-for counts, distinct bill counts, date spread, and expandable paginated official evidence links. Do not sum different evidence types into an unqualified count. A yes on cloture/procedural motion is not automatically substantive policy support; the algorithm must identify qualifying vote questions and label other actions precisely. Merely mentioned topics, broad fallback topics, party, donor ties, missing votes and withdrawn support are not affirmative evidence. **Strong supporter (recorded activity)** appears only when the other agent's approved rule is met with adequate coverage, with its threshold/window shown; otherwise display recorded activity or unavailable. No frontend threshold/recommender calculation is implemented here.

Lookalikes return at most five with stable IDs, observation window, qualifying evidence, matched explicit followed topics, method and coverage. UI label **Similar legislative activity**; clicking opens that person's profile, with explicit **Follow activity** action using existing authenticated trackLegislator APIs. Signed-out users see login; 401/403 are errors, never silently anonymous changes. No auto-follow or voting endorsement. Personalized request identity includes account/session generation, explicit-interest generation, representative ID, Congress and chamber. Immediately abort and clear recommendations and follow status on logout, account switch or followed-topic changes; discard stale success/error/finally callbacks. Baseline authGet has no AbortSignal: extend its options additively or add an abort-aware authenticated helper, including auth replay generation checks, never a public-GET fallback. Keep personalized DTOs only in scoped component memory with no public or persisted cache. Recommendation endpoints owned by the other agent must emit `Cache-Control: private, no-store` and appropriate `Vary: Cookie, Authorization`; frontend requests use `cache: "no-store"`. Topic-interest scope comes only from explicit user follows, never inferred sensitive traits. Missing interest/history shows an honest insufficient-data state. Recurring-topic and lookalike failures do not hide factual profile sections.

The new profile's explicit follow mutation also carries a captured account/session generation and AbortSignal. Baseline `trackLegislator → authPost` waits for CSRF setup and may replay after credential refresh, so ignoring a stale UI result alone is insufficient. Extend trackLegislator's options additively or provide an equivalent scoped mutation helper; re-check signal and captured generation after CSRF setup, immediately before the initial POST, before starting refresh, and after refresh immediately before replay. Abort and never send/replay across a generation change. Apply the same contract to unfollow if exposed. A request already sent under account A remains an A request; cancellation is not represented as undoing it. Tests switch/logout during CSRF setup and refresh and assert that no follow/unfollow POST is sent or replayed using account B. Parent coordinates ownership of the small shared api.ts/auth lifecycle edit with the recommendation agent.

## Implementation sequence after approval

1. Read local installed Next docs and relevant testing/security conventions. Confirm available reusable dependencies without changing task-8 files. Parent confirms frontend ownership and recommendation DTO; no migration numbering needed for this proposal.
2. Add sponsor identity fields and focused API regression tests. Implement fast profile and direct paginated recorded-vote endpoint with provider-coverage labeling.
3. Implement optional serial Wikipedia resolver/provider using existing requests/cache, fixed-host safety, provenance, throttling and the unavailable/stale states. Offline fixtures are mandatory; do not enable production calls.
4. Build standalone accessible profile and evidence sections, independent flag, nested navigation and stale-response handling. Integrate names by ID only; consume other agent's approved topic/recommendation DTO.
5. Run aggregate checks, isolated browser QA, independent adversarial code review, repair and review again until no actionable findings. Provide exact diff/source excerpts, test output and limitations to parent. No push/merge/deploy.

## Required verification

Backend: same names/different Bioguide/state/chamber; service across chamber changes, non-January special/appointment cases and unavailable exact election dates; original sponsor vs cosponsor/withdrawal; public read/authenticated follows, 404, strict invalid query/page bounds; billless votes, repeated roll numbers across sessions/Congress, null-session legacy data, present/not-voting/explicit absent/other, missing member rows, chamber-specific provider coverage; legacy ingestion check complete with a missing member row and a real row outside its derived service scope; deterministic static order and live pagination insertion/deletion/date/activity corrections, out-of-range refresh and query-count bounds. Validate House/Senate canonical source links, API-key links, generic session-list labels, unknown session and inconsistent year/session. Bio: no match/multiple matches, deprecated/mismatched crosswalk, redirects/disambiguation, deleted/empty/malformed/huge extract, observed revision metadata mismatch and non-immutable attribution, untrusted text/URLs, 403/429/Retry-After/maxlag/timeout, shared-cache outage and lock contention, TTL/stale expiration, cached identity invalidation, disabled network and no accidental donor exposure.

Frontend/component/API: malformed responses, unknown/new fields, all missing/stale/error states, attribution/license/date display, cache separation of public facts from personalized data, delayed account A→logout→account B and explicit-interest change responses, auth-replay abort, follow/unfollow switching during CSRF setup or refresh with no POST/replay for B, ID-based sponsor collision test, bill/vote/directory Congress/chamber context and former/multiple/missing history, repeated open/close/person changes, late page/retry responses and atomic page replacement, focus restore (including disconnected nested opener), unique IDs and bill→profile→different bill, keyboard/Tab/Escape, backdrop coordinates, stack body-scroll restoration, rollback while nested open, modifier-link behavior, 320px/mobile/tablet/desktop/long-content overflow, follow failure/auth access, invalid external links suppressed.

Aggregate: backend manage.py check, migration dry-run, black/ruff, pytest, existing dependency audit; client typecheck/lint, Vitest + Node API tests, build, extension tests. Every shell invocation runs through RTK. Use isolated Postgres/test settings; never default/shared database env. Playwright fixture-backed QA uses frontend port 13290 and a new dedicated config; real isolated backend QA can use port 18011 if needed. Keep all output clearly fixture versus real data. No touching 13280. Tests/audits requiring blocked network are reported with exact blocker, not claimed passed.

## Current blockers and approval boundary

Implementation awaits the explicitly requested parent approval of this proposal. Direct send_message_to_thread for the supplied durable parent ID returned `thread not found` twice; ordinary assistant output is the authorized handoff path. Donor/election data remain precise gaps, handled honestly in the first implementation. Wikipedia JSON resolver transport and the recommendation agent's final endpoint/DTO remain prerequisites before those pieces can be enabled/integrated. There are no product-code changes or executed product tests yet.
