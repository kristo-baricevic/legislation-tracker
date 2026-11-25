# Large-bill staged processing — November 25, 2026

## Problem and implementation

The November 24 harness stopped before generation for S.1071 at every experimental chunk size. Splitting the owned section did not bound the supporting definitions, conditions, and cross-references attached to it. A safe rejection demonstrated the guard, not successful large-bill processing.

The reader now handles that case through the saved plan's stages:

1. **Map bounded source owners.** Preserve official XML ancestry, exact offsets, table structure, and complete nonoverlapping source ownership. Small source dependencies can still be supplied directly. When a complete request cannot hold its dependencies, retain exact deferred source/quote obligations and map those sources independently. Repeated nonblank passages are subdivided into uniquely citable owners rather than disappearing behind null quote IDs.
2. **Retain cited factual records.** The existing discovery result and durable work/cache records hold actor, modality, affected people, money/base/unit, timing, definitions, references, and nested `all`/`any` conditions and exceptions. The contracts extend the existing source-first factual schema; there is no new database or parallel fact store. Every assigned citable passage must have exactly one factual record.
3. **Reconcile bounded dependency pages.** Every deferred owner/item/record relationship needs a validated receipt. Receipts bind source evidence, record hashes, earlier revisions, and exact ownership. Applicable conditions must retain their citations. Earlier checked evidence is represented by retained citation IDs in later requests; its original text and factual records remain available to server validation. Missing, altered, duplicated, misassigned, or unresolved pages cannot pass the publication barrier.
4. **Synthesize in bounded groups.** The existing recursive summary reducer runs after reconciliation. If one finding has an oversized citation inventory, its evidence is paged for summary generation without modifying the original finding or factual inventory. A reducer that makes no progress still stops instead of silently dropping a group.

All generation stays inside the existing pinned provider/model, durable reservation, shared cache, retry, and delivery mechanisms. Preflight reserves map, dependency, recovery, and synthesis work. Each actual dispatch must fit the complete serialized request and its output allowance. No SDK retry loop or automatic model/provider change was added.

Internal factual maps and reconciliation receipts remain in saved validation state; the public presentation returns reader prose and its original cited sources. Existing schema-1.4 presentation and small-bill compatibility are retained. There are no database migrations.

## Source-pinned large-bill check

Source: `BILLS-119s1071eah`, the House engrossed amendment of S.1071 in the 119th Congress.

- Official XML SHA-256: `69702b764640a8bd86dbc23717cd3161b091668792d6b066a55a42d8e3a64299`.
- Extracted text SHA-256: `7e9a1eb347efd5094b047ad8f797aba9e8c9e1929b43bf946520d19d48b89385`.
- 1,134 official sections and 3,370,908 extracted characters.
- Per-request application limits: 100,000 estimated input units and 120,000 serialized bytes. Estimates remain conservative UTF-8 byte bounds, not measured model tokens.

All four complete planning variants pass:

| Owned target | Owned chunks | Map requests | Initial planned calls | Largest serialized request |
| ---: | ---: | ---: | ---: | ---: |
| Default (8,000-byte ownership target) | 914 | 2,367 | 2,368 | 25,492 bytes |
| 1,000 | 4,433 | 4,433 | 4,434 | 17,044 bytes |
| 2,000 | 2,421 | 2,446 | 2,447 | 18,293 bytes |
| 4,000 | 1,421 | 2,373 | 2,374 | 20,834 bytes |

Initial planned calls include one summary slot. Dependency and recursive-summary reservations are additional ceilings, not claims that every reserved call will be used. No provider was called by these tests. After the review corrections, all four complete variants were rerun: actual preflight took **31.165 / 89.446 / 43.252 / 35.001 seconds** for the default / 1,000 / 2,000 / 4,000-byte targets. Preflight plus the coverage/budget assertions took 45.965 / 94.949 / 47.423 / 41.985 seconds. The four-case test process took 274.067 seconds and peaked at **1,134,460 KiB RSS (about 1.08 GiB)**. The structural counts and maximum request sizes above were unchanged. These timings are local observations, not a controlled performance comparison.

Both the local Compose API and production image now give the API worker 120 seconds to complete a request. This accommodates large-bill estimate/confirmation planning instead of relying on a short default worker timeout. Generation itself continues in the existing resumable background worker.

Citation catalogs are reused only within one planning or worker operation. Discovery now constructs its actual verbatim-passage envelope directly instead of normalizing whole dependency sources and then discarding those copies. The recorded planning time is a local observation, not a measured generation-latency claim.

The pinned test also checks the source evidence governing sections 8805 and 8806. Conditions may be present directly or carried by exact, independently mapped deferred quote obligations; a smaller chunk size does not waive those checks.

## Behavioral verification

After all review corrections, the complete legislation backend suite completed **1,543 passed, 10 skipped, zero failures/errors**, with two passing subtests, in 165.10 seconds. Four skips were the full pinned S.1071 cases, which passed separately with the XML path supplied. The other six require PostgreSQL: two full-text/headline search tests and four concurrency/row-lock tests. Those six were not run in this SQLite environment. The four source-sized tests are additional to the 1,543 passing cases; repeated diagnostic runs are not counted as additional tests. Django system checks, the migration dry-run, Black, Ruff, and Git whitespace checks pass.

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

The reader execution version is now 12, and the context planner version is 2. There are no schema migrations. The new cache version applies only to dependency transport; existing mapped facts keep their compatible cache identities.

## Verification boundary and rollout

These checks establish executable bounded planning for the real source and successful staged orchestration for the annotated offline cases. They do **not** establish the factual quality of a live model's complete S.1071 enhancement. No new live model request, paid API call, production data change, or deployment was made for this implementation.

The existing provider adapter remains the default. The reader execution version changes, so newly built confirmations and work identities include the new behavior. Existing published results and unrelated working-tree changes are preserved. Deploy through the ordinary reviewed backend release process; do not rewrite active attempts or regenerate all bills automatically.

## Reproduction

With the backend's installed environment and a disposable test database:

```sh
LARGE_BILL_XML_PATH=/path/to/BILLS-119s1071eah.xml .venv/bin/python -m pytest \
  apps/legislation/tests/test_large_bill_planning_regression.py -q -s

.venv/bin/python -m pytest apps/legislation/tests -q
```

The XML is deliberately not bundled into the application. The fixture verifies its pinned hashes before the full-source tests run.
