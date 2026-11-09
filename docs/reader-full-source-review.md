# Full-source enhancement review

The reader enhancement now has two inputs: the existing NLP items for in-place
explanations, and an independent scan of the entire exact bill document. The
second input does not depend on which financial provisions NLP recognized.

## Publication contract

- Every character belongs to a review source chunk; large sections are split,
  not truncated. Adjacent context is supplied for interpretation.
- Preflight accounts for every review call and its input/output allowance. If
  the complete plan cannot fit the configured budget, no paid work starts.
- Each chunk returns a financial inventory and missing nonfinancial changes.
  Money-related passages require an explicit financial/not-financial decision.
  A financial decision must have a corresponding cited financial entry.
- Citations use server-owned passage IDs and resolve to exact source text.
- Publication requires every planned review chunk and source evidence for
  financial provisions already found by NLP. Failure leaves the prior saved
  enhancement and the original analysis untouched.
- The AI Money tab uses the full-source financial inventory, including amount
  labels, rather than overlaying prose on the NLP ledger's amount fields. The
  Original switch retains the original NLP ledger. Older saved enhancements
  without a source review retain their prior behavior.
- Missing nonfinancial changes are displayed alongside the existing enhanced
  changes. Both views use source annotations and pagination.
- Existing shared enhancements remain reusable across users. A prompt change
  does not automatically charge users to regenerate every saved bill. The
  H.R. 10906 replacement is an explicitly authorized administrative run.

## Regression: H.R. 10906, 119th Congress, Introduced in House

The pinned source is `apps/legislation/tests/fixtures/reader_evals/hr10906_119_ih.txt`
in the backend (stored document 19587).
`apps/legislation/tests/fixtures/financial_review/hr10906_financial_expectations.json`
contains twelve source-derived checks:
mass-timber credit and multiplier, biomass investment credit, separate 95%/5%
fund uses, first/additional housing grant ranges, repayment, the biochar capital
cost cap, both base deduction increases, disaster limits, and recapture.

`evaluation.financial_review.evaluate_financial_review` checks that the expected
amounts/conditions are present in entries citing the relevant source passage.
Negative tests remove provisions, change amounts and substitute unrelated
citations. Tests also exercise publication with no NLP financial targets and
the client-side amount display, pagination, filters and source links.

These checks are not proof of legal entailment or exhaustive extraction. The
financial/not-financial classifications and explanations still require semantic
review; a correct citation alone does not establish a correct explanation.

## Size-based requests and recovery

- Reader batches are packed using serialized input size and estimated output
  bytes based on text, evidence, citation and JSON size, with reasoning headroom.
  There is no fixed provision-count limit; short items can share a request.
- A truncated response is never published. Only its failed batch is divided
  at a size-weighted midpoint, retaining the governing source context. Completed
  batches are not reissued. A single indivisible item fails with a diagnostic.
- Preflight reserves up to eight additional calls within the configured call
  ceiling and includes their maximum input/output allowances in confirmation.
  This bounds recovery cost; it does not cap the number of provisions.
- Each paid call is recorded before dispatch. Validated responses are saved
  immediately in existing enhancement-step records. An explicit retry of the
  same enhancement reuses successful steps without another provider call.
  An ambiguous dispatch is not automatically replayed.
- Usage totals come from durable step records so a cache hit cannot erase
  already incurred token usage. Reused results retain their resolved model.
- Compatible validated legacy explanations may be reused for an explicitly
  requested full-source upgrade. Exact target identities and source slices must
  still match; the summary and full-source inventory are regenerated.
- Quoted amendments stay with their enclosing section. Neighboring complete
  sections are not supplied as uncitable context, avoiding cross-batch duplicates.
  Oversized sections retain their own governing context; requests exceeding the
  configured input allowance are rejected before payment.
