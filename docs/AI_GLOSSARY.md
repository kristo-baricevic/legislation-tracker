# Private AI reader explanations

## Unified reader (schema 1.4)

Bills with a current 2.1 NLP contract use schema 1.4 for newly confirmed
enhancements. The public contract remains the complete inventory. Private AI
explanations replace matching summary, provision, money-purpose and definition
text in place; they never replace amounts, relationships, filters or pagination.
Every replacement retains the original explanation and cited source disclosure.
The top of the bill shows only Enhance with AI until a compatible saved result
exists, then replaces it with the Original / AI-enhanced selector. Switching uses
saved data and never starts a paid request. The AI metadata box, including
warnings, regeneration controls, usage and histories, sits at the bottom of the
bill page. Cost confirmation opens beside the top control. Signed-out users see
the original view and an Enhance action leading to login.

Targets are bound to document ID/text hash, contract ID/hash, typed item ID and
original text. Missing, unresolved or incompatible explanations fall back to
the original. Signing out clears private explanations. Viewing a historical
attempt does not change the active reader; a failed refresh does not discard a
compatible successful result.

Preflight sends complete enclosing sections, deduplicated within each batch,
with exact financial/deadline relationships. Up to eight targets share a batch.
External definitions and contexts exceeding per-request limits are explicitly
listed as unavailable. The entire eligible plan must fit `LLM_READER_MAX_CALLS`
(default 64, including the summary); otherwise confirmation is unavailable.
Confirmation shows aggregate limits and exclusions. No paid retries or silent
regeneration occur. Each batch must return every target as explained or explicitly
unresolved. Source/credential/lease checks fence calls and atomic publication.

Citation checks establish source location and target identity, **not semantic
entailment**. Human review of the generated wording remains necessary. The frozen
H.R. 7583 policy/wage fixture verifies that complete thresholds, formulas and
effective dates reach the model; it does not certify a future model response.

No backfill is needed. Compatible 1.1–1.3 summaries and explanations can be selected
as the AI reading version without regeneration, and 1.3 glossary refinements remain
usable. They replace the narrative area, not the complete financial ledger.
Old free-form reports cannot safely be mapped to individual provision IDs;
a separately confirmed regeneration is required for those ID-bound explanations.
Both saved AI explanations and original provisions use six-item pagination,
rather than an accumulating text list. Original actor/action fields are not
repeated underneath the same explanation; distinct effects remain visible.

Regression coverage: `test_enhancement_reader_targets.py`,
`test_reader_enhancement_pipeline.py`, `unified-bill-reading.test.tsx` and
`bill-enhancement-panel.test.tsx` cover target/source identity, complete outcomes,
source changes/revocation, original financial pagination, private-state clearing
and historical-selection isolation.

## Legacy glossary flow (schema 1.3)

The legacy bill-enhancement flow uses output schema 1.3 to return
optional glossary explanations alongside the bill analysis. Clicking Enhance
uses the existing confirmation, credentials, request limits, and private storage.
It does not change the public NLP contract.

Each offered definition is bound to its contract ID, definition ID, original
definition, scope, and source offsets. All eligible definitions from the current
contract are sent in separate batches of at most four, independently of the
main analysis's text selection. Complete source spans are preserved; a definition
that cannot fit even by itself blocks preflight instead of being silently omitted.
References whose definitions live in another law or section are excluded rather
than resolved from model memory.

Validation requires a unique definition ID and an exact, unambiguous quote inside
that definition's source range. This verifies citation location, not the semantic
accuracy of every paraphrase; human evaluation is still necessary.
The provider returns only quoted citations; the adapter derives the API's
`source_refs` list from them. It does not rewrite quotes or bypass source checks.
Validation failures retain an allowlisted field path, stage, and batch index,
plus completed-batch counts. Failed AI prose is not stored or published.
Malformed JSON failures also retain a fixed parser reason, character/line/column
coordinates, response-text length, and structured output-text part counts and
lengths. These distinguish empty responses, syntax failures, and text-extraction
discrepancies without retaining response contents or arbitrary exception messages.
Provider failures inside a glossary batch retain its index and accumulated usage.

The Key terms UI uses a successful, non-stale private explanation only when its
contract ID, definition ID, term, and original definition match. The original
legal text and evidence remain available. Missing entries, old analyses,
signed-out sessions, and mismatched versions retain the regular glossary.

Request limits apply to every batch. The confirmation includes every batch plus
the main analysis and its optional citation repair, with aggregate input/output
limits. The entire plan is fingerprinted. Every batch must return every assigned
definition before the result is published. There are no automatic paid retries.
Usage is accumulated and saved between calls, with source, credential, and lease
checks before continuing and again before publication.
Existing saved analyses are not regenerated automatically. Schemas 1.1 and 1.2
remain readable. The optional, disabled `2.0-source-first` pipeline does not yet
emit glossary refinements.

Regression coverage:

- Backend: `test_enhancement_glossary.py` and `test_enhancement_tasks.py` (identity,
  source bounds, complete batched coverage, omission rejection, usage, revocation,
  source changes, lease loss, timeout, compatibility).
- Frontend: `ai-glossary.test.tsx` (display, version fallback, logout privacy).
