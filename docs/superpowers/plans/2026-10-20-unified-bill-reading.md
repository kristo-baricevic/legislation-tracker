# Unified Bill Reading Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task in the main agent. No subagents.

**Goal:** Replace the separate AI report with supported, ID-bound explanations in the existing bill page.

**Architecture:** Immutable NLP items remain the complete reader inventory. Schema 1.4 AI results supply private explanations keyed to that inventory; a shared frontend resolver selects compatible explanations without changing facts or dropping items.

**Tech Stack:** Django, existing provider adapter/Celery workflow, Next.js/React, pytest and existing frontend component tests.

**Spec:** `docs/superpowers/specs/2026-10-20-unified-bill-reading-design.md`

## Implementation outcome — October 20, 2026

Tasks 1–3 are implemented on `codex/unified-bill-reading`; the checklist below
records the original acceptance plan. Verification: 1,406 backend tests passed,
15 skipped; 176 frontend component tests and 59 API tests passed; TypeScript and
`git diff --check` passed. Local API reloaded and `/health/` reports all checks OK.
The updated main worker is running. No paid requests, backfills or pushes occurred.

H.R. 7583 dry preflight includes all 16 financial targets: 390 eligible targets
out of 399, with nine external definitions explicitly excluded. Shared context
is deduplicated across each batch. The plan contains 50 calls, which will be
shown for explicit confirmation before any regeneration.

The remaining acceptance step is human review of **newly generated** H.R. 7583
wording, after separate paid confirmation. Frozen source tests verify policy
thresholds, fines, wage formulas and effective dates are supplied together;
they cannot prove the semantics of a future model response. Existing legacy
output is preserved, not relabeled as schema 1.4.

## Global constraints

- Main agent only; RTK for shell commands; preserve the dirty checkout and local stack.
- No paid calls, automatic regeneration, public AI writes, ingestion backfill, or enabling source-first.
- Keep all financial items accessible; do not match by heading, array position or semantic similarity.
- Keep existing schemas readable and separate source compatibility from format availability.
- Write failing behavioral tests before product code. Run complete backend/frontend suites and typecheck before completion.

## Review focus

1. Two contracts reuse an item ID: only the exact document/contract/hash match applies.
2. A financial explanation is unresolved or absent: amount, restrictions and pagination remain accessible.
3. A section-level deadline is not an exact provision deadline: no false narrow attachment.
4. Logout or historical selection: private/current content is cleared or preserved appropriately, never leaked or replaced by historical data.
5. Schema upgrade or failed refresh: compatible prior content remains accessible without silent paid regeneration.

## Task 1: Immutable targets and response contract

**Files**
- Add `legislation-tracker-backend/apps/legislation/enhancements/reader_targets.py`.
- Update `enhancements/schema.py`, `prompts.py`, `source_packet.py`, `types.py`, and `diagnostics.py`.
- Add `apps/legislation/tests/test_enhancement_reader_targets.py` and version compatibility tests in `test_enhancement_schema.py`.

**Interfaces**
- `build_reader_targets(document) -> list[dict]`: server-owned identity, original text, exact related facts, complete source context and eligibility.
- `validate_reader_explanations(output, targets, sources) -> dict`: rejects unknown/duplicate IDs, cross-target quotes and missing batch outcomes; accepts explicit unresolved outcomes.
- Schema 1.4: cited summary plus typed target outcomes. All original fact fields remain server-owned.

- [ ] Freeze H.R. 7583 target/source fixtures and independently verified policy/wage/financial assertions.
- [ ] Write and run failing tests for reused IDs, changed hashes, unknown IDs, duplicate/missing targets, unsupported quotes, unresolved outcomes and oversized context.
- [ ] Implement target assembly from existing contract/evidence and reader relationships; preserve section versus exact scope.
- [ ] Add schema 1.4 validation while keeping explicit 1.1/1.2/1.3 schemas and source-first validation unchanged.
- [ ] Run targeted schema/target tests; verify historic outputs still validate under their own version.

## Task 2: Generation and publication

**Files**
- Update `enhancements/source_packet.py`, `providers/openai.py`, `glossary.py`, `service.py`, `serializers.py`, `views.py`, and `apps/legislation/tasks.py`.
- Add `enhancements/reader_batches.py` for targeted batch execution.
- Extend `test_enhancement_tasks.py`, `test_enhancement_openai_provider.py` and enhancement API tests.

**Interfaces**
- `execute_reader_batches(initial, preflight, provider, api_key, checkpoint) -> ProviderResult`.
- Preflight exposes eligible/selected/unavailable counts and reasons, complete batch fingerprints, aggregate limits.
- Serializer supplies trusted target identity and resolved citation coordinates for successful results.

- [ ] Write failing worker/API tests: all targets returned or explicitly unresolved; missing targets reject; unknown usage stays unknown; revocation/source changes/lease loss prevent publication.
- [ ] Extend confirmed preflight and batch runner without resetting existing safety limits or allowing silent selection.
- [ ] Keep provider errors and batch progress diagnostics, no automatic paid retries, atomic publication.
- [ ] Test persisted publication through real task/serializer code using fake external provider responses.
- [ ] Test separate source compatibility versus format upgrade, and historical result preservation.

## Task 3: One reading view

**Files**
- Add `legislation-tracker-client/lib/reader-enhancements.ts`.
- Generalize `app/bills/[id]/ai-glossary-context.tsx` into shared reader enhancement state.
- Update `lib/api.ts`, `app/bills/[id]/bill-brief.tsx`, `financial-ledger.tsx`, `bill-enhancement-panel.tsx`, and `page.tsx`.
- Add `tests/components/unified-bill-reading.test.tsx`; extend glossary, panel and bill-detail tests.

**Interfaces**
- A pure resolver accepts current document/contract identity, target kind/ID, original text and private enhancement; returns a supported explanation or the original.
- Current active enhancement state is separate from selected history detail.
- Summary, provision, financial and glossary renderers consume the same resolver.

- [ ] Read installed Next.js guidance before frontend edits.
- [ ] Write failing tests for a single summary/report, in-place explanations, original disclosure, correct citation links and identity fallback.
- [ ] Add pagination/filter tests proving AI omissions cannot change the financial inventory.
- [ ] Test logout/account switching, stale source, historical selection, pending/failed refresh, legacy outputs and no-AI mode.
- [ ] Implement the resolver and readers using existing styles; keep structured facts adjacent.
- [ ] Move controls/history behind details; remove the duplicate default AI report, retaining historical viewing.
- [ ] Run complete frontend tests and typecheck.

## Task 4: Verification and handoff

**Files**
- Update `docs/AI_GLOSSARY.md` to describe the unified reader and compatibility.
- Extend existing reader evaluation fixtures/harness for missing conditions, amounts, scopes and inaccessible financial rows.

- [ ] Run full backend suite and report skips separately.
- [ ] Run full frontend suite and typecheck; inspect the rendered fixture with/without enhancement.
- [ ] Manually verify H.R. 7583's grouped policy and tipped-wage explanations against the frozen source; do not claim semantic accuracy from citation matching alone.
- [ ] Confirm no new paid calls or regeneration occurred, and keep the existing stack running.
- [ ] Report implementation/test results. Request separate confirmation before regenerating H.R. 7583 under schema 1.4.

Implementation begins after review of this written design and plan. Do not bundle a commit or push of unrelated existing work.
