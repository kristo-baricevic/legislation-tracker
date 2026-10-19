# Source-first correction and live evaluation — 2026-10-16

## Decision

**Release gate remains blocked.** Transport/schema fixes are implemented and exercised with live responses. Mechanical acceptance is not whole-bill correctness or readability acceptance. No output from these evaluations was published to the application.

## Implemented corrections

- Request-local `uN`/`pN` identifiers replace model-facing hashes. Schema enums and exact server-side mapping constrain identity; no fuzzy citation repair.
- Shared `cN` condition references restore exact source excerpts server-side, avoiding repeated long quotations in responses. Conditions outside the checklist still require source support.
- Student completion percentages are not treated as financial percentages; financial percentages still require a denominator.
- Required condition scope distinguishes structural/governing context from background definitions. Explicit external-law references cannot bind to an unrelated local section with the same number.
- Complete fiscal-year ranges are recognized. A year inside a cited range is not a date conflict.
- A verified table of contents is not classified as an operative financial provision. Documentation of eligibility does not itself create a payment.
- Valid batch siblings survive a malformed or missing row. Duplicate/unassigned identities and unknown evidence remain rejected.
- Repair receives detailed findings, including missing source conditions. An oversized failed set now selects up to eight fitting units for the single reserved repair, retaining all unattempted failures. It does not increase the approved call/token ceilings.
- Regression coverage includes actual saved model failures, not only constructed successful responses.

## Latest complete live run

Artifacts are immutable; their decoded canonical responses, model IDs, usage and request fingerprints remain available:

| Bill | Recording | Calls | Mechanical result |
|---|---|---:|---|
| H.R. 1589 | [recording](source-first-live-20261016-193226-BILLS-119hr1589ih.json) | 4 | 12/22 units explained; 10 unresolved |
| H.R. 9300 | [recording](source-first-live-20261016-193226-BILLS-119hr9300ih.json) | 2 | 5/5 units explained |
| S. 5 | [recording](source-first-live-20261016-193226-BILLS-119s5enr.json) | 2 | 3/3 units explained |

These runs used `source-first-7`, `gpt-6-luna`, and an 8,000-token per-call output cap. None failed on the previous hash-identity or unsupported-schema problems. The final external-reference guard and bounded repair-subset correction were made **after** this live run and tested locally; these recordings are not evidence of a live run of those last two changes.

H.R. 1589's repair did not dispatch in this recording because its combined repair input exceeded the cap. This is the concrete failure addressed by the new bounded-subset regression. One unresolved unit (§203) requires missing amended-law context; others failed condition preservation, financial coverage, or comparator/modality checks. They are not all provider transport errors, and not all have been adjudicated as actual semantic errors versus conservative validator false positives.

## Output review against the answer keys

This is a targeted review by the implementing agent, not independent human sign-off or a complete scored answer-key matrix.

### H.R. 9300

- The output retains gross 2% tribal reservation, minimum 20% of the post-tribal balance, and discretionary maximum 5%/2% after both reservations. It preserves the one-campus-at-a-time restriction and FY2027–2032.
- **Readability failure:** §5 details end one sentence with “and recruiting and ret a”. The 400-character schema maximum did not ensure a complete sentence.
- **Financial accessibility gap:** the structured money rows contain the percentage allocations but not separate no-fixed-amount entries for all authorized grant/support/evaluation uses in M02/M06–M08. Prose mentions some of these; a money-only view would not be complete.

### S. 5

- The output retains the conjunction of inadmissibility and crime-related triggers, the detention/detainer duty, and five separate structured $100 harm-threshold entries. These are not presented as appropriations or fines.
- **Coverage failure:** LR-F06's express replacement of “Attorney General” with “Secretary of Homeland Security” is absent from the displayed explanation.
- **Readability/coverage gap:** the five enforcement routes are summarized as actions against the “specified federal official”, rather than plainly identifying the different defendants and rules. Evidence alone is not an adequate reader explanation.

### H.R. 1589

- Most central eligibility provisions and the fine are withheld in this run, so the bill cannot pass its whole-bill benchmark.
- §310 correctly preserves the no-fixed-dollar authorization for FY2026–2036 and availability until expended.
- **Reader-facing problems in accepted output:** several details leak `(p1)`-style transport references into prose. §312 says cross-referenced provisions are not supplied even though the graph carries same-bill context. Accepted does not mean semantically certified.

## Required next gate

Do not loosen citation, amount, or condition checks to turn these results green. Reuse the saved responses for regression work before additional full-bill paid runs. Remaining acceptance work must cover complete sentences, separate financial provisions without stated dollar amounts, explicit amendments/official substitutions, and whether referenced context is actually supplied. Every answer-key item needs a reviewed supported/missing/incorrect/unresolved disposition; an ID-valid response alone cannot establish that.

No application restart, live database migration, deployment, commit or push was performed for this correction.

## Final local verification

- Full backend SQLite suite after the last corrections: **1,266 passed, 15 skipped**, 2 existing Django deprecation warnings. This is not PostgreSQL verification, and skipped tests are not passes.
- Focused pipeline/replay tests: **20 passed**.
- Focused provision-validation tests: **34 passed**.
- Ruff on the changed source-first modules/tests: passed.
- `git diff --check`: passed.
