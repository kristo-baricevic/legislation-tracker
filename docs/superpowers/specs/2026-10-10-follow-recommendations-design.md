# Explicit-follow bill recommendations: proposal v1

Status: parent technology/implementation approval received; independent plan repairs complete with no implementation blocker. This design and the [representative activity addendum](2026-10-10-representative-topic-recommendations-design.md) form one approval package.
Baseline: `4c5302bcbd36c19fb1d04dcb1c4adb27fe38b4f7` (`codex/dashboard-card-deck`), independently verified with GitHub `ls-remote` on 2026-10-10. Isolated checkout: task-10/legislation-tracker, branch `codex/follow-crossover-recommendations`. The telemetry task-8 checkout is read-only to this task. No pushes, merge, deployment, shared migrations, production access or live ingestion are authorized.

## Intended outcome and technology decision

Help a signed-in reader discover other already-ingested bills with factual relationships to topics, representatives and bills they deliberately follow. Rank crossover between interest facets above otherwise comparable single-facet matches. Explain each relationship plainly. No inferred ideology, party affinity, persuasion, vote prediction, engagement optimization, or demographic profile.

Recommend the existing Next 16.3.1 / React 19.2.3 frontend and Django / DRF / PostgreSQL backend, with standard-library integer arithmetic and existing Django ORM, signing and default cache. No package, embedding, model API, background worker or new service. The default cache is already Django RedisCache in base.py:88; tests use LocMemCache. This proposal adds a short-lived private ranking snapshot to that existing cache. Cache failure must produce a recoverable 503, with no silent unstable-pagination fallback. No database schema change or migration is proposed. The independent UI flag is disabled by default.

Parent approval should cover the scoring policy, existing-cache snapshot use, active-cosponsor signal, weaker followed-bill metadata signal, separate frontend flag and bounded row. Implementation would remain local until separately authorized to publish.

## Verified capabilities and source evidence

These excerpts are from the committed baseline, not the telemetry working copy. URLs are immutable source links.

- [accounts/models.py](https://github.com/kristo-baricevic/legislation-tracker/blob/4c5302bcbd36c19fb1d04dcb1c4adb27fe38b4f7/legislation-tracker-backend/apps/accounts/models.py#L201): `class TrackedBill(models.Model)`, `class TrackedTopic(models.Model)` and `class TrackedLegislator(models.Model)` each associate `user` with a bill/topic/representative and enforce a unique per-user target. BillViewState acknowledges reading; it is not a recommendation signal.
- [accounts/views.py:412](https://github.com/kristo-baricevic/legislation-tracker/blob/4c5302bcbd36c19fb1d04dcb1c4adb27fe38b4f7/legislation-tracker-backend/apps/accounts/views.py#L412): `permission_classes = [IsAuthenticated]`; summary querysets use `.filter(user=request.user)`. Tracking feed already matches `Q(bill__bill_topics__topic_id__in=topic_ids) | Q(bill__sponsor_id__in=representative_ids)`. Follow/unfollow uses existing authenticated POST/DELETE endpoints.
- [legislation/models.py:27](https://github.com/kristo-baricevic/legislation-tracker/blob/4c5302bcbd36c19fb1d04dcb1c4adb27fe38b4f7/legislation-tracker-backend/apps/legislation/models.py#L27): Bill has `jurisdiction`, `session`, `bill_number`, `title`, `status`, nullable `sponsor`, `last_action_at`, `introduced_at` and processing state. BillTopic has a unique `(bill, topic)` and `(topic, bill)` index; confidence is nullable.
- [congress/models.py:299](https://github.com/kristo-baricevic/legislation-tracker/blob/4c5302bcbd36c19fb1d04dcb1c4adb27fe38b4f7/legislation-tracker-backend/apps/congress/models.py#L299): BillCosponsor has representative FK and `withdrawn_at`; `(representative, withdrawn_at)` is indexed. Representative identity is an FK/Bioguide ID, not display-name matching.
- [BillDeck.tsx:75](https://github.com/kristo-baricevic/legislation-tracker/blob/4c5302bcbd36c19fb1d04dcb1c4adb27fe38b4f7/legislation-tracker-client/app/components/BillDeck.tsx#L75): `const visible = source.filter(...)` uses local search/topic/sponsor/state/status state. These are temporary view filters; changing them does not create a persistent follow.
- [accounts/models.py:114](https://github.com/kristo-baricevic/legislation-tracker/blob/4c5302bcbd36c19fb1d04dcb1c4adb27fe38b4f7/legislation-tracker-backend/apps/accounts/models.py#L114): UserPreference is explicitly described as non-tracking state/chamber preferences. SavedBillSearch stores a durable query, but its persistence is not consent to use it as an interest profile.
- [legislation/tasks.py:323](https://github.com/kristo-baricevic/legislation-tracker/blob/4c5302bcbd36c19fb1d04dcb1c4adb27fe38b4f7/legislation-tracker-backend/apps/legislation/tasks.py#L323): existing BillSimilarity is `round(topic_score * 0.6 + token_score * 0.4, 6)`, based on topic and title/summary/contract tokens; it is content similarity, not collaborative filtering. Recompute scans the bill catalog pairwise. The new endpoint will not trigger it or presume pair-table coverage/freshness.
- [legislation/tasks.py:352](https://github.com/kristo-baricevic/legislation-tracker/blob/4c5302bcbd36c19fb1d04dcb1c4adb27fe38b4f7/legislation-tracker-backend/apps/legislation/tasks.py#L352): topic confidence is keyword-hit-count divided by keyword count. It is not a calibrated probability. Unmatched bills receive `general-legislation` with confidence 0.0. Migration 0012 gives the same fallback to historical untagged bills.
- [.agents/skills]: no `.agents`, `.codex`, root AGENTS.md or RTK.md exists in this baseline. Client AGENTS.md requires reading installed Next docs before implementation. Workspace-supplied mandatory RTK policy applies to every shell command. No instruction or dependency will be imported from Extend repositories.

## Research comparison and adopted scope

| Source | What the original describes | Decision for this tracker |
| --- | --- | --- |
| Pazzani & Billsus, **Content-Based Recommendation Systems** (2007), [publisher chapter](https://link.springer.com/chapter/10.1007/978-3-540-72079-9_10), DOI 10.1007/978-3-540-72079-9_10 | Compare item descriptions with an interest profile. | Adopt the transparent content/profile framing using explicit follows and stored metadata. Do not adopt learned classifiers or implicit browsing feedback. Publisher abstract was accessible; do not claim a full chapter review. |
| Sarwar, Karypis, Konstan & Riedl, **Item-Based Collaborative Filtering Recommendation Algorithms** (WWW 2001), [author-group paper](https://files.grouplens.org/papers/www10_sarwar.pdf), DOI 10.1145/371920.372071 | Derive item relationships from a user-item preference matrix and aggregate neighbors. | Defer collaborative item relationships: no verified interaction density, appropriate consent or relevance labels. Metadata sharing between bills is content-based, not this technique. |
| Linden, Smith & York, **Amazon.com Recommendations: Item-to-Item Collaborative Filtering** (IEEE Internet Computing, 2003), [original paper mirror](https://www.cs.umd.edu/~samir/498/Amazon-Recommendations.pdf), DOI 10.1109/MIC.2003.1167344 | Precompute item associations from co-purchases; serve related items efficiently. | Adopt only the useful architectural separation of candidate retrieval and ranking. Reject co-follow/popularity models, offline pair-table infrastructure and commerce/conversion objectives. Amazon's few-items claim relies on a populated aggregate table; it does not establish this tracker's cold-start capability. |
| Carbonell & Goldstein, **The Use of MMR, Diversity-Based Reranking for Reordering Documents and Producing Summaries** (SIGIR 1998), [author-hosted original](https://www.cs.cmu.edu/~jgc/publication/The_Use_MMR_Diversity_Based_LTMIR_1998.pdf), DOI 10.1145/290941.291025 | Greedily balance relevance against maximum similarity to selected results. | Adopt the MMR selection equation with factual topic/sponsor similarity and a conservative weight. This is a metadata adaptation, not the original retrieval experiment; no asserted quality gain. |
| McNee, Riedl & Konstan, **Being Accurate Is Not Enough: How Accuracy Metrics Have Hurt Recommender Systems** (CHI EA 2006), [author-group original](https://grouplens.org/site-content/uploads/accurate-CHI-20061.pdf), DOI 10.1145/1125451.1125659 | Evaluate list usefulness and user needs beyond individual prediction accuracy. | Adopt coverage, explanation correctness and list redundancy evaluation, alongside relevance. Do not equate held-out-follow recovery or clicks with civic usefulness. |

Compared alternatives: (1) pure multi-facet content matching is simplest and auditable but can repeat the same metadata; (2) collaborative/item-to-item ranking requires data and introduces other-user influence; (3) content matching plus conservative MMR retains the explicit-follow foundation and reduces metadata repetition. Choose (3), with a pure-ranking comparator in offline evaluation. Numeric weights below are original policy choices, not parameters justified by these papers.

## Profile: explicit follows and bounded metadata propagation

Use only the authenticated user's TrackedTopic, TrackedLegislator and TrackedBill records. Read all these follows; never truncate a user's profile silently. Topic and representative affinities are sets, not counts.

- A specific explicitly followed topic has affinity 100.
- A specific topic attached to a followed bill has affinity 35, unless explicit affinity 100 already applies.
- An explicitly followed representative gives sponsor match strength 100 and active cosponsor match strength 75 (`withdrawn_at IS NULL`). Multiple matching representatives or sponsor-plus-cosponsor are combined with `max`, never sum.
- A sponsor of a followed bill gives strength 35 to another bill with that same sponsor. Do not propagate interests through every cosponsor of a seed bill.
- Do not use `general-legislation` as an interest, seed feature, diversity feature or explanation. It means classification missing, not a shared policy interest. A follow of it remains intact, but the API reports it as unsupported for recommendations.
- Specific tags with null confidence or finite positive confidence are usable categorically. Use one shared usable-edge SQL predicate everywhere (profile, candidates, MMR, reasons, fingerprint): exclude the fallback slug and require `confidence_score IS NULL OR (confidence_score > 0 AND confidence_score < +Infinity)`. PostgreSQL NaN compares greater than ordinary values, so `>0` alone is wrong. Ignore nonfinite or nonpositive confidence rows. Do not use confidence as a probability or score multiplier.
- Explicit followed-topic affinity wins over seed affinity. Multiple seeds/tags never multiply strength. Topic and representative are distinct factual facets; overlaps within a facet saturate.

Unsupported inputs: temporary filters, SavedBillSearch, UserPreference state/chamber, committees, party, votes, viewing cursors, history/clicks, inferred ideology, and arbitrary URL query filters. The API rejects unknown parameters. No new filter-follow model is necessary for this first version. Future additional interest types need an explicit follow/opt-in control and separate approved policy.

## Exact scoring and missing-data normalization

For candidate b, `T(b)` is the maximum affinity over its usable specific topics: 0, 35 or 100. `R(b)` is max(explicit sponsor 100, explicit active cosponsor 75, seed sponsor 35, 0). Define `A_T=1` when the user has at least one usable explicit/seed topic, otherwise 0; `A_R=1` when they have an explicit followed representative or known seed sponsor, otherwise 0. `D=60*A_T+40*A_R`. The denominator depends only on the user profile, not the candidate's completeness.

If D=0, return an empty cold-start state. Otherwise let `C(b)=min(T(b),R(b))` when both facets are active, else 0, and:

```text
N(b) = 4*(60*T(b) + 40*R(b)) + D*C(b)
S(b) = N(b)/(500*D)
     = 0.8 * normalized weighted facet match + 0.2 * crossover strength
```

Use integer N for exact base ordering; all candidates for one user have the same denominator. Return S rounded to six decimals for diagnostic use, not a displayed confidence percentage. Candidate missing sponsor/tags gets 0 for that field and is not renormalized upward. No freshness/status/party multiplier.

Example for a user with both facets active:

| Candidate relationship | T | R | S |
| --- | ---: | ---: | ---: |
| Explicit topic + explicit sponsor | 100 | 100 | 1.000 |
| Explicit topic + active explicit cosponsor | 100 | 75 | 0.870 |
| Explicit topic + seed sponsor | 100 | 35 | 0.662 |
| Explicit topic alone | 100 | 0 | 0.480 |
| Explicit sponsor alone | 0 | 100 | 0.320 |
| Seed topic + seed sponsor | 35 | 35 | 0.350 |
| Seed topic alone | 35 | 0 | 0.168 |
| No supported relationship | 0 | 0 | excluded |

A topic-only profile gives an explicit topic match 0.800; a representative-only profile gives an explicit sponsor match 0.800 and active cosponsor 0.600. Scores are only comparable within the same user/profile. Adding another kind of follow can change normalization; this is intentional and documented.

## Eligibility, retrieval, deterministic ranking and diversity

Eligible bills are existing Bill rows in federal/state jurisdiction, positive session, nonblank bill_number/title (including whitespace validation), at least one positive supported affinity, and not in this user's TrackedBill set. Processing can be pending/failed and documents/summary can be missing; metadata discovery does not imply full text is processed. Historical sessions and terminal statuses remain eligible and labeled. No ingestion request, external lookup or current-member-only assumption. Candidate identity is Bill.pk; the model enforces session/bill_number uniqueness. Do not collapse different sessions or companion bills by title.

Construct topic/sponsor/active-cosponsor matches using ORM `Exists`, subqueries and indexed FK relationships. Avoid row-multiplying joins and large Python profile IN lists. Annotate integer T, R and N in SQL. Read up to 501 matching rows ordered by `N DESC`, `last_action_at DESC NULLS LAST`, `introduced_at DESC NULLS LAST`, `id ASC`; retain first 500 and set `candidate_pool_truncated` when the extra exists. Preserve session/status as metadata rather than broad eligibility matches.

Fetch usable topics and only needed relationship names in a constant number of prefetch queries. No document/contract text and no per-card detail request. Build up to 60 recommendations from the pool with MMR:

```text
J(B1,B2) = |usable_topics(B1) intersect usable_topics(B2)| /
           |usable_topics(B1) union usable_topics(B2)|, or 0 for empty union
sim(B1,B2) = 0.7*J(B1,B2) + 0.3*[both known sponsor IDs equal]
M(b, selected) = 0.9*S(b) - 0.1*max(sim(b,x) for x in selected)
```

For the first result, max similarity is 0. At each step pick maximum M. Tie-break by the full base-order tuple above. Use exact rational comparison for J/MMR (standard-library Fraction); at most 500*60*60 metadata comparisons, reduced by maintaining each candidate's running maximum similarity. Diversity is only among positive-match bills; unrelated items never enter to fill a row. Missing sponsor equality is 0, not missing=missing. Metadata diversity does not establish viewpoint balance, legislative-effect diversity or serendipity. Pool limit can omit lower-score but diverse bills; disclose this limitation.

## Factual explanations

Return at most one strongest topic and one strongest representative reason, deterministically by strength descending, target ID ascending, relation order sponsor before cosponsor, then seed bill ID ascending. Explicit source outranks seed source. Reasons have typed kind, target ID/name, relation and optional seed bill ID/number/session. A seed representative reason is available only for sponsor equality. No names are matched by string. Example copy:

- “Tagged Health, a topic you follow.”
- “Sponsored by Alex Rivera, a representative you follow.”
- “Cosponsored by Alex Rivera, a representative you follow.”
- “Shares Health with HR 42 (119), a bill you follow.”
- “Has the same sponsor as HR 42 (119), a bill you follow.”

Use “tagged” because the repository's keyword classifier is fallible. Do not claim support/opposition, predicted relevance, political alignment or unexplained percentage confidence. Explanations must be derived from exactly the scored relationships and remain consistent with the cached card metadata.

## API, freshness, snapshots and privacy

New authenticated GET `/api/tracking/recommendations/`, declared explicitly `IsAuthenticated` even under dev AllowAny defaults. Input: `page_size` integer 1..12 (first request default 6), optional `cursor` signed string (max 2 KiB). On continuation omitted page_size inherits the signed cursor's value; an explicitly supplied value must match it. Reject unknown/repeated query parameters, malformed input and altered cursor page_size. Client helper `getBillRecommendations({pageSize?,cursor?})` uses authGet; credentials are existing cookie JWT/bearer behavior. No caller-supplied user ID.

Every service request, initial or continuation, runs its follow/profile/seed/eligibility reads in one PostgreSQL read-only repeatable-read transaction (SQLite transaction for hermetic tests). Set transaction isolation before the first service query and materialize all lazy querysets inside it. Validity means as-of this database snapshot; a follow committed after that boundary invalidates the next request, rather than claiming an impossible response-time global guarantee. Initial ranking and serialized card metadata share that snapshot. Store at most 60 already serialized cards, exact diagnostic scores and reasons in a versioned default-cache slot per user for 300 seconds. One active slot per user bounds card count; additionally enforce a 1 MiB UTF-8 JSON snapshot ceiling with allow_nan=False before cache write. A too-large snapshot returns recoverable 503 recommendations_metadata_too_large, preserves the existing dashboard and never silently truncates interests, titles or tags. This is a storage limit, not a proof of bounded temporary database/serialization memory. Each slot has a random snapshot nonce, profile fingerprint, creation time, schema/algorithm version and fixed page_size. A fresh request replaces the slot; another tab's prior cursor then receives 409 and refreshes. Cache content is private application state; no new public endpoint or log of profile/scores/reasons.

Expiry is captured_at+300 seconds, not write time+300. Cache timeout is the remaining whole seconds at write, and every use validates the embedded expiry. Discard a build with no remaining lifetime. This prevents ranking/build time from extending the advertised five-minute age. Cursor signing age is an additional upper bound; cache snapshot expiry is authoritative.

The cursor uses Django timestamp signing with dedicated salt and `{version,user_id,nonce,offset,page_size}`, max age 300s. It is authenticated, not encrypted, and contains no follows, explanations or ranked IDs. Verify authenticated user binding before looking up the user's slot; no cross-user lookup. Cursor offset must be a page_size multiple within the stored list and page_size fixed across continuation. Tampering/foreign-user tokens return a uniform 400. Expired/missing snapshots return 410 `recommendations_expired`; changed profile or replaced slot returns 409 `recommendations_changed`; cache unavailability 503 `recommendations_unavailable`.

Profile fingerprint streams ordered persistent follow rows (including created_at), seed sponsor IDs and usable seed topic edges, so unfollow/re-follow or seed metadata change invalidates a continuation even if IDs happen to match. Inside the continuation's same consistent transaction, recompute the user's profile signature and ensure none of the page's IDs are followed/deleted/ineligible as-of that read snapshot; changes return 409. Check nonce again before returning to detect a replaced cache slot; replacement after that check is an accepted request-boundary race and invalidates the next continuation. Snapshot card metadata and explanations are explicitly as-of captured time; other catalog edits do not reorder a snapshot. Newly ingested bills appear on a fresh first request. Returned snapshot does not promise current sponsor/tag/status beyond its at-most-five-minute age.

Apply `Cache-Control: private, no-store` and `Vary: Cookie, Authorization` in finalize_response for every success and error, including auth/validation/throttling failures. HTTP cache and frontend storage must not retain private cards or cursors; localStorage holds only the feature toggle and nonprivate session/tracking invalidation epochs. Rate-limit policy is 30 requests/minute per authenticated user using existing DRF/default-cache infrastructure and a separate scope; DRF's cache throttle is approximate under concurrency, not a hard cost bound. An endpoint-specific throttle wraps cache get/set and translates failures to the same DRF 503 recommendations_unavailable exception as snapshot handling; this explicitly covers checks before APIView.get. Test both throttle and service failures independently. Do not share cache keys between users. First ranking materialization occurs only on enabled signed-in UI or explicit API request. Leave existing dashboard usable.

Response example (one item abbreviated):

```json
{
  "algorithm": "explicit-facets-mmr-v1",
  "generated_at": "2026-10-10T00:00:00Z",
  "count": 24,
  "candidate_pool_truncated": false,
  "ranking_limit_reached": false,
  "empty_reason": null,
  "unsupported_follow_types": [],
  "next_cursor": "signed-continuation",
  "results": [{
    "bill": {"id": 123, "bill_number": "HR 70", "session": 119},
    "score": 0.87,
    "reasons": [
      {"kind": "followed_topic", "topic_id": 8, "name": "Health"},
      {"kind": "followed_representative", "representative_id": 7,
       "name": "Alex Rivera", "relation": "cosponsor"}
    ]
  }]
}
```

Actual bill payload has the existing BillListSerializer field shape; it is abbreviated only here. Its recommendation-owned topic projection includes only usable edges using the shared predicate, preserves finite/null confidence_score, and enforces strict JSON sanitation without altering the global serializer. Recommendation card sponsor display is Representative.name; party/state are not recommendation reasons or rank inputs. `count` counts this bounded snapshot, not the entire catalog or all matching candidates. `ranking_limit_reached` means 60 results selected and additional pool candidates remain. Empty reasons: `no_follows`, `insufficient_metadata`, `unsupported_follows_only`, `no_matches`; do not use popularity fallback. A supported profile with all matches already followed returns no_matches. Unsupported types only expose category strings (e.g. `general_legislation`), never another user's data.

## Frontend row and reversible rollout

New `BillRecommendations.tsx`, scoped `bill-recommendations.module.css`, API helper/types in separate `lib/recommendations.ts`, and `lib/recommendations-flag.ts`. BillDeck receives a small integration only: pass ready/signedIn/tracking, shared follow callback/pending ID and onOpen (existing setSelected). Row renders before followed topic sections and outside temporary filter logic. Modal is the existing BillDeckModal; Follow calls existing toggleFollow. Successful follow/unfollow updates tracking and invalidates/refetches the row. Failed saves keep the card, show shared save error, and do not change interests locally. Recommendation cards do not create follows by being shown or opened.

Successful existing bill/topic/representative follow mutations also emit a nonprivate tracking-changed event and epoch-only cross-tab invalidation through lib/api.ts, with no target IDs/profile data persisted. BillDeck invalidates recommendation-owned state, reloads current tracking and restarts only after the latest tracking revision resolves; abort/ignore prior requests. This covers changes on other pages/tabs as well as the row's bill button. Coalesce the shared callback update and event to avoid duplicate rank requests. Window-focus revalidation covers external clients and missed storage events. A failed mutation emits no tracking change.

Independent local toggle key `legislation-tracker-bill-recommendations` is default false. Its control is visible only in the card dashboard; the original dashboard switch is unchanged. Disabled means no recommendation API request. Persistence failure shows a reset-on-reload notice. Reload and cross-tab storage events update the flag. Card-dashboard rollback unmounts the row and preserves existing Dashboard/other pages. Use no build/environment switch or dependency change.

Use the dashboard's near-white cards, off-white surface, muted navy/burgundy/green topic bars and readable text. Bars are decorative and have no party mapping. Desktop/tablet horizontal scroll row, mobile cards with width `min(22rem, calc(100vw - 3rem))`, wrapping long titles and reason text; avoid whole-page overflow. Use a labeled section with h2 and `<ul>/<li>` cards, native title and Follow buttons, ordinary scroll behavior, explicit Load more (up to the 60-card bound) and Refresh. No automatic carousel, hover-only information or motion requirement. Date/status/sponsor remain factual and missing values explicit.

Show loading status, recoverable error + Retry, unauthenticated login prompt, no-follow/insufficient-metadata follow-topic/representative links, and no-match state. 409/410 clears the stale row and restarts once; if refreshed twice in succession, offer Retry instead of looping. Guard asynchronous results with request-generation IDs and session/profile identity; clear private cards immediately on auth loss/profile change.

Verified auth limitation: there is no AuthProvider/event, AuthSession supplies only email, and router.refresh after AuthNav logout can retain mounted client state. Add a small nonprivate `auth-session-changed` event and localStorage epoch-only invalidation in existing lib/api.ts after successful login/logout and final failed refresh; event contains no user data. BillDeck listens for same-tab events and cross-tab epoch storage changes, immediately clears tracking/cards/cursors and recommendation-owned modal selection and increments request generation, then reloads getSession/getMyTracking. Hold recommendations unmounted until both complete for the current revision. Use email only as in-memory identity from AuthSession; do not persist it. Revalidate on window focus. Classify final 401/403 as auth loss and clear all private recommendation state instead of showing generic retry. This is an additional shared lib/api.ts/BillDeck patch for parent coordination; preserve existing auth semantics and validate existing auth tests. A row follow removes its opener: if that button had focus, move focus to the next surviving card or row heading (tabIndex=-1) and announce “Bill followed; recommendations refreshed.” Keep modal selection ownership (regular deck versus recommendation) alongside selected bill. Extend the existing BillDeckModal with an optional focus-fallback ref; cleanup focuses the original opener only when connected, otherwise the persistent row heading or feature toggle. A recommendation-owned modal closes on row disable, auth/profile invalidation or row refresh/expiry reset; normal deck modals retain existing behavior. The toggle survives row unmount. On dashboard rollback the parent switch is the persistent fallback. Test disconnected opener, refresh/disable while open and account change, as well as existing focus containment. Accessible name disambiguates each Follow button by bill number/session.

## Evaluation, verification and known limits

Synthetic tests establish contract correctness, not recommendation usefulness. Compare pure facet ranking, MMR row and recent-activity direct-match ordering on controlled profiles. Measure explanation correctness (100% required), unrelated/followed exclusion (100% required), duplicate rate (0 required), repeat-request determinism, crossover representation, supported-interest coverage and mean pairwise metadata similarity. Evaluate representative/topic-only and sparse-seed cohorts separately. No claimed quality lift from synthetic overlap labels. Later optional human judgments would rate helpful discovery and explanation trust; collect no new behavior for this version.

Backend cases: unauthenticated under dev/test; two users; no follows; fallback-only; seed missing all metadata; null/zero/negative/NaN/positive-and-negative-Infinity confidence; strict JSON sanitation; missing sponsor; active/withdrawn cosponsors; sponsor-plus-many-cosponsors saturation; multiple topics/seeds saturation; deterministic seed explanation; direct/seed crossover order; unrelated and already-followed exclusion; historic/terminal bills; blank metadata eligibility; duplicate joins; deterministic date-null ties; snapshot pagination without repetition; size-12 initial/cursor-only continuation; new ingestion between pages; profile/topic-edge mutations; deleted bills; cursor tamper/expiry/replay from another user; repeated/unknown query keys; page bounds; throttle cache get/set and snapshot cache get/set outages; throttling; 1 MiB snapshot rejection and large-metadata fixtures; bounded truncation.

Frontend cases: default off makes zero calls; independent rollback; authenticated versus anonymous; explicit follows and temporary filter separation; loading/error/empty/no-match; follow/unfollow refresh, failed saves, late responses, same-page logout/account A-to-B switching and cross-tab invalidation while loading; duplicate responses; cursor refresh; keyboard modal/scroll/follow focus; disconnected modal opener/row disable/refresh while open; long titles/reasons, 390px mobile, tablet and 1440px desktop.

Query budget target: <=15 recommendation-service DB queries for a populated initial request, <=8 for continuation, independent of candidate count (excluding auth/throttle), with at most 501 candidate rows and usable-topic edges only for the 500 retained bills; 500 is a parent-bill bound, not a topic-edge or byte bound. No N+1. Inspect PostgreSQL `EXPLAIN (ANALYZE, BUFFERS)` on an isolated synthetic 10k-bill DB including large titles/high tag counts, record actual row counts/query plans/timing/memory; <=500ms initial/<=150ms continuation are local acceptance targets, not measured promises. Also run PostgreSQL correctness/concurrency cases for NaN/Infinity, initial and continuation repeatable-read captures, independent follow/seed mutation between reads, cache-slot replacement and deletion between requests. SQLite success alone cannot establish these behaviors. If plan/timing fails, repair query shape before adding a schema index or infrastructure and return to parent for any schema change approval.

Run relevant focused tests first, then all backend pytest/check/migration-drift/black/ruff, all frontend Vitest/API tests/typecheck/lint/build, existing dashboard Playwright regressions on a discovered free port, new recommendation browser QA, and extension tests/syntax checks. Perform dependency audits if network allows; report environmental failures separately from test results. The aggregate shell script contains direct commands, so honor workspace RTK by running equivalent individual commands through RTK instead of executing it unchanged.

Only isolated LocMemCache/in-memory SQLite or a newly created synthetic PostgreSQL DB may be used. Do not use telemetry port 13280, Extend XT ports/services, real account fixtures or existing production/development DB. Discover a free port by binding loopback port 0 before starting Next, record it and supply it through a separate Playwright config. No backend live server is necessary for fixture-based browser QA. Browser fixtures are clearly identified in evidence.

Limits: keyword tags can be wrong; missing/fallback tags reduce recall; 35-strength seed propagation can be broad; active cosponsor data can be incomplete; metadata diversity is approximate; historical bills may appear; base weights favor topic over representative; 500/60 bounds affect catalog coverage; five-minute snapshots are intentionally stale and one-slot multi-tab refresh can invalidate cursors; Redis outage affects this optional feature; no real-user relevance or behavioral-density evidence has yet been gathered.

## File ownership and proposed implementation sequence

Avoid telemetry's ingestion models/tasks/urls/views/migration 0008. Add backend `apps/accounts/recommendations.py`, `recommendation_views.py`, `recommendation_serializers.py`, tests and the single route import in accounts/urls.py; add one scoped throttle rate in settings. No ingestion file or migration needed. Frontend new files above plus BillDeck import/row insertion/callback return (successful boolean), lib/api.ts auth invalidation and the optional BillDeckModal focus fallback, and tests/new config. Reuse existing CSS through composition only as needed; prefer new scoped stylesheet, separate `RECOMMENDATIONS.md` and separate recommendation E2E spec to avoid telemetry edits to bill-deck.module.css, DASHBOARD.md and dashboard-cards.spec.ts. Parent coordinates shared BillDeck/lib/api.ts/modal ownership patches with telemetry/profile work.

1. Get parent approval of this concrete design/technology; preserve the committed baseline and inspect relevant installed Next guides. Verify available dependencies without installing new ones.
2. Implement exact pure scorer/reason selector and deterministic MMR with meaningful failing synthetic tests for overlap saturation, sparse normalization, fallback tags and diversity.
3. Implement indexed candidate query, authenticated API, per-user bounded snapshots, strict cursor/query validation and privacy headers. Test isolation and adversarial pagination/mutation/cache cases and measure query counts.
4. Implement separately flagged row using existing modal/shared follow callback. Add tests for state transitions/races/focus and no transient-filter signaling. Integrate the minimal shared BillDeck change after parent coordination.
5. Perform isolated PostgreSQL plan/timing evaluation, aggregate checks and browser QA/screenshots at mobile/tablet/desktop on a new free port. Record command results and limitations.
6. Fresh independent code review against this spec, repair each actionable finding, rerun affected checks, and provide final source excerpts for parent personal review. No publishing action without authorization.

## Approval and communication

Parent source thread supplied: `01a112b1-1b08-717b-80a7-f25390c94008`. Authorized send_message_to_thread returned `thread not found`; that thread is absent from current list_threads. The parent subsequently confirmed it can read ordinary commentary/final responses here and requested completion of independent proposal review. Messaging is not a blocker to research or plan review. Parent subsequently personally approved the complete proposal and technology; final independent repairs are complete. This task owns both row components and minimal lib/api.ts generation changes. Profile agent owns LegislatorName/ProfileModal, shared BillDeckModal/dialog stack and focus-fallback adapters: this task does not edit those shared modal files. ProfileScope is {representativeId, congress, chamber?}, LegislatorName props are {id,name,congress,chamber?}, and the provider accepts renderActivity(scope):ReactNode. This task supplies RepresentativeActivity for that adapter. Parent coordinates the small shared BillDeck patch. These final ownership decisions supersede earlier proposed direct modal edits.
