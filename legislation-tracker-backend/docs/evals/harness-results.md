# Bill enhancement harness evaluation, November 24, 2026

The two shorter bills passed offline preflight at all three experimental chunk sizes. S.1071 stopped before dispatch at every size. The existing transport remains the default. No provider was called for these nine runs, and none of them produced an enhancement suitable for factual or readability review.

## Source-pinned preflight results

These are aggregate reservation ceilings for an entire bill, including recovery and synthesis. The input estimate uses UTF-8 bytes plus message overhead. The output ceiling includes reasoning and visible tokens. Planning time measures one local run of the management command. Generation latency, correction rate, actual provider token use and comparative output quality are unmeasured.

| Bill | Owned target | Planned calls | Max calls | Max estimated input | Max output | Missing-context chunks | Planning seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H.R.9300 | 1,000 | 22 | 47 | 3,556,288 | 804,000 | 0 | 0.362 |
| H.R.9300 | 2,000 | 17 | 37 | 2,861,897 | 644,000 | 0 | 0.224 |
| H.R.9300 | 4,000 | 14 | 31 | 2,443,750 | 551,000 | 0 | 0.239 |
| S.4387 | 1,000 | 18 | 40 | 3,041,997 | 688,000 | 0 | 0.211 |
| S.4387 | 2,000 | 14 | 32 | 2,503,016 | 560,000 | 0 | 0.169 |
| S.4387 | 4,000 | 13 | 30 | 2,366,477 | 529,000 | 0 | 0.110 |
| S.1071 | 1,000 | — | — | — | — | 539 | 3.024 |
| S.1071 | 2,000 | — | — | — | — | 258 | 2.199 |
| S.1071 | 4,000 | — | — | — | — | 126 | 2.164 |

Each run verified the official XML and extracted-text hashes against its fixture manifest. The configured model was `inclusionai/ling-3.2-flash:free` with a context window of 1,048,576 and a provider output limit of 262,144. The application also applies its own per-request limits. The parser hashes in the manifests identify the implementation inspected during this evaluation. The original ingestion-time revision is unknown.

S.1071 has 1,134 official sections. Its inventory covered the 3,370,908-character source, including the sampled Sections 8805 and 8806. The planner retains the governing parent and linked provisions when splitting owned text. Some of those dependencies span hundreds of thousands of characters. Reducing owned text alone cannot bring those requests under the cap. The next large-bill change needs a way to narrow the governing passages while preserving conditions, definitions and exceptions. A human-reviewed, whole-bill financial inventory is still outstanding.

To reproduce the table, run the following against the pinned source archive, replacing the manifest filename for each bill. It uses local source storage and makes no generation request.

```sh
rtk proxy .venv/bin/python manage.py estimate_reader_variants \
  apps/legislation/tests/fixtures/harness/119s4387is.json \
  --provider openrouter --model inclusionai/ling-3.2-flash:free \
  --context-tokens 1048576 --output-tokens 262144
```

## Verification

| Check | Result |
| --- | --- |
| Full backend suite with disposable PostgreSQL | 2,048 passed, 3 skipped, 2 subtests passed |
| Full backend suite with SQLite | 2,032 passed, 20 skipped, 2 subtests passed |
| Final PostgreSQL regression run covering credential changes, chunk pinning, adapter pricing and concurrent reservations | 48 passed |
| Frontend component and API suites | 393 component tests and 59 API tests passed |
| TypeScript and Django migration checks | Typecheck passed and Django detected no missing migrations |
| Chromium browser checks with simulated generation | 2 passed with the normal configuration, 1 passed with source-first enabled |

The full suites ran during implementation. The final PostgreSQL regression run includes the subsequent chunk-target pinning and free validation routing fixes. Both full suites reported two existing Django constraint deprecation warnings. PostgreSQL skipped the SQLite fallback, an opt-in recommendations benchmark and a Redis integration test. SQLite also skipped PostgreSQL-specific locking, partitioning, search and isolation tests. Redis cross-process behavior was unverified in these runs.

The PostgreSQL barrier tests used separate connections. Two accounts confirming the same source received the same attempt. Two competing reservations limited to one dispatch produced one simulated provider call. Rotating the saved key before reservation produced zero calls. A disposable migration test checked rollback with a single key and preserved the encrypted envelope and its primary key.

Implementation commits are `d9d2680` (baseline), `de5949d` (pinned evidence), `9a3ca32` (harness and UI) and `a73a361` (worker chunk-target pinning).

## Publication evidence and rollout decision

The regression fixtures distinguish S.4387's annual authorization from actual spending and distinguish the two different percentage bases in H.R.9300. Attempt 113 is the historical S.4387 failure used for the paired transport probe. After explicit authorization, both adapters dispatched the same recorded request to OpenRouter with `inclusionai/ling-3.2-flash:free`, a zero-price routing ceiling and SDK retries disabled. The request hash was `0bab3ef671e2a775b2e286be02ecf089e5882e0b97631618bbcdf30c858f82bd`. Each call reserved 18,006 estimated input tokens and 24,000 output tokens, totaling 84,012 against the authorized 90,000.

| Adapter | Elapsed | Outcome | Provider usage |
| --- | ---: | --- | --- |
| Direct | 120.987 s | Client deadline exceeded. Upstream completion unknown. | Unreported |
| LangChain | 1.126 s | Rate limited. | Unreported |

Neither call returned visible output or a confirmed resolved model. The two calls exhausted the authorization, so neither was retried. The results do not distinguish model quality, adapter reliability or schema compatibility. The full-bill cold/warm comparison remains outstanding.

The browser checks used a simulated provider with real Django, worker, database and Chromium processes. Legacy, source-first and schema-1.4 results survived reload. The schema-1.4 case displayed the cited $100 rural-hospital grant in both Summary and Money. Desktop and mobile screenshots cover account settings, the Original view, the estimate dialog and the enhanced Money view. The browser test also opens the numbered source with Enter and restores focus with Escape. Queued, running and failed states have component coverage. Visual checks of those transient states and touch-device behavior remain outstanding. Screenshots and offline fixtures do not establish how a live model interprets these three bills.

The OpenRouter LangChain transport and chunk targets remain opt-in. Native providers retain their existing transports. There is insufficient evidence to select a different default or enable a production canary. Rollout, credential migration and rollback instructions are in [LLM enhancements](../LLM_ENHANCEMENTS.md).
