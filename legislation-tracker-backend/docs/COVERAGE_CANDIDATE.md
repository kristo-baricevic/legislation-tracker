# Source-checklist evaluation candidate

Status: these earlier candidates remain evaluation-only. A separate feature-gated
production implementation is documented in [SOURCE_FIRST_ANALYSIS.md](SOURCE_FIRST_ANALYSIS.md).
This is not a completed production coverage gate.

The candidate uses the pinned bill text, not its answer key. It builds structural
source ranges for financial vocabulary and conditional introductions. Child
conditions remain in their governing range. Source hashes and offsets are
validated. This is a **candidate inventory**, not proof of exhaustive extraction;
incorporated law, amendments, percentages without matched vocabulary, and unusual
wording still need review. Amount matching currently recognizes dollar notation,
not all equivalent written-number forms.

The initial request includes source references and short opening/closing locators
for each candidate, plus instructions to explain financial types and complete
conditions. Version 2 requires a `coverage_response` object with every candidate
ID present exactly once and no unknown IDs. Each entry must either map to
explanations (`explained`) or give a nonempty limitation (`unresolved`). The real
provider receives this required schema, not just a prompt instruction.

Mapped paths must exist and have matching evidence in that candidate's range.
Amount checks use only those mapped explanations; unrelated output cannot satisfy
them. Empty, contradictory, duplicate-path, missing-ID and unsupported mappings
fail. Unresolved entries remain visible in the report and block approval.

The post-generation assessment checks
whether a valid, uniquely located quote overlaps a candidate and whether that
candidate's explicit dollar amounts appear in the associated explanatory prose.
A quote containing a number does not count as explaining the number. Neither a
quote match nor a dollar match proves the actor, legal effect, modality, scope or
AND/OR logic: remaining rows are `needs_semantic_review`, never `pass`.

If mechanical gaps, invalid citations, or condition groups need review, the
candidate can make one correction call. It receives the original source,
checklist, findings, and previous explanatory prose when that prose fits the
budget. If necessary, the prior draft is omitted explicitly; full source and
findings are retained. It regenerates the complete
output; this is not an append-only repair. Every output item is revalidated and
the inventory reassessed afterward. The same byte/token caps apply. If the
correction request exceeds the budget it is not sent. There are no retries or
additional paid citation repairs. The total ceiling is two calls, each with the
configured output cap. Provider usage is retained per call and aggregated;
unknown usage remains unknown, not zero.

Inventory regression tests distinguish `appropriate court` from an appropriation
and exclude mixed-case contents entries when the corresponding uppercase
operative heading follows. These are conservative heuristics, not a general
financial parser or proof of inventory completeness.

## Commands

From the backend directory, with the project's virtual environment:

```sh
rtk proxy .venv/bin/python manage.py evaluate_coverage_candidate --case BILLS-119hr1589ih
```

This validates pinned source provenance and prints the planned budget without
calling a provider or requiring an API key. To explicitly authorize paid calls:

```sh
rtk proxy .venv/bin/python manage.py evaluate_coverage_candidate \
  --case BILLS-119hr1589ih --execute --prompt-key \
  --output /private/tmp/hr1589-checklist-new-run.json
```

The key is entered without terminal echo; it is not saved in the artifact.
Alternatively configure `LLM_ENHANCEMENT_EVALUATION_API_KEY`. An existing output
file prevents repeat spending/overwrite. Outputs and usage are saved for review;
no bill, contract, enhancement, or user record is changed. A nonzero command exit
means the release gate is not approved, not necessarily a failed provider call.

The normal `evaluate_reader_quality --suite whole-bill --replay ...` report also
includes source-derived `coverage_candidates` and `candidate_coverage` for saved
AI outputs. These diagnostics supplement, not replace, the independent answer-key
review.

## Before production integration

1. Review inventory completeness and false positives on H.R. 1589, H.R. 9300 and S. 5.
2. Grade new generations against independent answer keys, including fee
   substitution, the fine, and the complete eligibility groups.
3. Resolve remaining semantic failures; do not turn lexical checks into legal
   correctness assertions.
4. Integrate only the validated policy with worker leases, cost confirmation,
   persisted failure details, and reader-visible unresolved items. The evaluation
   runner is not a substitute for that production lifecycle.

## Provision-first experiment

`--provision-first` replaces summary generation plus correction with up to four
disjoint batches, at most eight candidate provisions per batch (32 overall). All
requests must fit the existing input cap before either is dispatched. Each sees
the full source packet for internal references; only the assigned explanations
are partitioned. Each candidate has its own required text, evidence, and explicit
unresolved status. There is no category mapping and no extra paid repair call.

This tests whether generating explanations before a synopsis avoids summary-first
compression. It does not invent a whole-bill synopsis or count the inventory as
exhaustive. Valid quotations and dollar coverage still require semantic review.
The separate `provisions` artifact shape is **not** the application's persisted
enhancement schema; it is not the new source-first production contract.
