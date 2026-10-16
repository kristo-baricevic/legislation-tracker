# Source-First Bill Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This document authorizes no implementation, paid evaluation, deployment, or commits by itself.

**Goal:** Produce understandable bill explanations that retain material conditions and financial provisions, with backend-owned evidence and bounded repair of failed provisions.

**Architecture:** Build a version-pinned source graph, generate provision explanations with structured facts and passage references, then validate and repair only failed units. Neither the deterministic parser nor the LLM is a legal truth oracle: mechanically accepted output remains distinct from semantic review. Integrate the validated contract into the existing private enhancement lifecycle and reader UI; preserve the non-AI reader and historical outputs.

**Tech Stack:** Existing Django/PostgreSQL/Celery backend, provider-agnostic enhancement adapter with OpenAI implementation, JSON Schema, Next.js/React, pytest, Vitest, Playwright. No new orchestration platform.

**Spec:** The “Agreed design and acceptance contract” section below records the design agreed in this conversation. Read it alongside `docs/benchmarks/bill-understanding/hr1589-provision-first-review-2026-10-16.md` and backend `docs/COVERAGE_CANDIDATE.md` for current failures, not proof of completion.

## Global Constraints

- Plan/review only until implementation is requested. No services stopped, restarted, reseeded or backfilled; no paid API calls during planning/review.
- Preserve unrelated dirty worktree changes. Route all shell commands through `rtk`; read applicable repository/frontend instructions before execution.
- Do not put API keys, credential plaintext, raw provider exception bodies or private user analysis into logs or committed artifacts.
- Every explicitly annotated financial provision must remain accessible. Do not select only “consequential” items or truncate the ledger for presentation.
- A readable synopsis is required; legal titles and “no official summary” are not substitutes. A partial analysis must not masquerade as an exhaustive synopsis.
- Preserve mandatory/optional/prohibited effects, amounts, units, percentage bases, dates, exceptions and AND/OR conditions. Unknowns must not be filled from unstated outside law.
- Passage identity proves provenance, not that a claim follows from the passage. Structured fields are fallible claims, not authoritative labels.
- Existing user-owned API credentials, private overlays, tenant isolation, toggle behavior and explicit spending confirmation remain in force.
- No newsletter/RSS/GitHub Actions, unrelated dashboard work, model upgrade, or automatic public-analysis replacement.
- Existing per-call limits remain 120,000 serialized bytes, 100,000 conservative input units and 8,000 output tokens. Aggregate call/input/output bounds must be shown before confirmation; never silently widen them.

## Review Focus

1. A child clause sounds independently sufficient after losing its governing exception or AND condition (Tasks 1, 3).
2. A real passage from the same bill supports a different actor, amount or version (Tasks 2, 3).
3. Worker loss or source/credential changes between batches causes duplicate charges or mixed-version output (Task 5).
4. Parent headings duplicate child money items, while a financial provision without dollar notation disappears (Tasks 1, 7).
5. A polished synopsis hides an unresolved provision or silently drops a money item behind pagination (Tasks 4, 6, 7).

## Agreed design and acceptance contract

### Current evidence

H.R. 1589's provision-first experiment generated 31 candidate entries in four calls. Fee substitution and the previously missing eligibility conjunctions appeared, but the result still failed: mandatory fine weakened to optional, incorrect quotations, one overlong paragraph and a parent surcharge entry missing its amount. The inventory also previously classified “appropriate court” as funding and included contents entries. These are frozen regression inputs, not grounds for weakening checks.

The current `evaluation/provision_generation.py` experiment is not wired to the production worker. Its limits of eight candidates per batch and 32 per experiment are experimental, not permanent application coverage limits. Existing production schema 1.2 and legacy 1.1 must remain readable.

### Source and output contract

Use immutable identifiers derived from document-version identity, decoded-text hash, offset range and normalization version. The original decoded text is authoritative for exact evidence rendering; any display normalization carries a mapping back to those offsets. Do not use the existing arbitrary 4,000-character AI chunks as semantic units.

`SourceGraph` contains `document_fingerprint`, `passages`, `units` and `coverage`. Each `Passage` has `id`, `start`, `end`, `text`, `text_sha256`, `role` (`operative`, `definition`, `context`) and a structural path. Each `SourceUnit` has `id`, `own_passage_ids`, `context_passage_ids`, `parent_id`, `condition_group_id`, `inventory_kinds`, and `unresolved_dependencies`. Context includes governing clauses and resolved internal definitions/cross-references; it is not an independently asserted operative change. Quoted amendments remain marked as amendments; do not infer the full effect on existing law without the referenced baseline.

The graph is a candidate inventory. Missing/ambiguous structure produces an unresolved structural unit retaining the complete source section, not a discarded fragment. Exclude verified contents entries. Structural parent headings group children; do not duplicate their financial facts. A parent that contains its own operative rule remains a separate unit.

New output schema `2.0-source-first`:

```text
Analysis = {
  schema_version, document_fingerprint, pipeline_version,
  synopsis: {text, explanation_ids, status: complete | partial | unavailable},
  provisions: [Explanation],
  coverage: {unit_ids, unresolved_unit_ids, omitted_source_ranges, inventory_complete: false},
  quality: {mechanical_status, semantic_review_status}
}
Explanation = {
  id, unit_id, status: explained | unresolved,
  summary, details: [short statement], unresolved_reason,
  claims: [{actor, action, modality: required | permitted | prohibited | unspecified,
            money: [{amount, currency, measure, comparator, purpose, period, base}],
            conditions: ConditionNode, exceptions: [ConditionNode],
            evidence_ids: [passage_id]}]
}
ConditionNode = {operator: all | any, children: [ConditionNode]}
              | {operator: leaf, text, evidence_ids: [passage_id]}
```

This is the persisted server response, not the provider schema. Document identity, coverage, quality/review statuses, publication completeness and all IDs are backend-owned. The provider returns explanations for assigned IDs and passage references; synopsis generation returns text and explanation references only. Reject provider assertions of complete coverage or human approval. Default semantic review to `unreviewed`, never copy it from model output.

Provider output contains IDs, never generated quotations or character offsets. Backend hydrates quotes from the pinned graph. Fields allow `null` where source facts are not established; `unspecified` is not permission. Unresolved reasons explain a specific limitation, not merely “other conditions apply.” Exact schema validation, recursion limits and per-field sizes are owned by `schema.py`; condition trees exceeding limits become unresolved, never truncated.

Readability limits: summary at most 400 characters; each detail at most 400; at most 12 details per unit. These are display-shape limits, not permission to drop content. Finalize source splitting before preflight on validated child boundaries with inherited context. Once confirmed, IDs and assignments are immutable: an oversized generated explanation may be repaired within its original ID or become unresolved, never trigger new child work. If no safe source split fits before preflight, retain the full section as an unresolved structural unit. Never split a conjunction into separate sufficient eligibility rules. Synopsis at most 1,200 characters, derived only from accepted explanations, with explicit partial status when any source unit is unresolved or source selection is incomplete.

Validation outcomes: `mechanically_valid`, `repairable`, `unresolved`, `fatal`. Mechanical validity is not semantic approval. Fatal failures include cross-user data, source identity mismatch, unknown passage IDs and unsupported schema versions. Conservative fact detectors produce a repair/review finding with evidence; they do not silently rewrite meaning. Repaired prose must pass all checks again, not only the check that triggered repair.

### Call budget and publication

Proposed default execution envelope: up to four initial generation calls, one targeted repair call, and one synopsis call, maximum six total. Each uses the existing per-call caps. Preflight includes immutable ordered work units, exact initial payload sizes and bounded repair/synopsis allowances. Aggregate conservative input allowance is the sum of initial payload sizes plus at most 100,000 units for each optional call; maximum output is 8,000 times the permitted call count (at most 48,000). This is a spending ceiling, not a guarantee that every possible failure set can be repaired. Eight units per generation call is only an upper bound; byte size and complete context also determine packing. If complete initial generation does not fit the confirmed envelope, preflight reports `budget_exceeded` before spending. A larger envelope requires explicit new confirmation; no automatic scaling for omnibus bills.

Repair only failed units, in one call if the actual complete failed set and context fit the reserved allowance. If it does not fit, mark all unrepaired failures unresolved; do not silently repair an arbitrary subset. Preserve accepted units byte-for-byte. Cross-unit conflicts invalidate the relevant units and synopsis; repair may change only explicitly listed IDs. Generate the synopsis last, from all accepted summaries/structured claims and evidence references. If that actual payload does not fit its allowance, skip the AI synopsis and show the existing non-AI brief plus its provenance; do not silently select a subset. An invalid synopsis is withheld, not retried outside the envelope.

Publication state is separate from execution state. Add `published_attempt` and result `completeness` (`complete`, `partial`, `none`) while keeping the legacy successful pointer readable. A completed attempt may publish a sanitized partial result and still allow a user-confirmed unresolved-unit retry. Such a retry creates a new attempt with its own confirmed plan, references reusable accepted step results by ID, and charges only for newly dispatched steps. Never mutate an old attempt's result or count reused usage again.

| Existing publication | New attempt outcome | Publication/display |
| --- | --- | --- |
| None | Valid partial | Publish partial, show unresolved-unit retry |
| Partial | Valid complete, same source lineage | Atomically promote complete |
| Partial | Valid partial retry, same lineage | Promote only if unresolved set strictly shrinks with accepted content unchanged; otherwise retain prior result |
| Partial or complete | Failed/unknown/cancelled retry | Keep prior result visible; show latest execution failure separately |
| Complete | New partial attempt | Keep complete primary; make newer partial separately accessible with version labels |

Never merge different document versions. A source change starts a new lineage; old complete results remain labeled stale rather than serving as current-version evidence. The latest-attempt status must not control whether an existing publication is rendered.

On retryable content failures, publish a private **partial** result only after all invalid prose has been removed and replaced by explicit unresolved cards with complete source access; never present it as a passed full-bill analysis. Fatal integrity failures publish no new result. Maintain the previous valid result and show failure status separately. Production feature rollout requires independent answer-key review of the three regression bills and real UI checks, not merely green unit tests.

## File ownership

All backend paths below are relative to `legislation-tracker-backend/`; client paths relative to `legislation-tracker-client/`.

- New `apps/legislation/enhancements/source_graph.py`: immutable passages, source units, hierarchy/context and coverage.
- New `apps/legislation/enhancements/provision_validation.py`: mechanical findings and structured/prose consistency checks, never legal truth labels.
- New `apps/legislation/enhancements/provision_pipeline.py`: bounded packing, targeted repairs, deterministic merge and synopsis stage.
- Existing `enhancements/{types,schema,source_packet,prompts}.py`: versioned contracts and preflight.
- Existing `enhancements/providers/{base,openai}.py`: generation/repair/synopsis requests using server-owned schemas.
- Existing `tasks.py`, `enhancements/{service,views,serializers}.py`, `models.py`: lifecycle, aggregate confirmation and persisted step state.
- Existing `evaluation/{whole_bill,coverage_inventory,provision_generation}.py`: benchmark/report integration and replay; retire experimental duplicate orchestration only after replacement parity is established.
- Existing `app/bills/[id]/bill-enhancement-panel.tsx` and associated API/types: new private analysis renderer alongside legacy renderer.

## Task 1: Build source units with inherited legal context

**Files:** create `enhancements/source_graph.py`, `tests/test_enhancement_source_graph.py`; modify `enhancements/types.py`, `extraction/federal_structure.py` only for proven parser defects. Preserve NLP behavior through regression tests.

**Interfaces:** `build_source_graph(document_id: str, version: str, text: str) -> SourceGraph`; `graph.passages` keyed by immutable passage ID, `graph.units` in bill order. Implement types described above as frozen dataclasses; serialized forms are JSON-safe.

- [ ] Add literal source fixtures for a parent IF with A AND (B OR C), sibling headings, contents/operative duplicates, quoted amendments, no-dollar authorizations, and “appropriate court.” Test through the real parser, not mocked inventory.

```python
def test_child_inherits_governing_condition():
    graph = build_source_graph("doc-1", "IH", "SEC. 1. BENEFIT\n(a) Grant aid only if--\n(1) income is below $20,000; and\n(2) the applicant is enrolled or employed.")
    group = next(u for u in graph.units if u.condition_group_id)
    selected = group.own_passage_ids + group.context_passage_ids
    text = " ".join(graph.passages[p].text for p in selected)
    assert "only if" in text and "income is below" in text
    assert "enrolled or employed" in text
```

- [ ] Run `rtk proxy .venv/bin/python -m pytest apps/legislation/tests/test_enhancement_source_graph.py -q`; require a meaningful failure before implementing.
- [ ] Implement graph construction: preserve raw spans; distinguish headings from operative text; group condition trees conservatively; keep ambiguous sections intact and unresolved. Resolve internal references only when their target is unambiguous; cycles use visited IDs and remain finite. References into another statute remain unresolved.
- [ ] Add mutation tests deleting parent context or one source range: graph coverage must expose the loss. Assert source reconstruction and hashes, no overlapping sibling ownership, and no duplicate monetary facts for heading-only parents.
- [ ] Run focused tests plus existing `test_complete_conditions.py`, `test_source_coverage.py`, `test_coverage_inventory.py`.

## Task 2: Introduce passage-ID evidence and the versioned response schema

**Files:** modify `enhancements/{types,schema,source_packet,prompts}.py`, `providers/{base,openai}.py`; create `tests/test_source_first_schema.py`; extend `test_enhancement_openai_provider.py` and `test_enhancement_schema.py`.

**Interfaces:** `hydrate_evidence(explanation: dict, graph: SourceGraph) -> dict`; `validate_source_first_schema(output: dict, graph: SourceGraph) -> dict`. Add provider methods `generate_provisions`, `repair_provisions`, `generate_synopsis`, each accepting the existing request/key/timeout arguments and returning `ProviderResult`. No arbitrary model-supplied schema or tool execution.

- [ ] Write rejection tests: correct quote ID from another version, same-bill unrelated evidence ID, unknown ID, oversized condition tree, duplicate/missing unit IDs, and model-supplied `quote` fields. Keep legacy 1.1/1.2 read tests.

```python
def test_evidence_is_backend_owned(graph, explanation, valid_provider_output):
    # Fixtures use a hand-authored operative passage ID belonging to this unit.
    explanation["claims"][0]["evidence_ids"] = ["fixture-operative-passage"]
    result = hydrate_evidence(explanation, graph)
    assert result["evidence"][0]["text"] == graph.passages[result["evidence"][0]["id"]].text
    valid_provider_output["provisions"][0]["claims"][0]["quote"] = "invented text"
    with pytest.raises(ValidationError):
        validate_source_first_schema(valid_provider_output, graph)
```

Fixtures `graph`, `explanation` and `valid_provider_output` must be hand-authored complete valid examples. First assert the unmodified provider fixture validates, then inject the single prohibited field so an unrelated schema error cannot make the test pass. Also test a provider claiming `semantic_review_status=approved` or `coverage=complete` while omitting a unit; these server-owned fields must be rejected.

- [ ] Run the new tests red; implement strict schema 2.0 and exact backend hydration. Require evidence appropriate to the unit/context role. A known but unrelated ID is not accepted merely because it exists in the graph.
- [ ] Exercise the actual OpenAI adapter with fake transport; assert serialized requests include the selected schema and passage IDs. Do not test only a mocked provider call.
- [ ] Run all schema/provider tests. Do not remove legacy citation handling until existing stored outputs no longer depend on it.

## Task 3: Add correctness findings without declaring parser output authoritative

**Files:** create `enhancements/provision_validation.py`, `tests/test_provision_validation.py`; modify `evaluation/whole_bill.py` to report findings separately from semantic judgments.

**Interfaces:** `validate_provision(explanation: dict, unit: SourceUnit, graph: SourceGraph) -> list[Finding]`; `Finding` fields: `code`, `unit_id`, `path`, `evidence_ids`, `outcome`, `message`. Outcomes use the four states specified above.

- [ ] Write negative fixtures for $10,000→$1,000, maximum→minimum, shall→may, prohibition→permission, Secretary of Homeland Security→Secretary of State, percentage-base loss, wrong fiscal year, missing conjunction and an unexplained external reference.

```python
def test_mandatory_fine_is_not_optional(fine_graph, optional_fine):
    unit = fine_graph.units[0]
    findings = validate_provision(optional_fine, unit, fine_graph)
    assert any(f.code == "modality_conflict" and f.outcome == "repairable" for f in findings)
```

- [ ] Run red; implement conservative source-anchored detectors for directly comparable facts, plus structured-fields versus prose consistency. When scope/modality cannot be safely matched, emit an unresolved/review finding, not a guessed correction. Do not use global keyword absence to prove semantic omission.
- [ ] Add positive counterexamples: may request review of a mandatory penalty; quoted prior law; multiple actors and amounts in one section; “not more than”; alternative eligibility; date references rather than effective dates. These must not be blindly rewritten or falsely certified.
- [ ] Record what automation cannot establish. Separate source support, factual findings, coverage, readability and human semantic review in reports. An LLM judge may assist review later but cannot be the sole release gate in this plan.

## Task 4: Bounded generation, targeted repair and synopsis composition

**Files:** create `enhancements/provision_pipeline.py`, `tests/test_provision_pipeline.py`; adapt `source_packet.py` and existing evaluation command to use the same orchestrator in evaluation mode.

**Interfaces:** `plan_analysis(graph: SourceGraph, limits: dict) -> AnalysisPlan`; `run_analysis(plan: AnalysisPlan, invoke: Callable, checkpoint: Callable) -> AnalysisResult`. `AnalysisPlan` holds ordered calls, graph/schema/prompt/model fingerprints, maximum calls/input/output and immutable generation unit assignments. `invoke` is a lifecycle-aware callback, not a direct untracked HTTP call. `checkpoint` persists each dispatch/result.

- [ ] Write tests that 33+ units or excessive context either pack completely within confirmed limits or fail preflight before any dispatch; never silently truncate. Test missing source dependencies, all calls fitting individually but exceeding aggregate budget, and an 8,000-token incomplete response.
- [ ] Implement at most four generation batches, one repair batch and one synopsis call. Reserve bounded optional-call allowances, not a promise to repair every imaginable failure set. Validate actual optional payload sizes before dispatch; oversized repair becomes unresolved and oversized synopsis becomes unavailable. Add a pinned H.R. 1589 preflight test proving the actual graph fits initial packing and aggregate ceilings; if it does not, report `budget_exceeded` rather than adjusting the fixture or silently widening caps.

```python
def test_repair_cannot_change_accepted_units(two_unit_plan, scripted_provider):
    result = run_analysis(two_unit_plan, scripted_provider.invoke, scripted_provider.checkpoint)
    assert result.provisions["accepted"] == scripted_provider.initial_accepted
    assert scripted_provider.repair_unit_ids == ["failed"]
    assert result.call_count <= two_unit_plan.maximum_calls
```

- [ ] Build the scripted provider fixture with literal initial/repair responses, including an attempted accepted-ID overwrite. Reject unexpected repair IDs. Revalidate the full combined result for cross-unit contradictions and document identity after merge.
- [ ] Test source-based splitting before preflight: a valid child boundary carries governing conditions into every child; an unsafe oversized unit becomes unresolved with source access. After dispatch, an oversized last-batch response must retain exactly the confirmed IDs, assignments and call ceiling; only same-ID repair or unresolved fallback is allowed. No arbitrary text truncation or silently increased response caps.
- [ ] Generate synopsis last from accepted explanations and pinned evidence, not from unverified draft text. Validate IDs and referenced claims; on unsupported synthesis, withhold AI synopsis and retain the non-AI brief. Partial status must be rendered when incomplete.
- [ ] Test zero failed units (no repair charge), failed set exceeding repair reservation (explicit unresolved), failed repair (no loop), and synopsis failure (no extra call).

## Task 5: Integrate persistence, confirmation and worker safety

**Files:** modify `models.py`, `tasks.py`, `enhancements/{service,views,serializers,types}.py`, `config/settings/base.py`, `.env.example`; add a new numbered migration after checking the current migration leaf; extend `test_enhancement_tasks.py`, `test_enhancement_api.py`; create `tests/test_enhancement_steps.py`.

**Interfaces:** persist `BillEnhancementStep` keyed uniquely by `(attempt_id, step_index)` with request fingerprint, unit IDs, status (`prepared`, `dispatching`, `succeeded`, `failed`, `outcome_unknown`), response ID, safe diagnostics and usage. Add versioned result/coverage metadata without rewriting historical rows. Use existing attempt lease and ownership checks.

- [ ] Write PostgreSQL transaction tests for duplicate workers, lease expiry between calls, credential deletion/rotation, source version change, feature disablement, cancellation and worker death after remote completion but before local save.
- [ ] Implement transactionally claimed dispatches: commit `dispatching` before HTTP; persist response before next step. Unknown outcomes never automatically redispatch; require explicit user-confirmed retry with an unknown-charge warning. Completed steps are reusable only when their exact request, owner, credential version, model and source fingerprints still match the approved plan.
- [ ] Add preflight API fields for aggregate call/input/output ceilings, included units and unresolved dependencies. Bind confirmation to the complete plan fingerprint. Changed source/model/budget requires a new confirmation.
- [ ] Persist safe error categories plus exact validator code/path and usage per step; unknown usage remains unknown. Do not store credential plaintext or emit arbitrary provider text in diagnostics.
- [ ] Publish schema 2.0 results atomically: partial explanations sanitized as specified; fatal integrity failure preserves previous result. Never overwrite public deterministic contracts. Recheck source/owner/feature state immediately before publication.
- [ ] Implement the publication transition table explicitly in `_finish_enhancement_attempt`, retry eligibility, serializers and latest-result queries. Replace the existing first-success-only promotion rule for schema 2.0, not historical artifacts. Test partial→retry→complete, partial→failed retry, complete→failed new attempt and concurrent partial retries under PostgreSQL; assert publication identity and accumulated usage, not only HTTP status.
- [ ] Run migrations/checks against an isolated test database, not the running app database. Test rollback/read compatibility and attempt deletion behavior. No production rollout merely because migration succeeds.

## Task 6: Reader UI for explanations, money and unresolved units

**Files:** modify `app/bills/[id]/bill-enhancement-panel.tsx`, `lib/api.ts`, and `tests/components/bill-enhancement-panel.test.tsx`; extend `e2e/llm-enhancement.spec.ts`. Read frontend `AGENTS.md` first; preserve the current UI design.

**Interfaces:** schema-discriminated renderer for 1.1, 1.2 and 2.0; new result includes hydrated evidence and coverage status. Do not rebuild evidence URLs by guessing document IDs.

- [ ] Write component tests rendering realistic schema 2.0 responses: concise synopsis, short provision summaries, expandable conditions/details, all financial items, unresolved source card, and prior-valid-result plus latest-failure status.

```tsx
await user.click(screen.getByRole('button', { name: /conditions and exceptions/i }));
expect(screen.getByText(/has not abandoned/i)).toBeVisible();
expect(screen.getByRole('link', { name: /read source/i })).toHaveAttribute('href', expectedPinnedDocumentUrl);
```

`expectedPinnedDocumentUrl` is a literal fixture URL containing its pinned document identity, not derived by the renderer under test.

- [ ] Implement evidence expansion with exact backend text and section label, short initial summaries, and accessible keyboard controls. All money entries remain reachable through pagination/filtering; show total and visible counts accurately. Unknown amounts remain unknown, never zero.
- [ ] Render unresolved items without rejected prose. Clearly distinguish partial private AI analysis from deterministic analysis and from old-version results. Show aggregate spending bounds before Enhance confirmation.
- [ ] Replace the current `enhancement.status === "succeeded"` display gate with published-result presence and completeness. Test every publication-table transition and the unresolved-only retry control. Failed latest attempts must not hide a prior valid publication.
- [ ] Run `rtk proxy pnpm test`, `rtk proxy pnpm typecheck`, and `rtk proxy pnpm exec playwright test e2e/llm-enhancement.spec.ts` in an isolated test setup. Do not restart the user's live stack for these tests.

## Task 7: Freeze benchmark evidence and establish the release gate

**Files:** modify `evaluation/whole_bill.py`, `management/commands/evaluate_reader_quality.py`, evaluation command and tests; add versioned reports under `docs/benchmarks/bill-understanding/`; update backend `docs/{COVERAGE_CANDIDATE,LLM_ENHANCEMENTS,PRODUCTION_OPERATIONS}.md`.

- [ ] Add replay mode that verifies source, graph, prompt, model and request identities, makes zero network calls, and labels historical versus fresh results. Preserve immutable raw responses alongside separately versioned assessment reports.
- [ ] Use pinned H.R. 1589, H.R. 9300 and S. 5 answer keys, independently of generated outputs. Never send answer keys to generation or repair. Record reviewer identity, exact artifact hashes, expectation-by-expectation decisions and unresolved external-law questions.
- [ ] Gate rollout on: no critical factual errors; every annotated financial provision accessible; every material explanation supported by its cited source; no omitted meaning-changing condition. Track readability independently. An incomplete answer key cannot certify exhaustive whole-bill coverage; the two partial omnibus keys remain explicitly partial until separately completed.
- [ ] Run all backend tests on SQLite for fast regression and PostgreSQL for lock/search/partition-specific coverage; provide dedicated Redis for cache tests. Report every skip or blocked check. Run frontend component/API tests and the real screen E2E flow. Human usability checks ask “What changes? Who is affected? What money is involved?” with results recorded, not assumed from automated tests.
- [ ] Only after the three-bill gate passes, expand to the other seven pinned bills. No dates or passing scores promised in advance. Do not call this complete merely because generation returned structured JSON.

## Completion and handoff

- [ ] Tasks 1–7 verified, benchmark findings resolved or explicitly excluded from claims with source-backed reasons.
- [ ] Production worker, UI and legacy compatibility tested; aggregate spending confirmed; no unexplained skips hidden.
- [ ] Document migration, feature rollout and rollback instructions. Feature remains off until explicitly enabled; no automatic regeneration of existing user analyses.
- [ ] Propose scoped commits only after implementation approval; no broad `git add .`, push, PR or deployment from this plan/review request.
- [ ] Provide changed-file summary, exact test/evaluation evidence, remaining limitations and launch instructions. Planning completion is not implementation completion.
