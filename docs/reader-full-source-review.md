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
- Prompt version 8 produces a single `policy_changes` list covering financial
  and nonfinancial effects. Related definitions, dates and conforming edits are
  folded into their policy instead of becoming a page of separate clauses.
  All policy entries are shown with numbered source tooltips, without a second
  "Other changes" list. Long lists paginate six grouped explanations at a time,
  reserving the tallest page's height so navigation never shifts the layout.
  Money remains a complete,
  separate inventory. Original and older saved results retain their source data.
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

## Reader-level explanations

The audience has no legislative background. Use a short action heading and
normally 25–45 words explaining who is affected and what changes. Preserve
conditions that change the meaning; use the Money tab for the detailed financial
breakdown rather than repeating its entire ledger in the overview. There is no
fixed count of policy entries; every entry remains accessible through pagination.

A final size-bounded grouping pass combines related draft entries (for example,
a housing program's applications, eligibility, loans and reporting). The server
groups entries by their originating bill section before requesting prose, so the
model cannot simply return one explanation per draft clause. Very large sections
retain source-chunk subdivisions. Quoted amendments do not create outer sections.
Each output group has a fixed policy heading and its own schema description;
the model cannot shift a later policy into an earlier group's slot. Each input
entry must belong to exactly one output group. Rewrite packets target 24 KB of
serialized input, keeping whole groups together. Citations are inherited and
deduplicated by the server, not rewritten by the model. This does not establish
semantic equivalence automatically, but prevents silent omission of input entries
and retains the evidence for review. The original draft, group membership and
usage remain in the durable step records. Verified full-source inventories can
be reused for a presentation upgrade; Money is not regenerated unnecessarily.
Unabridged policy drafts are also retained with the stored review and excluded
from the reader API, so another presentation upgrade does not summarize an
already condensed explanation and progressively lose details.

Each selectable source passage receives an explained/context decision. Explained
passages must be cited by a policy entry; financial passages cannot be dismissed
as context. Exact source matching, complete sentences, length bounds, and guards
against quote IDs and amendment instructions apply before publication. One
bounded correction for wording/coverage failures is allowed within the existing
confirmed reserve. Repeated failure leaves the previous result intact.

`hr10906_policy_expectations.json` adds source-pinned policy coverage checks,
including nonfinancial policies. `evaluate_policy_review` reports entry and word
counts and flags concrete readability hazards. Neither those metrics nor passing
keyword checks prove that a child understands the explanation; human review is
still needed. Existing saved enhancements do not automatically incur new API
charges. H.R. 10906 is explicitly regenerated to verify this change live.
