# Source-first correction verification — 2026-10-16

## Decision

The implementation and targeted corrections below are verified. **The complete
release gate is not approved.** Mechanically valid output is not proof of legal
accuracy or reader comprehension. No application analysis was published, no
production flag was enabled, and no changes were committed or pushed.

## Changes verified

- Repairs target connected failed claims/source items, preserving unrelated
  accepted claims and prose. Money-only correction preserves non-money fields.
- Source accounting reports multiple safely diagnosable failures together,
  rather than hiding condition failures behind the first missing item.
- Internal subsection references retain the complete relevant qualification,
  including ancestor introductions and parent-scope safeguards. Unknown outside
  law remains explicit rather than guessed.
- Provider response schemas constrain evidence, condition and source-block
  references to each provision's available source material.
- Mandatory fines cannot be softened to discretionary penalties; travel days
  cannot be classified as money; cost-based fees need financial coverage even
  when there is no numeric amount.
- The reader can expand every rule, including rules without money or conditions.
  Required, permitted and prohibited actions are labeled. Financial harm
  thresholds are distinguished from spending or bill-cost estimates.
- Saved output can be revalidated and narrowly repaired with recorded provenance
  and actual paid-call counts. Previously accepted output is not automatically
  accepted under newer validators.

## Pinned bill results

| Bill | Current mechanical result | Evidence and provenance |
| --- | --- | --- |
| H.R. 9300, introduced | 5/5 sections accepted | `source-valid-candidates-v12-BILLS-119hr9300ih.json`; saved provider responses revalidated offline |
| S. 5, enrolled | 3/3 sections accepted | `source-valid-candidates-v12-BILLS-119s5enr.json`; includes the corrected detainer/custody distinction, revalidated offline |
| H.R. 1589, introduced | 21/22 explained; one explicitly unresolved | `claim-repair-v20-low-20261016-212912-BILLS-119hr1589ih.json`; 19 reused valid sections, two repaired sections, two actual paid calls |

H.R. 1589 section 203 changes an absent INA baseline. Its source is retained;
the full legal effect is deliberately not invented. These counts are section
validation results, **not semantic accuracy percentages**.

The final offline candidate-pool revalidation also reports 5/5, 3/3 and 21/22.
This is not a fresh single-pass run of all three bills. Artifacts retain origins;
the `v12` candidate filename is historical, not the current prompt version.
Latest live output uses `source-first-16`. Targeted live runs used a low-reasoning
evaluation override; production defaults were not changed. Answer keys were not
provided to the generation model.

Follow-up inspection confirmed H.R. 1589 applicant classes, education alternatives,
criminal-bar exceptions, mandatory fine, fee substitution, and section 303's
removal/return safeguards. The v19 money-only correction added the DACA cost-based
fee while preserving all legal claims and explanatory prose. The v20 correction
removed false source-absence statements in sections 304 and 312.

## Tests

- Final full PostgreSQL suite: **1,345 passed, 3 skipped**. Skips: SQLite-only
  fallback, opt-in recommendation performance benchmark, and Redis availability.
- Redis sharing test then ran separately against a disposable isolated Redis:
  **1 passed**. That container was stopped and removed after the test; app Redis
  was not touched.
- Full SQLite suite before the last two source-availability regressions:
  **1,331 passed, 15 skipped**. Latest focused validation/schema/transport run:
  **58 passed**. Final PostgreSQL suite includes the later regressions.
- Frontend: **148 component tests and 38 API tests passed**; TypeScript passed.
- Source-first browser flow: **1 passed**, using isolated Django/Celery services
  and a fake provider, covering key validation, confirmation, persisted result,
  evidence navigation and reload. This is not live-model semantic approval.
- Scoped Ruff checks passed. Django emits two existing CheckConstraint
  deprecation warnings in the full backend suite.

An initial PostgreSQL run exposed an outdated concurrency-test provider fixture
without source coverage items. The fixture was updated; the worker test file and
then the full suite passed. No application database migration or stack restart
was performed.

## Remaining acceptance limits

- H.R. 1589 section 306 still includes an overly broad statement that the supplied
  text does not establish the full effect of subsection (c), although it then
  explains that subsection's removal exception and return safeguard. This needs
  semantic cleanup; current mechanical checks do not prove prose consistency.
- Some definitions are vague outside their expanded rules, and long exact
  condition quotations remain difficult to read. Accessible is not the same as
  understandable.
- Independent whole-bill acceptance of the final combined artifacts and human
  screen-comprehension checks remain outstanding. The synthetic recommendation
  performance benchmark was not run; it is unrelated to this correction.

Do not promote these results to a completed release gate or enable publication
based only on the passing test counts.
