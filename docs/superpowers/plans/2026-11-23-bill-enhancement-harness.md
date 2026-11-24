# Reliable Bill Enhancement Harness Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement this plan task-by-task. Work in one agent unless the user explicitly authorizes delegation. Steps use checkboxes for tracking. Read this entire document before implementation.

**Goal:** Deliver reliable, model-independent bill enhancement with per-user provider credentials and model selection, source-faithful chunking, resumable execution, and verified readable results.

**Architecture:** Retain Django/Celery orchestration, public-result reuse, evidence validation, and durable checkpoints. Introduce a thin LangChain-backed provider adapter and capability-aware request planning behind the existing provider protocol; benchmark it against the existing adapter before changing the default. This is a bounded document-processing workflow, not an autonomous Deep Agents application.

**Tech Stack:** Django, PostgreSQL, Celery, existing provider harness, Python LangChain provider integrations, Next.js/React/TypeScript, pytest, Vitest, Playwright. Pin compatible dependencies in the existing lock workflow; no paid LangSmith or managed agent platform required.

**Spec:** The product requirements and contracts below are the self-contained specification. Older enhancement design documents are historical context, not authority to override this plan.

## Product context: what this pipeline is for

Legislation Tracker ingests official US federal bills, versions, sponsors, votes, and source documents. A deterministic NLP pipeline creates an Original analysis. Users can optionally Enhance a bill through an LLM. Enhancement must explain the bill—not merely rewrite whatever the NLP happened to extract.

The intended reader has no legislative training, roughly a 12-year-old's familiarity with government. Use clear adult-respectful language, short sentences, and ordinary words. The primary page must answer in about 30 seconds: **What does it do? Who is affected? What money is involved?**

- Summary: normally two short sentences, approximately 30–45 words. Do not invent a spending total or stuff all eligibility details into it.
- What this bill does: concise, complete explanations grouped by actual policy change, not mechanical amendment fragments or duplicate headings. Paginate long results without layout jumps.
- Money: every material financial provision, including authorizations, appropriations, fees, penalties, allocations, tax rules, percentage bases, timing, restrictions, and exceptions. Distinguish permission to fund from funding actually provided or required.
- Key terms, votes/sponsor, and versions remain existing tabs. Details and source passages use numbered accessible tooltips, not expanding walls of text under summaries.
- Original and Enhanced are reading modes, not two separate piles of analysis. UI copy is **Enhance** and **Enhanced**, never “AI-enhanced.”
- A job is not product-complete merely because it returns JSON or a green status. Correctness, coverage, and readable rendering are acceptance requirements.

## Global constraints

- Use `rtk` for every shell command, including the first inspection, tests, Git, and package management. Follow repository instructions and GitHub credential/escalation policy. Referenced RTK.md was not found in the inspected checkout; do not invent its contents.
- No subagents unless explicitly authorized. This document is a handoff, not permission to spawn agents.
- Preserve unrelated local changes and existing data. Do not reset the checkout, purge queues, delete saved results, or reset databases.
- Do not manually write an improved summary into the DB and call that pipeline verification. All acceptance outputs must come from the real application pipeline.
- No bill-specific production branches. Bill IDs below identify regression fixtures only.
- Do not silently change a user's model, provider, key, reasoning choice, or free/paid selection. Never fall back from free to paid without a new confirmation.
- Loading estimates, opening a modal, changing a model, or viewing a bill must not start enhancement. Explicit confirmation is required. Credential validation must disclose if it requires a billable test request.
- Reuse a valid shared enhancement for the exact source version across users. Private credentials and attempt diagnostics remain account-scoped. Do not attach a public result's visibility to its payer's account lifecycle.
- Preserve original analysis on failure. Do not call an unreadable fallback an enhancement or falsely claim complete coverage.
- No disabling citation, financial, or readability validation just to obtain success.
- Keep API/worker reloads scoped to affected legislation services. Do not interrupt XT, databases, unrelated workers, or an in-flight provider call without first establishing how it will be recovered.
- Plan-only handoff: do not infer permission to spend an unlimited amount on experiments. Initial comparison uses the already configured free provider; for paid runs obtain a current explicit dollar cap. Bound free experiments as well.

## Handoff state and evidence (snapshot, November 23, 2026)

Repository: `legislation-tracker` under `/Users/kristo/Documents/Codex/2026-08-19/kristo-baricevic-legislation-tracker-https-github`.

Branch at inspection: `codex/bill-discovery-and-reader-fixes`. There are numerous **uncommitted backend changes** in model selection, provider transport, reader planning/cache/validation, and tests. Preserve and review them; do not assume they are all correct or deployed. `.superpowers/` is unrelated/untracked. At implementation start, record the branch, Git HEAD, relevant working-tree diff and running image identity. Compare the worker code with the checkout before attributing a live failure or success to local changes. Scope commits by hunk where files already contain unrelated edits.

Known deployment: Docker Compose project `legislation-local`, `.env.docker`, frontend `http://localhost:13000`, API `http://localhost:18001`, dedicated `enhancement-worker`. Verify rather than assume current state.

### Regression bills

1. **Bill 15778 / S.4387, Protect Moms From Domestic Violence Act**, document **18636**, about 7,796 characters. This is the primary failing short-bill case.
   - Study of violence/abuse and maternal health; grants for education and innovative approaches; eligibility and priorities including Tribal entities; HHS guidance within two years; reporting within three years and every three years thereafter.
   - **$15 million authorized for each fiscal year 2027–2029**. Not an appropriation, not a mandatory allocation of that amount.
2. **Bill 463 / H.R.9300, Postsecondary Student Success Act**, document **511**. Check grants, eligible applicants, conditions, annual percentage reservations and their distinct bases. Do not claim “no money” merely because there is no fixed appropriation total.
3. **Document 18343**, large House amendment. Resolve and record its bill/version from the DB; use the official XML inventory and existing large-bill fixtures. Do not guess its title or select a different version silently.

Pin each source's document ID, version, XML/text SHA-256, and parser version in fixtures. Establish expectations from source text, not generated output. Local IDs are not portable identifiers; store Congress/type/number/version too.

### Observed failures—not hypotheses

- Attempt 110 / enhancement 86 for bill 15778: repeated output exhaustion, then malformed JSON; an early response contained period-only explanations that were accepted. The original malformed response body was not retained, so it cannot be reconstructed exactly from the diagnostic.
- Subsequent replay/live runs showed output budgets consumed predominantly or entirely by reasoning. Attempt 113 included a response reporting **24,000 reasoning tokens and zero visible output tokens**, despite a low-effort request.
- `openrouter/free` selected different concrete models between runs; a run pins its resolved model. Thus two bills using the same router are not necessarily testing the same model.
- Attempt 112 failed at `/policy_changes/4/text`: JSON-schema pattern rejection bypassed the existing bounded wording-repair path. Local code now classifies that case for correction.
- A partial result in attempt 113 said the Secretary “must allocate $15 million annually” although the source only authorizes appropriations. Local code adds a narrow amount-scoped safeguard, but it is **not a complete semantic validator**.
- Local changes also address punctuation-only explanations, old cache revalidation, and reasoning-starved output recovery. They need review; their successful tests do not prove a successful live result.
- A full suite reached 2,004 passed / 18 skipped before the latest authorization/cache changes. Later targeted tests were run; do not report that older total as verification of the final working tree.
- Attempt 113 was still running at the last observed trace. **Inspect its current terminal state before starting another run.** No successful readable final page was established during that investigation.
- Removing prose regexes from the wire schema was explored, but the replay also changed an output allowance. Do not claim a controlled experiment proved regexes caused the failures.

## Current code map

Backend root: `legislation-tracker-backend/`; frontend root: `legislation-tracker-client/`.

| Responsibility | Existing files |
|---|---|
| User keys/settings | `apps/accounts/models.py`, `llm_credentials.py`, `llm_serializers.py`, `llm_views.py` |
| Selected provider/model | `apps/legislation/enhancements/model_selection.py`, `provider_registry.py` |
| Provider protocol/transport | `enhancements/providers/base.py`, `openai_compatible.py`, `harness.py` |
| Source/XML planning | `enhancements/source_packet.py`, `xml_sections.py`, `source_sections.py`, `reader_discovery.py` |
| Capacity and packing | `enhancements/reader_capacity.py`, `reader_sizing.py`, `reader_batches.py` |
| Durable calls/reuse | `enhancements/reader_steps.py`, `reader_cache.py`, `service.py`, `shared.py`, models and task entrypoints |
| Validation and synthesis | `enhancements/reader_targets.py`, `reader_integrity.py`, `reader_partial.py`, `reader_summary.py`, `provision_validation.py` |
| Alternative processing path | `enhancements/source_first_preflight.py`, `source_first_worker.py`, `provision_pipeline.py` |
| Settings UI | `app/settings/page.tsx`, `tests/components/llm-settings-page.test.tsx`, `tests/api-llm.test.ts` |
| End-to-end UI | `e2e/llm-enhancement.spec.ts`; inspect its existing auth/setup before extending |

Paths beginning `enhancements/` above are under backend `apps/legislation/`. Inspect all implementations of the provider protocol, not just the OpenRouter path.

## Target contracts and design decisions

### A. Per-user credentials and settings

Current `LLMCredential.user` is OneToOne, so one user cannot retain separate keys for multiple providers. Migrate it to a foreign key with unique `(user, provider)`. Preserve existing credential PKs, encrypted envelopes, revisions, validated metadata, and attempt foreign keys. Do not change encrypted identity fields without re-encrypting through the existing helper.

Add `LLMPreference` with OneToOne user and nullable active credential FK. Each credential retains its last selected model. Validate active credential ownership server-side. Migrate existing users to their existing credential as active. Deleting an active credential clears the selection; deleting an inactive credential does not change the active selection. New users have no credential and no automatic paid request.

Settings: **Provider dropdown → Model dropdown → masked key status/key input → Save / Validate / Remove**. Preserve a provider's saved key when switching away and back. Free model options display a small “Free” label based on verified pricing metadata; unknown price is not free. Never return plaintext keys, store them in browser storage, or put them in traces. Use the existing session-auth and CSRF conventions.

Proposed API resources under the existing account API prefix (wire into the current URL module):
- `GET/PUT/DELETE llm/credentials/{provider}/` — current user's provider credential only; GET returns masked metadata, never the key.
- `GET/PUT llm/selection/` — `{provider, model}`; PUT validates ownership and model eligibility atomically.
- `GET llm/models/?provider=...` — cached selectable model metadata with capability/pricing freshness.
- `POST llm/credentials/{provider}/validate/` — current user's key/model validation, with explicit cost disclosure when necessary.
Preserve the registered model pair for the E2E fake provider in test settings. For a first-time provider, save its key and chosen model together before activating it. A failed save or selection leaves the previous selection intact. Keep existing clients working through compatibility handlers during migration, then remove them only when tests prove no callers remain. Do not let changing provider reuse the previous provider's secret.

### B. Thin adapter, not an agent rewrite

Add `providers/langchain_adapter.py` implementing the existing `EnhancementProvider` protocol. Keep Celery, validation, persistence, budgets, and retry decisions outside LangChain. Use direct structured model calls, not an unconstrained agent loop. Explicitly disable SDK/LangChain automatic retries so the durable dispatcher owns every retry and charge.

Normalize success, refusal, truncation, malformed output, auth errors, rate limits, timeouts, usage, concrete model, and response IDs to existing `ProviderResult` / `ProviderError`. A timeout has an unknown outcome; do not treat it as a known completed failed generation.

Add `model_capabilities.py` with `resolve_capabilities(provider, model) -> ModelCapabilities` and `token_budget.py` with `plan_request(envelope, capabilities) -> RequestBudget`. Contracts:
- `ModelCapabilities`: concrete model ID, context/output limits, tokenizer ID or explicit unknown, structured-output methods, reasoning controls, pricing/currency, provenance, fetched timestamp.
- `RequestBudget`: estimated input, estimator kind, max total output, requested reasoning allocation, reserved visible output, remaining-context margin, capability fingerprint.
- Unknown capabilities are not invented. Permit a clearly labeled conservative estimate where safe; unsupported required behavior must be explicit.
- Native reasoning token caps are preferred when supported. Effort settings are requests, not guaranteed enforcement; compare returned usage with the reservation and classify starvation separately from oversized visible output.
- Resolve dynamic routers before confirmation to a supported concrete model where feasible, using authoritative metadata/explicit configured eligible models, without a generation call. Show and pin that choice. Do not silently follow a router to an incompatible model. If metadata cannot establish eligibility, require a supported concrete selection rather than pretend it is known.
- No arbitrary API base URLs supplied by users; provider adapters use vetted endpoints.

### C. Chunking and synthesis

Preserve official XML hierarchy and exact source offsets. Split oversized sections recursively by subsections, paragraphs, sentences, then token-safe spans as a last resort. Preserve tables, list lead-ins, amendment boundaries, and source mapping. Every owned source span must be accounted for exactly once; additional context can be shared without duplicate ownership.

Build each request from owned passages plus necessary parent lead-ins, definitions, and explicit cross-references. Reuse the existing `source_graph.py` where applicable. Include dependencies transitively with cycle detection and a bounded context budget. Unresolved references—especially external statutes—must be recorded, not guessed. A byte/section coverage check does not prove interpretive completeness.

Do not blindly add 10–15% overlap or repeat an entire section in every request. Dependency context must be deduplicated, separately identified, and included in token estimates. Reducing output ownership does not necessarily reduce input size; report both.

Benchmark owned-text targets of **1,000, 2,000, and 4,000 tokens**, with the complete request always constrained by real model limits. These are experiment variants, not production defaults. Measure actual input/output/reasoning usage against estimates. Avoid a universal chars/4 tokenizer assumption; use exact tokenizers only for models they match.

Map phase: produce cited factual records with actor, legal effect/modality, affected people, monetary amount/base/unit, timing, conditions, and exceptions. Extend existing structures only where required; do not add an independent second fact store. Full-source discovery remains independent of the NLP inventory.

Reduce phase: generate readable summaries from validated findings and their supporting source passages. Fresh wording is permitted but must be validated against its evidence. Recursively combine bounded groups if necessary, preserving traceability. Do not force the summary to be a concatenation of extracted sentences or substitute punctuation/boilerplate for failed prose.

Keep execution sequential for the initial comparison. Add bounded concurrency only after correctness and resumability pass; it is a separate optimization, not necessary to prove the adapter works.

### D. Recovery, reuse, and publication

- Key completed work by source/dependency hashes, transformation/prompt/schema/validator versions, and relevant model configuration. Never include secrets in fingerprints or shared data.
- Revalidate older completed work under current checks; reuse valid portions and repair only invalid portions. Preserve successful siblings across retries, crashes, and account changes.
- New user key/model selections cannot silently mutate an active run. Rotation/deletion of the run's credential must safely stop future calls and require reconfirmation; a switch of active selection alone does not rewrite the pinned attempt.
- Confirmed budgets include estimated input, reasoning plus visible output, bounded retries, and final synthesis. Each dispatch reserves budget transactionally. Parallel users cannot pay for the same in-flight shared artifact twice.
- Reasoning-only response: record actual usage, use at most one supported bounded recovery for that request, then report model incompatibility/exhaustion rather than blindly multiplying subdivisions. Visible-output truncation: split only failed owned work while preserving dependencies. Malformed or semantically invalid result: targeted bounded correction, never relaxed validation.
- Publication requires readable complete policy explanations and supported money language. If a portion remains Original, expose accurate coverage in the existing source metadata and do not mark the whole analysis fully enhanced. Never publish empty bodies or “.”.
- Retain the sanitized provider-facing request and visible response for authorized debugging in a private, access-controlled diagnostic artifact, never in the public result. Redact credentials, headers, private account data, and provider hidden reasoning content; record reasoning token counts, not chain-of-thought. Store visible raw output/finish reasons/response IDs so rejected JSON can be diagnosed. Use the repository's retention conventions, document deletion, and never export traces to LangSmith by default.

## Review focus

1. Two users confirm the same bill concurrently: one shared generation, isolated keys and diagnostics (Tasks 2, 5).
2. A provider switch, key rotation, or deletion occurs mid-run: pinned execution cannot charge the wrong key/model (Tasks 2, 3, 5).
3. A distant exception or definition changes without owned text changing: cached interpretation invalidates (Task 4).
4. Model ignores reasoning/structured-output controls or times out: no invisible unlimited retries, paid fallback, or false success (Tasks 3, 5).
5. Valid JSON contains misleading money wording, empty explanations, or lost conditions: publication rejected/corrected; the actual screen stays usable (Tasks 5, 6).

## Task 1 — Freeze baseline and reproducible evidence

**Files:** Create `legislation-tracker-backend/docs/evals/harness-baseline.md`; extend existing fixtures under `apps/legislation/tests/fixtures/` and evaluation code under `apps/legislation/evaluation/`.

**Interface:** Produce three source-pinned fixture manifests and `evaluation/harness_comparison.py::run_comparison(case, adapter, model, variant, budget) -> ComparisonResult`. ComparisonResult records source identity, adapter/model, configuration hash, coverage/factual/readability outcomes, call count, retries, wall time, input/reasoning/visible tokens, and known/unknown cost.

- [ ] Inspect git status, running images, and bill 15778's active/latest attempt. Record the current state and timestamp. If still active, continue offline fixture work and capture the terminal state before a new live comparison.
- [ ] Capture the three source versions and manually verify answer keys with exact supporting passages. For each critical claim record the expected legal effect, evidence span and failure condition, including S.4387 authorization and H.R.9300 percentage bases.
- [ ] Write tests showing each known bad output fails its specific assertion; keep raw visible rejected fixtures isolated from accepted publication fixtures.
- [ ] Implement the comparison report with no automatic live calls; live mode requires explicit model and budget arguments. Default is fixture replay.
- [ ] Run fixture tests; record existing failures/skips honestly. Commit only this task's artifacts.

## Task 2 — Per-provider keys and active model settings

**Files:** Modify account model/credential/serializer/view files above, actual account URL registrations, `model_selection.py`, settings page and its existing tests. Create migration using the next available number and `apps/accounts/tests/test_llm_multi_provider.py`.

**Interfaces:** `get_selected_credential(user) -> LLMCredential | None`; `set_llm_selection(user, provider, model) -> LLMPreference`. For a new generation, bind the estimate to credential identity and revision as well as provider, concrete model, source, adapter, reasoning settings and budget. Verify those server-issued values under the selection lock at confirmation and persist them on the attempt. Revision alone can repeat after deletion and recreation. Exercise a stale estimate after deleting the credential and saving a new key for the same provider at revision 1: reject it with zero dispatches. Each subsequent dispatch checks the attempt’s original credential ID/revision. Test switching models on the same saved key as well as switching providers during an active run.

- [ ] Add failing tests: migrate an existing key without loss; save two providers; switch back without reentering keys; user A cannot access user B's credentials; malformed/unsupported model rejected; deletion semantics; rotation invalidates validation but retains history.
- [ ] Run those tests red, then implement the migration and account-scoped API without exposing plaintext. Test rollback on a disposable database snapshot; do not destructively reverse a populated multi-provider table.
- [ ] Replace all OneToOne assumptions (`user.llm_credential`, worker lookups, rotation command, settings APIs) with explicit selection/provider lookups. Ensure legacy compatibility cannot accidentally select an arbitrary credential.
- [ ] Add UI tests for provider/model dropdowns, Free badge, masked key status, stable loading/errors, and no generation on selection/save. Reuse existing form and modal styles.
- [ ] Test an upgrade with an old API/worker still using the one-row lookup. Keep multi-provider writes gated until all such readers and writers have drained or been upgraded. Rehearse rollback with two saved keys using a compatible application version and the expanded schema. Run backend credential tests, frontend settings/API tests, and typecheck. Commit the migration/API/UI together.

## Task 3 — LangChain adapter and capability-aware request planning

**Files:** Create `enhancements/providers/langchain_adapter.py`, `enhancements/model_capabilities.py`, `enhancements/token_budget.py`, and corresponding `test_langchain_adapter.py`, `test_model_capabilities.py`, `test_token_budget.py`. Modify provider registry, protocol only as needed, model catalog, preflight/estimate consumers, and dependency inputs/lock.

**Interfaces:** Preserve `EnhancementProvider` calls and normalized results. Implement capability/budget contracts from B. Treat the existing ProviderCapabilities as the adapter’s wire-format description. Combine it with model-specific limits and pricing. Fingerprint execution-relevant values, keeping fetch time as freshness metadata so identical metadata refreshes cannot invalidate every confirmation. Add a server-side adapter-selection flag defaulting to the existing implementation during evaluation.

- [ ] Write failing contract tests for each supported provider: native JSON, tool-based structured output where supported, refusal, malformed JSON, output truncation, reasoning starvation, rate limit, authentication error, timeout/unknown outcome, and absent usage/capability metadata.
- [ ] Test that provider and LangChain automatic retries are disabled; each reserved provider step produces at most one outbound generation request. Count actual transport requests in tests, including failed responses. Structured-output tool recovery must not introduce an unmetered agent loop.
- [ ] Implement adapter and capability caching with provenance/freshness. Use maintained provider integrations; do not assume an OpenAI-compatible URL implies identical capabilities.
- [ ] Test estimates include all instructions, source/dependency text, schemas, wrappers, output and reasoning. Show unknown costs/tokenizers honestly; never label byte counts exact tokens.
- [ ] Verify selection and estimate use the same pinned capability/model snapshot as dispatch. Changes between estimate and confirmation require a fresh estimate.
- [ ] Run adapter tests and perform the single paired S.4387 comparison specified in Task 6. Record the sanitized logical request, provider-facing differences, confirmed per-call limits and resolved model. If no concrete model is directly selectable on both adapters at verified zero price, mark the free comparison blocked and continue offline tests. Save redacted request/visible response and measured usage in the private diagnostic store. Put only metrics, sanitized fixture references and conclusions in the repository report. Do not enable LangChain globally on unit-test evidence.
- [ ] Commit the adapter plus test/report evidence. If it has no demonstrated benefit, leave it opt-in and report the result rather than forcing migration.

## Task 4 — Source-aware chunk planning and dependency coverage

**Files:** Modify `reader_discovery.py`, `reader_sizing.py`, `reader_capacity.py`, `reader_batches.py`, `source_graph.py`, `xml_sections.py`, and `reader_summary.py`; extend existing reader sizing/large-bill/work-plan tests.

**Interface:** `plan_reader_batches(document, capabilities, owned_token_target) -> existing EnhancementPreflight` (may wrap existing preflight functions rather than duplicate them). Each planned unit records owned spans, dependency spans, hashes, budget, and unresolved references.

- [ ] Add failing fixtures for a giant single paragraph/sentence, Unicode, decimal/statutory punctuation, quoted amendments, tables, nested list lead-ins, distant exceptions, external references, and cyclic internal references.
- [ ] Implement structure-first splitting with token-safe final fallback and exact byte/character source mapping. Assert complete non-overlapping ownership and no truncated source.
- [ ] Implement bounded dependency expansion, deduplication, and dependency-based cache invalidation. Do not claim “fully contextualized” when a required dependency cannot fit or be resolved.
- [ ] Wire the three experimental sizes into the comparison runner. Keep production configuration unchanged until real results justify a choice.
- [ ] Test recursive summary reduction preserves source IDs and critical findings and terminates when no size reduction is possible. Do not silently drop final groups.
- [ ] Run existing planner tests for document 18343 and all three pinned fixtures; report accounted/missing/duplicate sections and complete request estimates. Commit.

## Task 5 — Bounded recovery, factual publication gates, and reuse

**Files:** Modify `reader_steps.py`, `reader_cache.py`, `reader_partial.py`, `reader_integrity.py`, `reader_targets.py`, `reader_batches.py`, `service.py`, `shared.py`, and their existing tests; add `test_harness_recovery.py`.

**Interfaces:** Keep durable attempt/work-unit APIs; normalize failure classes through ProviderError and route each into exactly one documented recovery policy. ComparisonResult consumes persisted dispatch/usage evidence.

- [ ] Add red tests reproducing S.4387 punctuation-only output, schema-pattern repair bypass, authorization becoming mandatory spending, unsupported numbers, and wrong-source citations. Also add legitimate mixed authorization/mandatory-allocation examples to prevent over-rejection.
- [ ] Review existing uncommitted fixes against these tests; retain, correct, or replace them with explanation. Do not stack duplicate heuristics without understanding their interaction.
- [ ] Add reasoning-only and visible-truncation replay tests showing distinct recovery, fixed model identity, bounded calls/tokens, no repeated successful siblings, and no hidden SDK retries.
- [ ] Run the concurrent-confirmation and budget-reservation tests with separate PostgreSQL connections and a synchronization barrier. Assert one live generation, private attempt/diagnostic fields visible only to their owner, and a successful result still readable after payer deletion. Exercise legacy published schema versions and dependency-only changes through shared_enhancement as well as the per-call cache; require current validation or regeneration before stale results can be served. Add crash/reload/concurrent-user tests: before dispatch, after provider response but before checkpoint, partial validation, credential rotation/deletion, and changed dependency hash. An ambiguous timeout must not be replayed as though no call occurred.
- [ ] Keep diagnostics.py and API/log payloads allowlisted. Capture a sanitized request and visible response before parsing in a separate owner-scoped artifact, including rejected responses. Test access denial for another viewer of the same bill, expiry/deletion and omission of keys, headers and hidden reasoning in success and error paths. Export only redacted evidence approved for the report; preserve public-result reuse independently of private diagnostic ownership.
- [ ] Make factual/readability gates apply to initial generation, correction, cache reuse, and final synthesis. Do not equate numeric matching with semantic proof; manually review the pinned money/eligibility answer keys too.
- [ ] Run the full backend suite and report skips. Commit.

## Task 6 — Live comparison, visual verification, and controlled rollout

**Files:** Extend `evaluation/harness_comparison.py`, `docs/evals/harness-baseline.md`, existing enhancement E2E tests, and `docs/LLM_ENHANCEMENTS.md`. Put a final evidence report beside the baseline.

- [ ] Use the paired S.4387 evidence from Task 3 if its inputs and transport code still match. Across Tasks 3 and 6 allow at most two generation dispatches per adapter for this probe, including recovery. Compare identical source, schema, prompt, output and reasoning settings on the same concrete model. Record each dispatch separately. Advance only adapters that pass the failing batch’s source-based assertions. If neither passes, stop the live sweep and diagnose the failure. A single passing adapter can proceed to bill-level verification; report that the other arm failed.
- [ ] For cold comparisons, use an isolated disposable application database, cache and worker queue for each comparison arm. Seed the same source-only snapshot and provision the evaluation credential through the normal settings flow. Include any validation charge in the experiment budget. The bill lock, shared-result lookup, legacy step lookup and global call cache remain enabled. Assert that the intended adapter actually dispatched and record cache hits and provider usage. Run the warm and second-user checks in the same arm afterward. Keep existing local results intact.
- [ ] Before a sweep, record numeric aggregate call, token and cost ceilings across all arms, including validation, recovery and synthesis. Use a zero-dollar ceiling for free runs. Reserve worst-case cost before dispatch and retain the reservation for unknown outcomes. If pricing or enforceable limits cannot establish the ceiling, stop live work and report which comparison is outstanding.
- [ ] With transport verified, run each pinned bill through the real estimate → confirm → worker → validation → save → page flow. All calls must be authorized and metered. Do not use a direct DB result edit.
- [ ] Compare the three owned-token variants on the short and medium cases first. Expand only viable variants to the large bill. Reuse checkpoints only when configuration identity matches; separately report cold and warm-cache timings.
- [ ] Acceptance: zero known critical factual errors; all annotated money provisions accessible; all material claims supported by their own evidence; no omitted condition that reverses meaning; all source spans accounted for; readable Summary/What this bill does; no punctuation-only or clipped explanations. Passing mechanical checks is not a substitute for source-based human review.
- [ ] Compare total calls, input/reasoning/visible tokens, end-to-end time, correction rate, and price. No fixed speedup is promised. Adopt the adapter/chunk configuration only if it improves reliability or maintainability without factual regression or unexplained cost growth; document any tradeoff.
- [ ] Add a seeded schema-1.4 reader case to the fake-provider browser suite and assert that the saved reader projection is shown. Keep the existing legacy/source-first fixture for compatibility. Test the actual reader components under `app/bills/[id]/` and `app/components/EnhancementEstimateDialog.tsx`; fix any gaps in mode switching, specified copy, Money, pagination, citation keyboard/touch behavior and stable loading states. Include the corresponding component tests. The browser suite and live-provider bill runs produce separate evidence.
- [ ] Visually inspect Original and Enhanced modes, Money, numbered citations, estimate modal, queued/running/failed/succeeded states, and settings on desktop and mobile. Check no loading flash, modal resizing, button movement, or refetch-induced scroll jumps. Save screenshots and name which data is real versus simulated.
- [ ] Re-enhance the same exact version as another user: confirm a valid shared result is reused with zero generation calls. Change a source dependency and verify stale work is not reused.
- [ ] Enable a limited canary only if the comparison supports adoption. Otherwise leave the existing adapter as default and record that decision. For a canary, scope selection to newly confirmed attempts, persist the adapter version, and verify that toggling the flag affects future confirmations while previously confirmed work resumes on its pinned adapter. Rollback must not delete keys, results, or checkpoints. Do not automatically regenerate every bill.
- [ ] Deliver commit IDs, diff, full test results, evaluation run identifiers, sanitized model/capability snapshots, timing/token/cost tables, screenshots, remaining limitations, and rollback instructions. Keep provider request IDs and raw diagnostic artifacts in the private evidence store. Create/push a PR only if the executing user authorizes that workflow.

## Verification commands

Run from the named directory, using the environment actually installed there. Check dependency instructions before installing anything.

Backend (`legislation-tracker-backend`):
```sh
rtk proxy .venv/bin/pytest apps/accounts/tests/test_llm_credentials.py apps/accounts/tests/test_llm_settings_api.py apps/accounts/tests/test_llm_configuration.py -q
rtk proxy .venv/bin/pytest apps/legislation/tests/test_reader_sizing.py apps/legislation/tests/test_reader_work_plan.py apps/legislation/tests/test_reader_large_bills.py apps/legislation/tests/test_reader_enhancement_pipeline.py -q
rtk proxy .venv/bin/pytest -q
```
Add new test files from Tasks 1–5 to targeted runs; the full suite must collect them.

Frontend (`legislation-tracker-client`):
```sh
rtk proxy pnpm exec vitest run tests/components
rtk proxy pnpm run test:api
rtk proxy pnpm run typecheck
rtk proxy pnpm exec playwright test e2e/llm-enhancement.spec.ts
```
Use a dedicated disposable E2E database: scripts/start-e2e-api.sh removes the configured SQLite file or flushes the configured PostgreSQL database. Verify the E2E database target before running Playwright. Use the existing E2E authentication setup and disposable test data; do not overwrite the user's account or invoke paid enhancement from an unmarked test.

Repo root, read-only Docker inventory (request escalation as required):
```sh
rtk proxy docker compose --env-file .env.docker -p legislation-local ps
rtk git diff --check
```

## References and how to use them

- [Pinecone: Chunking strategies](https://www.pinecone.io/learn/chunking-strategies/): meaningful boundaries, context preservation, and empirical comparisons. Primarily retrieval/embedding guidance; not a universal 500-token recipe for legal synthesis.
- [LangChain structured output](https://github.com/langchain-ai/docs/blob/main/src/oss/langchain/structured-output.mdx): provider-native versus tool strategies and capability profiles. Verify the installed version and selected provider; dynamic router capability inference is not guaranteed.
- [LangChain model integrations](https://github.com/langchain-ai/docs/blob/main/src/oss/langchain/models.mdx): provider differences remain beneath the common interface.
- [Deep Agents](https://github.com/langchain-ai/deepagents): intentionally not adopted for this fixed workflow.
- [OpenRouter reasoning controls](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens): reasoning shares response capacity; supported controls differ by model. Verify actual usage rather than assuming low effort enforces a hard cap.
- The user's pasted Google example is an architectural sketch: map section findings, then reduce. Do not copy its splitter unchanged—it does not bound oversized single sentences or the final reduce request and has no durable recovery/citation contract.

## Completion and handoff checklist

- [x] Per-user keys for multiple providers work; active model selection is secure and preserved.
- [ ] LangChain adapter comparison is measured, not assumed superior.
- [ ] Chunk planning preserves source ownership and required context with honest unresolved coverage.
- [ ] Completed work survives retries; duplicate users do not trigger duplicate paid generation.
- [x] All three real bill runs and their actual pages are verified, or a specific remaining blocker is reported without a completion claim.
- [ ] Evidence includes actual model, provider request/response IDs, timing, token usage, and money semantics—not only pytest output.
- [x] No manual enhanced-content edits, unapproved model changes, paid fallback, or whole-database regeneration.

The implementation and offline verification are recorded in the [November 24 evaluation report](../../../legislation-tracker-backend/docs/evals/harness-results.md). The paired S.4387 live probe requires explicit authorization. S.1071 exceeded the context budget at each experimental target. The live bill comparison and rollout remain open.
