# Large bill handling: short output, complete review

## Scope and baseline

This document covers the **source-first provision planner**, not the separate reader-batch pipeline. On the original sample of 16,925 documents, the median was 7,034 characters, the 90th percentile 35,101, and the largest 3.77 million. Only 59 exceeded 400,000 characters. Do not add retrieval or selective reading to solve a planning problem in the tail.

Previously, planning documents 18340 and 11639 did not finish within 90 seconds. Document 18343 took 24.6 seconds and incorrectly returned a valid plan containing no calls and no reusable work.

## Stage 1: local preflight (implemented)

- Build the source graph once from the document. Independently supplied graphs still undergo the integrity audit. Keep original passages, offsets, amendments, repeals and effective dates.
- Check source eligibility and a lower bound on request bytes before building provider payloads. Compute inputs for feasible units once and reuse them during packing. Check actual serialized request and estimated output sizes before admitting each batch.
- Keep existing cost limits. Once enough individually feasible units prove that even perfect packing would exceed the generation-call ceiling, stop serializing. Still account for every remaining unit. On atomic refusal, a budget-blocked unit is **not** a claim that it would fit individually.
- A unit is planned, validated for reuse, or unresolved. Return counts and reasons in preflight. No newly planned **or** reusable units means an explicit zero-coverage refusal; partial plans must not be presented as complete. Reusing all verified work is not a failure.

### Dry run on the three original documents

Run `python manage.py benchmark_source_planner 18340 11639 18343`. This command reads stored text, verifies the union of passage ranges against it, and checks that each graph unit has exactly one disposition. It never instantiates a provider. Single local run; times exclude database I/O.

| Document | Characters | Graph | Planner | Units accounted for | Executable |
| --- | ---: | ---: | ---: | ---: | ---: |
| 18340 · S. 1071 · Public Law | 3,582,163 | 8.401 s | 0.161 s | 2,228 / 2,228 | 0 |
| 11639 · S. 2296 · Engrossed in Senate | 3,006,823 | 12.142 s | 0.154 s | 1,351 / 1,351 | 0 |
| 18343 · S. 1071 · Engrossed Amendment House | 3,370,908 | 10.065 s | 0.005 s | 36 / 36 | 0 |

18340: 2,046 budget-blocked, 180 lacking explainable source, 2 over the per-request input limit. 11639: 1,160 budget-blocked and 191 lacking explainable source. 18343: all 36 units over the input limit. No spending or bill analysis took place. Source-span and unit accounting establish that no text was silently discarded, **not** that every legal section was correctly identified or explained.

**Concrete section-boundary gap:** 18340 and 18343 are two versions of S. 1071, not two different bills. The latter has numbered headings split across lines (e.g. `8801.` followed by `Pilot program for sound insulation repair and replacement`). A text scan found 1,413 number-only lines followed by capitalized text; this is a diagnostic, not an authoritative count of sections. Many sections remain inside large units. Before paying to analyze this version, test its section inventory against the official XML structure and distinguish contents entries from operative headings.

## Stage 2: enable complete analysis within an approved budget (planned)

**Section inventory fix (implemented and locally verified).** The source-first
planner now aligns operative sections from stored Congress bill/amendment XML
to the existing citation text. For 18343: **1,134 matched, 0 missing, 0 extra,
0 duplicated**; all 3,370,908 source characters accounted for. This includes
one unnumbered opening resolution; 282 nested section elements are not counted
as separate bill sections. The section IDs, order and XML hash were pinned
independently. Run the full local regression with:

```sh
python manage.py benchmark_source_planner 18343 --expected-inventory apps/legislation/tests/fixtures/xml_inventory/s1071_eah.json
```

Graph including XML alignment: 11.880 s; planner: 0.183 s. The resulting plan
still refuses under existing limits (961 generation-budget, 166 unexplained
source, 7 input-limit). No provider was called. The earlier 36-unit result above
is the text-only baseline, not the current XML result.

1. Remove only provably non-operative duplication, e.g. repeated page furniture, with mappings to original text. Never strip strike/insert instructions, repeals, expiration dates, amounts or governing exceptions.
2. Batch by actual input size and expected output, not an arbitrary target number of sections. Replace the existing eight-unit/four-generation-call ceilings only with tested, explicit limits. Split oversized units at safe boundaries carrying their governing clauses, definitions and source offsets. Report indivisible or ambiguous units.
3. Validate findings against the source. Persist completed batches against exact source, prompt, schema and model identity. Interrupt and resume a test run: completed batches must not incur another charge. Show the full estimated cost and enforce the confirmed maximum **before** dispatch.
4. Write a short reader summary from verified findings, not a chain of increasingly lossy summaries. Keep detailed amounts, conditions, exceptions and citations accessible independently of the brief.

## Release gates

**Document 18343, full XML batch plan (local; no provider calls).** The large-XML
path uses the resumable full-text reviewer instead of the small provision planner.
Run the command above with `--summary-scenario` to reproduce. The pinned XML
inventory matched in order: 1,134 sections, none missing or duplicated, and
3,370,908 characters assigned to review without gaps or overlap. Planning took
15.7 seconds. A cold run needs 215 review calls. A simulation with one 160-character
finding per selectable passage required 49 summary calls (264 total); the real
number depends on the findings. The confirmed plan ranges from 216 to 438 calls.
Estimated standard-price cost: about $0.53 using four serialized bytes per input
token and prior local output usage. Conservative token-budget ceiling: $8.54
(rounded up). Neither figure is a charge. Section coverage measures what gets sent,
not whether a model will interpret it correctly.

- Dry-run accounting, zero/partial/reused cases and high-unit regression tests. Repeat timings on the same documents when changing limits or parsers.
- Before a paid large-bill run: verify against a pinned answer key that an amendment, a funding amount with its correct base, and a meaning-changing exception survive batching; missing evidence must never count as success.
- Separately evaluate whether a reader can explain purpose, affected people and money in 30 seconds. H.R. 9300 is a readability case, not a substitute for a large-bill coverage test.
