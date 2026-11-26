# Large-bill staged processing — November 25, 2026

## Problem and implementation

The November 24 harness stopped before generation for S.1071 at every experimental chunk size. Splitting the owned section did not bound the supporting definitions, conditions, and cross-references attached to it. A safe rejection demonstrated the guard, not successful large-bill processing.

The reader now handles that case through the saved plan's stages:

1. **Map bounded source owners.** Preserve official XML ancestry, exact offsets, table structure, and complete nonoverlapping source ownership. Small source dependencies can still be supplied directly. When a complete request cannot hold its dependencies, retain exact deferred source/quote obligations and map those sources independently. Repeated nonblank passages are subdivided into uniquely citable owners rather than disappearing behind null quote IDs.
2. **Retain cited factual records.** The existing discovery result and durable work/cache records hold actor, modality, affected people, money/base/unit, timing, definitions, references, and nested `all`/`any` conditions and exceptions. The contracts extend the existing source-first factual schema; there is no new database or parallel fact store. Every assigned citable passage must have exactly one factual record.
3. **Reconcile bounded dependency pages.** Every deferred owner/item/record relationship needs a validated receipt. Receipts bind source evidence, record hashes, earlier revisions, and exact ownership. Applicable conditions must retain their citations. Earlier checked evidence is represented by retained citation IDs in later requests; its original text and factual records remain available to server validation. Missing, altered, duplicated, misassigned, or unresolved pages cannot pass the publication barrier.
4. **Synthesize in bounded groups.** The existing recursive summary reducer runs after reconciliation. If one finding has an oversized citation inventory, its evidence is paged for summary generation without modifying the original finding or factual inventory. A reducer that makes no progress still stops instead of silently dropping a group.

All generation stays inside the existing pinned provider/model, durable reservation, shared cache, retry, and delivery mechanisms. Preflight reserves map, dependency, recovery, and synthesis work. Each actual dispatch must fit the complete serialized request and its output allowance. No SDK retry loop or automatic model/provider change was added.

Internal factual maps and reconciliation receipts remain in saved validation state; the public presentation returns reader prose and its original cited sources. Existing schema-1.4 presentation and small-bill compatibility are retained. Migration `0041_widen_enhancement_estimate` stores the confirmed input estimate and aggregate attempt and enhancement token counts in 64-bit columns. Apply it before starting the updated API and workers.

## Source-pinned large-bill check

Source: `BILLS-119s1071eah`, the House engrossed amendment of S.1071 in the 119th Congress.

- Official XML SHA-256: `69702b764640a8bd86dbc23717cd3161b091668792d6b066a55a42d8e3a64299`.
- Extracted text SHA-256: `7e9a1eb347efd5094b047ad8f797aba9e8c9e1929b43bf946520d19d48b89385`.
- 1,134 official sections and 3,370,908 extracted characters.
- Per-request application limits: 100,000 estimated input units and 120,000 serialized bytes. Estimates remain conservative UTF-8 byte bounds, not measured model tokens.

All four complete planning variants pass:

| Owned target | Owned chunks | Map requests | Initial planned calls | Largest serialized request |
| ---: | ---: | ---: | ---: | ---: |
| Default (8,000-byte ownership target) | 914 | 2,367 | 2,368 | 25,539 bytes |
| 1,000 | 4,433 | 4,433 | 4,434 | 17,079 bytes |
| 2,000 | 2,421 | 2,446 | 2,447 | 18,277 bytes |
| 4,000 | 1,421 | 2,373 | 2,374 | 20,849 bytes |

Initial planned calls include one summary slot. Dependency and recursive-summary reservations are additional ceilings, not claims that every reserved call will be used. No provider was called by these tests. After the review corrections, all four complete variants were rerun: actual preflight took **35.270 / 96.093 / 42.984 / 32.229 seconds** for the default / 1,000 / 2,000 / 4,000-byte targets. Preflight plus the coverage/budget assertions took 51.552 / 106.964 / 47.285 / 38.923 seconds. The four-case test process took 286.128 seconds and peaked at **1,138,876 KiB RSS (about 1.086 GiB)**. The ownership and request counts are unchanged; the table records the corrected planner’s measured request sizes. These timings are local observations, not a controlled performance comparison.

Both the local Compose API and production image now give the API worker 120 seconds to complete a request. This accommodates large-bill estimate/confirmation planning instead of relying on a short default worker timeout. Generation itself continues in the existing resumable background worker.

Citation catalogs are reused only within one planning or worker operation. Discovery now constructs its actual verbatim-passage envelope directly instead of normalizing whole dependency sources and then discarding those copies. The recorded planning time is a local observation, not a measured generation-latency claim.

The pinned test also checks the source evidence governing sections 8805 and 8806. Conditions may be present directly or carried by exact, independently mapped deferred quote obligations; a smaller chunk size does not waive those checks.

## Behavioral verification

In the November 25 SQLite run, the complete legislation backend suite completed **1,664 passed, 10 skipped, zero failures/errors**, with two passing subtests, in 230.94 seconds. Four skips were the full pinned S.1071 cases, which passed separately with the XML path supplied. The other six require PostgreSQL: two full-text/headline search tests and four concurrency/row-lock tests. Those six were not run in this SQLite environment. The four source-sized tests are additional to the 1,664 passing cases; repeated diagnostic runs are not counted as additional tests. Django system checks, the migration dry-run, Black, Ruff, and Git whitespace checks pass.

The staged worker tests use real temporary XML storage, database models, estimate and confirmation APIs, durable reservations, worker execution, cache validation, final synthesis, and publication. Only the upstream model is simulated; network generation is prohibited.

- An oversized dependency completes processing and publication. A distant 50% matching requirement remains in the grant explanation, original citation, and summary.
- A crash after a response is durably validated but before its work-node checkpoint recovers through the actual stale-attempt and retry paths. The original call identity is dispatched once.
- Malformed factual records fail with the expected validation failure before reconciliation or summary.
- An unresolved dependency fails at the reconciliation barrier before summary or publication.
- Twenty repeated public-hospital eligibility clauses all become exact mapped dependency obligations, with no source bytes omitted.
- Two hundred applicable dependency records retain more than 100 KB of earlier evidence and all 201 final citations. Later requests supply current evidence and compact retained IDs, rather than resending the entire history.
- A single finding with 220 supporting source passages completes bounded summary reduction; every evidence page is consumed and the saved finding is unchanged.
- Receipt replay remains valid after reader policy drafts are grouped for display, and tampered drafts still fail validation.

The shared enhancement test fixture now gives each test its own cache-key prefix. This fixes cross-test rate-limit contamination from reused database user IDs while retaining rate limits and cache persistence throughout each individual confirmation, recovery, and reuse scenario.

## PR review corrections

[The PR review](https://github.com/kristo-baricevic/legislation-tracker/pull/35#issuecomment-7176686794) identified integration failures that the initial offline orchestration tests did not cover. The earlier successful planning and simulated-provider results did not establish correct schema transmission through the actual adapters, recovery from a truncated dependency response, or inclusion of server-recovered financial rules in the receipt inventory.

The corrections address all four findings:

1. **Provider schema selection.** OpenAI, Anthropic, Gemini, and OpenAI-compatible adapters select the dependency page/check/item schema explicitly. Malformed dependency envelopes fail before SDK dispatch. Transport tests call the real adapters with mocked SDK responses and inspect the actual transmitted schema. A dependency-only cache version prevents reuse of failures produced by the old wrong schema while preserving map-call identities. Old ambiguous reservations still block duplicate paid dispatches, including salted reruns.
2. **Incoming restrictions.** Resolved local references are retained without requiring a matching modal phrase. The regressions include all three review examples, another wording variant, XML `idref` references without a textual subsection label, and many incoming clauses that must become bounded deferred obligations. Section and quoted-law scope boundaries remain enforced.
3. **Truncation recovery.** A truncated dependency page splits complete records, then reader-item groups; an indivisible page can increase its output allowance within configured, provider, context, and request-size limits. Failed calls are metered, revised requests have deterministic identities, and preflight reserves the finite recovery tree. Real worker regressions exercise completion in the same delivery, an authorized retry after a cached truncation and transient failure, and a crash after a recovered response was durably validated. Mapped facts and validated calls are reused. Capacity, call-budget, and unknown-outcome cases remain bounded.
4. **Recovered financial inventory.** Source-derived financial rows are recovered before dependency reconciliation and summary, including saved-summary replay. A recovered provision spanning several mapped owners is retained as exact per-owner source fragments, so each owner receives its own dependency checks and no combined row becomes unbounded. An oversized source string can be retained with an explicit null text operation in the model response; the server restores its verified original text. Generated replacement prose remains limited to 1,600 characters. Receipt replay validates original source provenance, added citations, and every other prose field. Positive tests preserve a 22,989-character source row with more than 24 citations at the ordinary 24,000-token output ceiling. Tampered source text, generated oversized replacements, and altered labels are rejected.

Financial ownership regressions cover contiguous and disjoint evidence ranges, mixed short/long source fragments, applicable conditions on a later owner, final publication validation, and zero-call replay of completed receipts. The complete source text is retained across these fragments. No provider limit was increased for the correction.

### Second review: production-shaped regressions

[The next review](https://github.com/kristo-baricevic/legislation-tracker/pull/35#issuecomment-7177569022) found four remaining gaps. The earlier tests covered incoming single references, but not ranges or the renderer's child ordering. The financial fixtures put target metadata on discovery owners, unlike real preflight. The compatibility tests constructed old cache keys from the new envelope, rather than an authentic historical request. Those fixtures did not establish the behavior claimed for these paths.

1. **Complete reference ranges.** The context planner expands ranges within the verified legal scope, including intervening provisions, and preserves an unresolved obligation if an endpoint, member, or scope is ambiguous or missing. The reported grant now receives the public-hospital, emergency-service, and 50% matching requirements at both 1,000-byte and default 8,000-byte ownership targets. Regressions also cover mixed lists/ranges, nested shorthand, inserted labels, Roman numerals, external-law qualifiers, and quoted-law scope. Nested shorthand preserves the referenced legal level and label case; a parenthesized “inclusive” cannot hide an external qualification.
2. **Rendered ownership order.** Parent ownership subtracts child intervals in immutable rendered-text order, rather than XML traversal order. Tests use the actual ingestion renderer, XML boundaries, and source planner with a large quoted amendment followed by an inline quotation in its continuation. The resulting owners cover the source exactly without overlaps.
3. **Financial provenance at publication.** Final reconciliation receives the complete source snapshot, including separate non-discovery target metadata. Discovery ownership and factual-record coverage checks remain restricted to discovery sources. The fixtures now match real preflight, and a 6,069-byte recovered row completes estimate, confirmation, worker execution, reconciliation, and publication. Extra non-discovery factual records, duplicate records, altered source text, and citations swapped to overlapping context remain invalid.
4. **Authentic reservation migration.** A checked-in fixture captures requests and keys generated by the actual `563c64c` implementation, including its original prompt, financial schema, output allowance, and planned-source metadata. Known old wire identities are reconstructed for orphaned reservations; durable historical steps also fence unresolved dispatches for the same bill, document hash, provider, and requested or pinned model when planner metadata or source numbering changed. The document-level migration check applies only to executions before version 13, so independent current pages remain independent. Known failed or validated calls and unrelated documents/providers/models do not acquire an ambiguous-outcome fence. The actual adapter paths are tested with mocked SDK calls, including salted reruns and pinned models.

The second review advanced the reader execution version to **13** and the context planner version to **3**. The dependency transport version remains 2; the map cache identity format is unchanged.

### Third review: complete abbreviated paths

[The third review](https://github.com/kristo-baricevic/legislation-tracker/pull/35#issuecomment-7178322191) verified the four preceding fixes and identified a remaining multi-component shorthand failure. The prior continuation tests covered single parenthesized labels, but did not cover a section abbreviation containing several labels. `_reference_parts()` treated `(2)(B)` as one component, so `section 2(a)(1)(A) and (2)(B)` was expanded at the wrong level. The available 50% matching condition was omitted from the grant's selected context and falsely recorded as unresolved.

[The correction](https://github.com/kristo-baricevic/legislation-tracker/commit/2327c5417f70fbe91448686fd219fdd669109311) splits every parenthesized component while preserving a full section's numeric identifier. Continuations can also descend deeper than their preceding reference, such as `section 2(a) and (b)(2)(B)`. Matching prefers the complete shared suffix, with Roman-numbered clauses distinguished from repeated-letter items at their legal levels; `... (i)(I)(aa) and (bb)(BB)` therefore retains the item/subitem path.

Thirteen maintained regressions use actual ingestion, XML boundaries, source planning, and scoped context selection. They cover the reported 37,233-character source at both 1,000-byte and default 8,000-byte ownership targets; equivalent fully expanded wording; compound lists and ranges; deeper continuations; Roman/item numbering; quoted and external laws; and missing targets. Independent probes also verify numeric, suffixed, decimal, and hyphenated section identifiers. The original review reproduction and all thirteen new cases pass.

That correction used reader execution version **14** and context planner version **4**, so confirmations and published-output freshness checks recognize this change. The historical reservation boundary remains **below version 13** because it belongs to the earlier transport migration; it is not a moving latest-version lock. The version 14 correction itself changed neither the database columns nor provider limits.

### Fourth review

Reader execution version **15** uses context planner **5**. A repeated structural kind starts its own path. Shorthand uses the numbering family of each legal level and checks the scoped source tree when a label has multiple possible meanings. Local qualifications include item and subitem scopes. The grant regression checks that both the public-hospital condition and the 50% match reach the grant owner.

Reconciliation binds each page to the preceding item with a hash. The server carries forward validated citations, merges the page's additions, and replays that merge during publication checks. The 300-record regression retains all 301 citations for one item under the existing request and output ceilings.

All reader stages identify ambiguous provider dispatches independently of planner freshness. The migration tests use reservation hashes captured from commits `563c64c`, `1365612`, `acf4eba`, and `2327c54`. They cover mapping, dependency review, and summary generation with ambiguous, ready, failed, and validated reservations. A separate durable-provider test simulates an unknown outcome, retries after a planner change, and checks that a different page can still proceed.

## Verification boundary and rollout

These checks establish executable bounded planning for the real source and successful staged orchestration for the annotated offline cases. They do **not** establish the factual quality of a live model's complete S.1071 enhancement. The final provider matrix intercepts serialized requests at the HTTP boundary. The acceptance results cover offline adapter contracts and deterministic publication. Live model quality and billing are outside these checks.

The existing provider adapter remains the default. The reader execution version changes, so newly built confirmations and work identities include the new behavior. Existing published results and unrelated working-tree changes are preserved. Deploy through the ordinary reviewed backend release process; do not rewrite active attempts or regenerate all bills automatically.

## Reproduction

With the backend's installed environment and a disposable test database:

```sh
LARGE_BILL_XML_PATH=/path/to/BILLS-119s1071eah.xml .venv/bin/python -m pytest \
  apps/legislation/tests/test_large_bill_planning_regression.py -q -s

.venv/bin/python -m pytest apps/legislation/tests -q
```

For the PostgreSQL estimate and worker-claim check, set `DATABASE_URL` to a disposable PostgreSQL database on an existing instance and set `LARGE_BILL_XML_PATH` to the same XML. Run `apps/legislation/tests/test_large_bill_staged_flow.py::test_pinned_pg_confirmation` with `-s` to print the exact confirmed ceilings. The test compares the API budget with the stored manifest and claims the attempt without calling a provider.

The other staged-flow cases use a deterministic provider. To include the browser assertion, point `STAGED_READER_CLIENT` to a local test build of the client and install its Playwright Chromium browser. The test starts its own API against the isolated test database, logs in, and checks the published summary, policy and money tab.

The XML is deliberately not bundled into the application. The fixture verifies its pinned hashes before the full-source tests run.
