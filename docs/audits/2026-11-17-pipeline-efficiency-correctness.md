# Pipeline efficiency, cost and correctness audit

Date: 2026-11-17. Historical pre-fix audit of commit 1636fa2 plus the then-uncommitted similarity changes. Findings below describe that baseline, not the repaired head. See [implementation status](../superpowers/plans/2026-11-17-pipeline-integrity-and-reuse.md) for fixes and remaining work. This is not a production certification. No paid model requests, live FEC requests, deployments or application data changes were made.

## Conclusion

There is no local GPU inference in the inspected stack. Deterministic extraction, PDF parsing, topic classification and similarity use CPU/RAM/database resources. OpenAI does the model inference remotely; we control its cost through requests, input/output tokens, reuse and validation. Adding a GPU server would not fix the identified problems.

The most important work is **correctness validation plus a shared, resumable, section-level fact pipeline**, not larger model requests or higher blanket limits. Existing code already has useful durable steps, citations, source identities and sharing; extend those rather than build another parallel pipeline.

## Reproduced findings

### P1 — Real citations do not establish financial accuracy

Location: `apps/legislation/enhancements/reader_discovery.py:164`, `:206`; `reader_targets.py:109`.

An offline probe supplied a source explicitly providing **$10,000**, with generated money and policy explanations claiming **$1 billion**. Citation resolution, stored-source-review validation and the final schema-1.4 publication validator all accepted it. The quote exists, but does not support the claimed number.

Fix: extract typed monetary claims with amount/range/formula, unit, percentage base, actor, action, mandatory/optional status, timing and evidence offsets. Validate those against the source before prose is eligible for publication. Distinguish an allowed calculation from an extracted amount. Add adversarial amount/base/modality/eligibility mutations to the whole-bill benchmark. Deterministic checks still do not replace semantic/human review of legal effects.

### P1 — Missing financial provisions can pass the model's own coverage check

Location: `reader_discovery.py:148`, `:164`, `:206`.

A second probe omitted the explicit $10,000 grant entirely, classified its passage as `not_financial` and `context`, and passed both discovery and stored-review validation. This happens when the NLP inventory missed the item too. The safeguard requires citations for passages the model calls financial; it does not independently establish that a rejected passage is nonfinancial.

Fix: retain an independent source inventory of monetary markers and operative funding language. Every candidate needs a validated disposition: extracted, duplicate of an identified fact, contextual with a supported reason, or unresolved. Do not silently treat unresolved as absent. Check every source block, not only high-ranked or NLP-recognized blocks.

### P1 — Splitting a large bill can retain the oversized input

Location: `reader_discovery.py:73–112`; `reader_batches.py:215–240`; `reader_sizing.py:19`.

A synthetic 168,015-byte section split into 17 chunks, but each carried the full section as `section_context`: **2,856,255 context bytes across requests**. Each context alone exceeded the default 120,000-byte request limit. Splitting after output truncation also keeps the source/context and narrows the reviewed passage IDs; it reduces output obligations, not necessarily input duplication.

Fix: partition operative clauses, retaining exact dependency references to shared definitions, exceptions and governing conditions. Supply only necessary dependencies. If a complete interpretation still cannot fit, record that unit as unresolved or use another bounded stage; never truncate away its conditions. Size both input and expected output before making the first paid request.

### P1 — Long bills hit an all-or-nothing plan limit

Location: `reader_batches.py:282–296`; settings `LLM_READER_MAX_CALLS=64` by default.

A 426,982-character, 70-section synthetic bill with **zero NLP targets** was rejected with `Complete reader plan exceeds configured call budget`. More targets add further calls. Raising output tokens does not solve this limit.

The alternative source-first path is not an immediate fix: it defaults off and its planner caps generation at four calls, eight units per batch, and 48,000 total output tokens (`provision_pipeline.py:131–228`). It also needs a large-document design before enabling it broadly.

Fix: persist a work plan with bounded calls, independent checkpoints and an approved total spend. Process the whole source over multiple deliveries instead of requiring everything to fit one monolithic attempt. Keep previously validated work. If approval runs out, pause with explicit remaining coverage—not a false complete analysis or a restart from zero.

These are reproduced failure classes, **not proof of the cause of the user's particular historical hundred-page failure**. Its attempt diagnostics were not retrieved in this audit. Page count itself is not the correct sizing unit.

### P1 — Whole-bill summary is generated from only a subset

Location: `source_packet.py:124–185`; `reader_batches.py:136`, `:309`.

A 182,982-character synthetic bill produced a 31-call plan, but its summary request contained only 79,256 source bytes and was marked truncated. The summary runs first; the later complete source reviews do not feed back into it. Large-bill summaries can therefore miss later policies even when detailed extraction succeeds.

Fix: generate the summary last from the complete validated fact inventory. For very large inventories, combine section-level facts into chapter-level facts, then into the short summary; retain source IDs and an explicit coverage manifest at every stage. Do not ask the summary to enumerate all money; keep the complete financial inventory in the money tab.

## Cost and CPU findings

### P2 — Repeated interpretations and request overhead

H.R. 10906's 56,995-byte fixture produced **20 planned calls**, 28 including the retry reserve, and **963,324 bytes of serialized planned request envelopes** before retries. The configured maximum output allowance was 647,000 tokens across calls/reserves. These are planning bounds and envelope sizes, **not actual tokens billed or actual dollars spent**. Large `max_output_tokens` values are not charged unless output is generated.

The plan separately rewrites NLP targets and performs full-source policy/financial discovery. The same material is consequently revisited. Exact source/citation metadata and schemas also contribute substantial overhead. Input estimates use one token per UTF-8 byte: safe but intentionally pessimistic, not a realistic cost estimate.

Fix: one validated fact inventory should feed summaries, policy cards, money and glossary explanations. Cache unchanged sections and their dependencies across versions; use a model-aware token estimate plus a safety margin and actual per-stage usage measurements. Avoid a second paid prose pass where local grouping can produce the same result.

### P2 — Preflight and usage accounting repeat expensive CPU/database work

Location: `tasks.py:1354`, `:1431–1450`; `source_first_worker.py:115`.

Every reader checkpoint rebuilds the complete preflight before the next call. The measured H.R. 10906 preflight took **1.756 seconds** on the local host, with a tiny synthetic database. It includes targets, citation catalogs, serialized schemas, source scanning and reuse validation. Repeating this for each call is avoidable. `step_usage` also loads whole step objects, including saved results, merely to add token fields.

Fix: freeze a validated plan once. Before each dispatch, check lightweight document/contract/configuration/credential revisions and the run lease; rebuild only when those change. Sum usage in SQL, preserving unknown usage as unknown, rather than loading model outputs repeatedly.

### P2 — Partial paid work is not globally shared; cost accounting is incomplete

Location: `reader_steps.py:29`; `shared.py`; `providers/openai.py:22`, `:110`.

Completed compatible enhancements are shared across users, and validated steps are reused within an enhancement. However, the step lookup is scoped to `enhancement_id`. A different user's new attempt after a failed run cannot reuse its validated partial steps. Changing a whole-bill plan/version can likewise prevent reuse of otherwise unchanged section work.

The adapter deliberately disables implicit prompt caching without adding explicit breakpoints. Usage stores input/output/total tokens but not cached reads, cache writes, pricing version or a reserved/actual dollar ledger. Call ceilings are not dollar ceilings, and repeated user-approved attempts have separate ceilings.

Fix: share validated public-bill steps by content/dependency hash, model, prompt and validator version, while keeping payer credentials and billing history private. Add a durable spend reservation before each call, reconcile actual usage afterward, and retain reservations for ambiguous outcomes. Enable prompt caching only for stable prefixes with measured reuse, accounting for cache-write charges. Do not silently change retention/privacy policy.

For noninteractive backfills, the provider's [Batch API](https://developers.openai.com/api/docs/guides/batch) advertises 50% lower costs and a 24-hour completion window; check model support and preserve the same validation and billing controls. Interactive Enhance should retain its immediate queue. [Prompt-cache documentation](https://developers.openai.com/api/docs/guides/prompt-caching) describes explicit breakpoints and cached-read/write usage fields; savings are workload-dependent.

### P2 — Not every ingestion stage is resumable or change-aware

Locations: `tasks.py:662–707`, `:375`; `apps/ingestion/tasks.py:1802–1840`, `:2405`; `apps/congress/relationship_sync.py:88`; `apps/ingestion/congress_client.py:335–397`.

Contract generation performs extraction before computing the output hash used to detect duplicates. Unchanged bill metadata still runs topic inference over flattened contract text. Extraction itself is one whole-document CPU stage, not section-checkpointed. Bill-action and relationship helpers fetch all collection pages in one task; a later page failure replays earlier requests. Existing per-request deadlines do not bound the total of several requests within a 60-second durable delivery.

Fix: key extraction and topic projections by source hash plus all relevant parser/taxonomy/presentation versions before heavy work. Add section checkpoints for oversized extraction jobs. Persist fetched relationship/action pages in a staging snapshot with cursor and source identity, then atomically promote only after the complete collection validates. Never remove relationships based on a partial fetch. Existing immutable source preservation and bounded downloads should remain.

### P2 — Finance still spends unnecessary CPU and database round trips

Locations: `apps/campaign_finance/research.py:21–48`; `fec_client.py:70–78`.

Finance does checkpoint each page and prioritizes official totals/filtered schedules, which is good. However, contributor identities and transactions are looked up/inserted individually for every receipt. The HTTP reader iterates one byte at a time up to a four-megabyte response bound. Both costs multiply across ten years of receipts.

Fix: batch-fetch identities and existing transaction keys, bulk-insert validated rows, and retain the existing changed-record/duplicate/refund checks. Read bounded network chunks with total/read deadlines. Continue reusing completed historical snapshots while supporting explicit amendment-aware refreshes; append-only incremental fetching alone is not safe for amended filings.

### Queue fairness risk

An enhancement currently runs all its calls inside one Celery task on a one-process enhancement worker. Long bills block later bills even while waiting on the provider. Pending enhancement dispatch leases expire after 60 seconds and may republish queued messages; atomic claims prevent duplicate paid execution, but not duplicate broker traffic. Use bounded admission and one/few durable call steps per delivery, with round-robin fairness across bills. Keep ambiguous-provider-outcome protection; do not blindly retry a possibly charged call.

## What is already worth keeping

- No local GPU/model server cost; dedicated enhancement and research queues.
- SDK retries disabled; ambiguous outcomes do not automatically trigger another paid call.
- Shared successful bill results, validated step caching, run-token/lease checks and source fingerprints.
- Structured outputs, exact source offsets and publication validation (but not sufficient semantic accuracy).
- Download byte/page/text limits, checksum handling, original-source storage, durable ingestion retries and finance cursors.
- The previous turn's similarity feature cache, bulk writes and atomic checkpoints; unchanged completed bills are skipped. Initial all-pairs initialization remains quadratic.

## Recommended implementation order

1. **Financial correctness gate:** turn the wrong-amount and missing-money probes into failing regressions; protect amounts, bases, modalities and meaning-changing conditions.
2. **One source-first fact plan:** bounded clause/dependency chunks, stable IDs, complete coverage accounting, reusable validated facts, and summary-last composition.
3. **Durable execution and spend controls:** per-step checkpoints, fair scheduling, shared partial-result reuse, measured token sizing, dollar reservations and explicit ambiguous outcomes.
4. **Ingestion hot paths:** early unchanged checks, cached topic features, resumable large-document extraction/collection snapshots, bulk finance persistence and chunked response reads.
5. **Benchmark:** short, 100-page and omnibus fixtures; oversized single sections, dense financial tables, long definitions/cross-references, Unicode and quoted amendments. Inject truncation, interruption, rate limits and source changes. Record source coverage, critical factual errors, input/output/cache tokens, dollars per accepted provision, retries, reused calls, wall time, peak RSS and SQL counts. Keep readability separate from factual correctness.

Do not solve cost by dropping financial items, shortening away conditions, selecting only the first pages, removing validation, or silently increasing the approved spending limit.

## Evidence and reproduction

`docs/audits/pipeline_efficiency_probe.py` contains six **audit characterization probes**. Their passing assertions confirm the observed defects/current planning behavior; they are not release acceptance tests. They use a fresh test database and no model API. Run from the backend with the project's Python environment:

```sh
rtk proxy python -m pytest -c pytest.ini -s -q ../docs/audits/pipeline_efficiency_probe.py
```

Observed: 6 probes passed in 13.13 seconds. They cover oversized section-context duplication, large-plan rejection, truncated summary coverage, the real H.R. 10906 plan shape, unsupported amounts passing final publication validation, and missed funding passing discovery validation. Separately, 80 existing reader-discovery, reader-step, sizing, enhancement-service/pipeline and finance/research-history tests passed in 7.82 seconds. Their green status does not cover the newly demonstrated gaps. Actual model accuracy, invoice amounts and the specific historical failure remain unverified. No production code was changed by this audit.
