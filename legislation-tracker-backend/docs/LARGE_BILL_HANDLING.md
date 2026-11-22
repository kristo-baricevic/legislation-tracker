# Large bill handling

Status: findings + plan. Nothing here is implemented yet.

## Why this exists

Enhancement preflight must fully plan a bill before any provider call. On very large
bills that planning step is unusable today, and a second failure mode returns a
"successful" plan that covers nothing.

## Measured on the local dataset (16,925 bills with source chunks)

| | chars | ~tokens |
|---|---|---|
| median bill | 7,034 | ~1.8k |
| p90 | 35,101 | ~8.8k |
| largest | 3.77M | ~942k |

Distribution: 10.1% of bills exceed 35k chars, 2.6% exceed 100k, 0.35% (59 bills)
exceed 400k, and 4 exceed 2M.

Implication: sending the whole bill to the model is correct for the median and the
p90. Retrieval-on-demand (vector search, tool fetching) would save nothing on a
1.8k-token bill and would break the coverage guarantee. The problem is only the
tail, and there the problem is planning, not payload size.

## Bug 1 — `plan_analysis` is quadratic in units

`apps/legislation/enhancements/provision_pipeline.py`

`plan_analysis` builds a fully serialized payload for every unit
(`singles = {unit.id: make([unit.id])}`), then rebuilds candidate payloads again
inside the packing loop. Cost grows with units × candidates.

Measured (local stack, `config.settings.dev`):

| document | chars | units | graph | plan |
|---|---|---|---|---|
| 18340 | 3.58M | 2,228 | 10.6s | **did not finish in 90s** |
| 11639 | 3.01M | 1,351 | 12.0s | **did not finish in 90s** |
| 18343 | 3.37M | 36 | 11.4s | 24.6s |

Source-graph construction is fine (~11s for 3.5M chars). The cost is entirely in
planning.

Fix: compute each unit's payload and estimated input once, memoize it, and pack
batches using memoized estimates instead of re-serializing. Target: planning time
linear in units.

## Bug 2 — a zero-coverage plan reports success

Document 18343 (36 units, 3.37M chars) returned `calls=0, input=0` and no error:
every unit was skipped as unresolved, and the result looked like a valid plan.

An enhancement built on that plan would complete with no analysed content.

Fix: a plan that resolves no units must fail preflight with an explicit reason
(categorised like the existing `budget_exceeded` path), never return as valid.
Unresolved units must also be surfaced to the caller with a count and reason
rather than only appearing in `source_manifest.unresolved_unit_ids`.

## Strategy for bills that genuinely do not fit

Current hard limits: `max_generation = min(4, generation_calls)`, per-call input
≈100k tokens, total input ceiling 600k tokens, output ceiling 48k.

2,228 units cannot fit in 4 calls at 8 units per call. Two levers, in order:

1. **Deterministic text reduction (cheapest, highest value).** Strip boilerplate
   that no provision depends on — page headers/footers, amendatory instructions
   ("strike X and insert Y"), repealed and expired text — before building units.
   This reduces tokens without reducing coverage. No model involved.
2. **Hierarchical summarization.** Summarize each unit once (bounded call), then
   plan provisions over summaries and hydrate evidence from the original text for
   citation. Turns one impossible context into N bounded calls with a deterministic
   second pass.

Only after both: raise the call ceiling, and present the estimated cost to the user
for approval before spending. A server-side refusal is the last resort, not the
first response.

## Explicit non-goals

- **No vector database for this pipeline.** Embeddings (~$0.02 per 3.5M-char bill)
  are cheap but do not reduce the generation call that actually costs money, and
  retrieval would drop text the coverage guarantee requires. Revisit embeddings
  only for cross-bill near-duplicate detection, where boilerplate repetition makes
  the saving real.
- No model-based selection of which sections to read.
- No silent truncation of source text.

## Acceptance

1. Planning is linear: the 2,228-unit bill plans in seconds, not >90s.
2. A plan that resolves zero units fails preflight with an explicit reason.
3. Tests cover both: a synthetic high-unit-count bill for timing, and a
   zero-resolvable-unit bill for the refusal path.
4. Unresolved units are reported to the caller, not only in the manifest.
