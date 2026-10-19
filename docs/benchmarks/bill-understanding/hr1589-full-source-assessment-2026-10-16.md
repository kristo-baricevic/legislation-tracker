# Whole-bill benchmark: provisional baseline

No case is release-approved. Draft keys and semantic/UI review remain outstanding.

| Bill/version | Pipeline | Gate | Items | Mechanical failures | Long items (>60 words) |
|---|---|---|---:|---:|---:|
| BILLS-119hr9300ih | nlp | blocked | 25 | 0 | 5 |
| BILLS-119hr9300ih | ai | blocked | 0 | 0 | 0 |
| BILLS-119hr1589ih | nlp | blocked | 167 | 0 | 58 |
| BILLS-119hr1589ih | ai | blocked | 22 | 0 | 0 |
| BILLS-119s5enr | nlp | blocked | 14 | 0 | 1 |
| BILLS-119s5enr | ai | blocked | 0 | 0 | 0 |

## Current source-policy preflight (not sent to a provider)

- BILLS-119hr9300ih: prepared_not_sent; complete document: True; omitted: none.
- BILLS-119hr1589ih: prepared_not_sent; complete document: True; omitted: none.
- BILLS-119s5enr: prepared_not_sent; complete document: True; omitted: none.

AI outputs below are historical replays, not new generations using these packets. Passing quote validation does not clear recorded semantic failures.

## Review procedure

For each expectation in the JSON report, map the relevant output item IDs and check coverage, actors, legal effect, amounts, denominators, dates, exceptions and uncertainty against the pinned source. Do not credit words merely appearing in an evidence quote.

Inspect every output claim for unsupported additions, including claims not represented in the answer key. Review readability separately. Confirm all financial provisions are accessible through the actual UI, including pagination and expansion.

Release requires accepted keys, no critical factual errors, all annotated financial provisions accessible, source support for every material explanation, and no meaning-changing omitted conditions. Unknown or unreviewed is BLOCKED, never PASS.

AI not_run means no matching saved artifact was supplied. No provider requests were made.
