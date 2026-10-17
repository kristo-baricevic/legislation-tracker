# Source-first private bill analysis

Implementation status: integrated behind `LLM_SOURCE_FIRST_ENABLED=False`.
This is not a three-bill semantic acceptance or a production rollout.

## Execution contract

Schema `2.0-source-first` retains pinned raw passages and section-level source
units. Definitions, governing container text and explicit same-Act references are
context, not independently generated quotations. The backend hydrates evidence;
provider-supplied quotation text, offsets, review approval and coverage assertions
are rejected. Existing 1.1/1.2 results remain readable.

The OpenAI transport uses request-local `uN`/`pN` references constrained by the
response schema. Canonical hashes stay server-side; decoding is an exact lookup,
never fuzzy matching. The source-only condition checklist is deduplicated across
units. `cN` condition references expand to complete pinned text and evidence
before the ordinary local validator runs. A condition from an unrelated passage
still fails ownership validation. Local uniqueness constraints remain enforced
even when unsupported keywords are omitted from the provider's wire schema.

Preflight fixes generation assignments and reserves at most four generation calls,
one targeted repair and one synopsis. Each call is capped at 100,000 conservative
input units, 120,000 bytes and 8,000 output tokens. The UI confirms the aggregate
ceiling, including optional calls. There is no automatic budget expansion.

Each dispatched call is committed to `BillEnhancementStep` before HTTP and its
response/usage saved before the next call. Ambiguous outcomes require a new user
confirmation. Credential, feature, source and lease checks run between calls and
again before publication. Failed attempts do not erase the prior publication.
Partial retries freeze reusable accepted explanations into the new authorization;
only unresolved units are newly generated. Reuse requires the same source/model
identity and credential revision. Prior paid usage is not counted again.

The reader shows short summaries, expandable conditions, every returned financial
item, and exact source text. Rejected prose is replaced with unresolved source
cards. `complete` means all inventoried units passed mechanical checks; it does
**not** mean independently verified legal accuracy or exhaustive extraction.

## Conservative boundaries

- Large sections can split at complete, consecutively labeled, titled subsections
  before confirmation. Operative parent introductions, conjunctions and quoted
  amendments remain intact; no splitting occurs after dispatch.
- Unambiguous same-Act references, including subsection suffixes, resolve to
  pinned context. Bare references resolve only outside amended-law scope.
- Outside-law dependencies remain unresolved, but do not automatically suppress
  explicit rules supplied by the bill. Those explanations carry backend-owned
  source limitations in the UI, and their synopsis remains partial. An amendment
  whose meaning cannot be established from supplied text stays unresolved.
- Condition checks require complete source wording. Complex or paraphrased
  Boolean logic can be withheld pending review rather than silently accepted.
  Display whitespace can normalize; condition leaves allow up to 6,000 characters
  so the 400-character summary limit does not force shortening legal conditions.
  Mandatory checklists cover owned text, structural parents and explicit
  `subject to section` dependencies, not every condition anywhere in background
  definitions or ordinary cross-references. That distinction is not a claim that
  all implicit legal dependencies have been resolved.
- Financial checks cover explicit currency amounts, magnitudes, currency,
  percentage-base presence and unmatched no-dollar authorizations. They do not
  prove every financial purpose, overlapping allocation or implied cost.
  Nonfinancial completion-rate percentages and verified contents headings do not
  require invented financial entries.
- Synopsis generation currently selects complete accepted summary sentences.
  Novel synthesis is withheld; the existing non-AI brief remains available.
- Mechanical checks are not a semantic oracle. Actor/action attribution, amended
  law, exception scope and independent reader comprehension still require the
  pinned answer-key review. `semantic_review_status` remains `unreviewed`.
- Shared-evidence contradictions are checked before repair and after merging;
  conflicting units cannot feed the synopsis. This catches direct structured
  conflicts, not every paraphrase-level contradiction.
- Structurally invalid or missing individual assignments enter targeted repair
  without discarding valid siblings. Duplicate or out-of-assignment IDs reject
  the batch; unknown source identities are never guessed or silently reassigned.

## Offline verification

From the backend:

```sh
rtk proxy .venv/bin/python manage.py evaluate_source_first
rtk proxy .venv/bin/python manage.py evaluate_source_first --case BILLS-119hr1589ih --replay /absolute/path/new-source-first-recording.json
```

Preflight and replay never invoke a provider. Replay requires the exact plan/model/
document identity, each request fingerprint and response hash. Historical v1
experiments cannot be relabeled as fresh schema-v2 evidence. Original response
artifacts remain unchanged. Independent answer keys are used only in review,
never in generation or repair prompts.

Fresh evaluation uses the same production orchestrator and configured model,
reasoning and per-call bounds. Configure `LLM_ENHANCEMENT_EVALUATION_API_KEY`
locally, run preflight, then explicitly confirm its current fingerprint:

```sh
rtk proxy .venv/bin/python manage.py evaluate_source_first --case BILLS-119hr1589ih --execute --confirm-plan FINGERPRINT_FROM_PREFLIGHT --output /absolute/path/new-recording.json
```

The runner exclusively reserves a new owner-readable artifact before dispatch,
records each request identity before sending, and checkpoints decoded responses
(with exact aliases restored to canonical source identities),
usage and safe failures. Existing artifacts are never resumed or overwritten.
Unknown outcomes do not retry automatically. Changing model/reasoning/output
bounds invalidates confirmation. Review packets retain money, conditions and
evidence, and distinguish repaired historical findings from unresolved failures.

Release requires fresh outputs for H.R. 1589, H.R. 9300 and S. 5, independently
accepted answer keys, no critical factual errors, all annotated financial items
accessible, supported material explanations, and no meaning-changing omitted
conditions. Readability and human screen comprehension are separate checks.
Fresh provider runs are recorded in `docs/benchmarks/bill-understanding/` at the
repository root. They are not a human usability study or semantic approval.

## Deployment and rollback

1. Apply migrations 0016 and 0017 in the intended deployment after backup/change
   approval. Tests apply them only to disposable databases.
2. Keep the source-first flag false until the benchmark gate and rollout are
   explicitly approved. Enabling does not regenerate any existing analysis.
3. To stop new source-first work, set the flag false and use normal authorized
   deployment procedures. Existing v2 results remain readable; queued v2 work
   fails its identity check instead of dispatching under the legacy policy.
4. Prefer flag rollback. Reversing migrations removes the step audit/authorization
   metadata, so archive it first; do not roll them back casually.

The running application database and services were not migrated or restarted.

## Verification recorded on 2026-10-16

- Latest full PostgreSQL/Redis suite: 1,249 passed; two expected skips (SQLite-only
  fallback and opt-in recommendation performance benchmark).
- Final SQLite suite after the completion-review fix: 1,238 passed; 15 skipped, including PostgreSQL-only cases covered
  by the separate PostgreSQL run.
- Focused source-first validation/pipeline/replay/schema rerun: 50 passed.
- After the completion review, source-graph/pipeline regression tests passed
  (29 tests); a PostgreSQL source-graph/worker/pipeline/replay rerun passed
  (46 tests). The review found and we fixed one sibling-definition context-loss
  issue in large-section splitting. No additional high-confidence findings were
  reported; real-provider behavior and whole-bill accuracy were not approved.
- Frontend: 145 component tests and 38 API tests passed; TypeScript check passed.
- Source-first browser flow: passed against isolated Django/Celery services and
  the fake provider, including confirmation, publication, evidence and reload.
- Legacy browser flow with the source-first flag disabled: passed separately.
- Migration consistency and whitespace checks passed.
- One intermediate full run overlapped an implementation edit and failed on
  mixed imported module versions; the stable-snapshot PostgreSQL rerun above
  passed. An earlier focused run omitted the isolated database override and
  failed database setup; it did not establish a product failure or modify app
  records. Explicit isolated database configuration was restored for reruns.

On continuation, the offline benchmark preflight includes all 5 units for H.R.
9300, 21 of 22 for H.R. 1589, and all 3 for S. 5, within the confirmed limits.
H.R. 1589 section 203 inserts a phrase after “considered” in INA 244(f)(4): its
complete legal effect requires the absent baseline, so its full source remains
available as an unresolved item. Outside-law limitations on other units remain
explicit; being eligible for generation is not an accuracy score.

The user-supplied evaluation key has been used for fresh generation. The full
release gate, independent whole-bill acceptance and human reader checks remain pending.
Passing infrastructure tests must not be reported as passing those criteria.
## Latest evaluation status

See the [current correction verification report](../../docs/benchmarks/bill-understanding/source-first-acceptance-2026-10-16.md)
for exact artifacts, provenance, tests and remaining acceptance limits. Current
offline revalidation accepts 5/5 H.R. 9300 sections, 3/3 S. 5 sections, and 21/22
H.R. 1589 sections; the remaining section requires an absent outside-law baseline.
Claim-level and money-only repair are implemented. Final PostgreSQL verification
is 1,345 passed / 3 skipped, with the Redis test subsequently passing separately.
These are not semantic accuracy percentages or a fresh all-three-bill run.
Whole-bill release acceptance remains unapproved, including a documented prose
consistency issue and human comprehension checks. Earlier reports and the
verification counts above are historical.
