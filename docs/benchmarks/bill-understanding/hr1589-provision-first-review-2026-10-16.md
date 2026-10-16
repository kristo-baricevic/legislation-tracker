# H.R. 1589 provision-first evaluation

Status: **not release-approved; production worker unchanged**.

## What was changed

- Required one response per source-derived candidate, rather than checklist instructions alone.
- Tested explicit mappings first; live output still mapped unrelated summary statements to provisions.
- Added a provision-first mode: each assigned candidate must have its own explanation and evidence.
- Removed false financial matches for “appropriate” and duplicated contents entries.
- Added readable source locators rather than expecting the model to interpret character offsets.
- Split 31 candidates into four batches of at most eight; all batches retain the full source context.
- Added a mandatory-fine-versus-optional-fine regression and safe cross-chunk quote splitting. Neither semantic approval nor prose rewriting is performed by citation repair.

## Live evidence

Final artifact: `hr1589-provision-first-v2-2026-10-16.json`.
Four calls, 74,389 input tokens and 11,890 output tokens. No automatic retries.
The previous 16-item batch consumed its 8,000-token output allowance and failed;
eight-item batches all returned structured output within that same per-call cap.

The initial experiments remain separate artifacts, not overwritten results:
`hr1589-required-coverage-v2-2026-10-16.json`,
`hr1589-required-coverage-v3-2026-10-16.json`, and
`hr1589-provision-first-2026-10-16.json`.
The unsuffixed required-coverage artifact records a credential-entry failure.

## Original omissions: source-backed review

- `cov_e4cd4a0dec1b2858`: explains the removal-of-conditions fee substitutes for the initial application fee, subject to exemption.
- `cov_77ca243172266c2f`: includes continuing criminal/security eligibility, non-abandonment, alternative education/service/income routes, and the three-year AND 75% income condition with the enrollment adjustment.
- `cov_645923770e51e808`: includes continuing eligibility and non-abandonment alongside compelling circumstances and the additional hardship alternatives.
- `cov_9731deb40e450934`: includes the $10,000 maximum and knowing misuse, but incorrectly weakens “shall be fined” to “may be fined.” This is not approved.

This is an assistant review of specific source-backed expectations, not independent
human acceptance of the entire bill or a completed ten-bill benchmark.

## Remaining failures after offline replay

The replay asserted all saved request fingerprints matched current batch construction;
it made no provider calls. One citation spanning source chunks was safely split
into exact source excerpts. Original generated text and paid-run artifact remain intact.

| Candidate | Remaining finding |
| --- | --- |
| `cov_bc4c462ec3754d53` | Overlong explanation; two quotations do not match |
| `cov_44a3dcc8a37f708c` | One quotation does not match |
| `cov_f9b1f19a534655e7` | One quotation does not match |
| `cov_a35bf57c1131635c` | No valid supporting quotation for the explanation |
| `cov_9731deb40e450934` | Mandatory fine described as optional |
| `cov_3469918a44b3b085` | Parent surcharge entry omits $25 in its prose |

The last item also exposes overlapping parent/child inventory ranges: the child
is separately explained, but the parent claims coverage without the amount. Do
not silently count a neighboring explanation as the parent’s own evidence.

## Not completed

The candidate is not integrated with production worker leases, spending
confirmation, persisted public/private analysis schemas, or reader UI. H.R. 9300
and S. 5 have not been regenerated using this provision-first mode. No application
records were published, no running services were restarted, and no changes were pushed.
