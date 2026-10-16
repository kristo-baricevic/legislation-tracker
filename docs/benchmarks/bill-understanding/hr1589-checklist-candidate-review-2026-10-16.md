# H.R. 1589 checklist candidate: not ready for production

## Implementation and execution scope

An evaluation-only source inventory and one-correction runner were added. They
do not load answer keys during generation or update application records. The
normal whole-bill replay report now includes candidate-coverage diagnostics.
The production worker has not been changed.

The candidate detects 41 source ranges in H.R. 1589. These are review candidates,
not a verified count of all independent provisions. Against the prior full-source
output, it reports 22 ranges without overlapping explanatory evidence and two
with dollar amounts missing from linked prose. The $10,000 fine is correctly
identified as absent. These are mechanical signals, not semantic verdicts.

## Paid experiment

Artifact: `hr1589-checklist-candidate-2026-10-16.json`.

- Two calls; 41,873 input tokens and 6,254 output tokens total.
- Both provider requests returned output. Validation failed; output was not
  published to the app.
- The second output includes the fee-substitution rule, but still omits the
  $10,000 confidentiality fine.
- `uncertain_language[0]` falsely says the fee-exemption list does not establish
  alternatives. The quoted text explicitly says “or” before the final alternative.
- `funding_and_timing[6]` assigns the appointed-counsel procedures to the Secretary,
  while its own source quote names the Attorney General.
- `key_impacts[3]` still omits continuing eligibility and nonabandonment from the
  condition-removal rule. The source inventory itself retained the complete group.

## Experimental wiring defects found and fixed afterward

1. The provider adapter sends `bill` and `source_packet`, not arbitrary envelope
   fields. Correction findings and previous prose had been added at the envelope
   root and were therefore not transmitted. They now reside in `source_packet`.
   A test exercises the real provider adapter with a fake network transport and
   inspects the actual transmitted input.
2. A citation validation failure suppressed all inventory checks. Structurally
   valid output now still receives coverage checks; invalid quotes cannot establish
   coverage, and the whole response remains failed.
3. The runner now retains the existing safe, specific validation diagnostics,
   including schema field paths, rather than only `invalid_output`.

The first paid artifact predates these fixes. It must not be presented as evidence
for the corrected runner.

## Corrected-run result

`hr1589-checklist-candidate-v2-2026-10-16.json` is a second, separately saved run
after those fixes: two calls, 44,237 input tokens and 7,858 output tokens total.
The correction was actually transmitted this time.

- `key_impacts[8]` now explains the $10,000 fine and knowing misuse of information.
- `funding_and_timing[3]` correctly presents the fee-exemption groups as alternatives.
- `obligations[8]` correctly identifies the Attorney General for appointed-counsel procedures.
- The explicit no-double-fee/substitution explanation is absent again.
- `key_impacts[3]` says “every route also has additional requirements” rather than
  explaining continued eligibility and nonabandonment. This is still inadequate.
- The final output also fails `citation_reference_mismatch` at
  `/overview/0/source_quotes`; the first output failed `citation_quote_not_found`.
- Mechanical diagnostics report 17 source ranges without overlapping explanatory
  evidence. Two further missing-amount flags were false positives for `$495.00`
  versus `$495`; numeric-equivalence handling and a regression test were added
  afterward. The saved artifact retains the original diagnostics, not rewritten
  results from newer code.

Neither live run is release-approved. Combined actual usage across the two
experiments was 86,110 input tokens and 14,112 output tokens (four calls).

## Remaining work

- Add required per-provision response mapping before another paid generation:
  each inventory ID must map to an explanation or an explicit unresolved entry.
  The present source checklist is guidance, not an enforceable response contract.
  Matching dollar values does not prove preserved eligibility logic.
- Then grade the new output against the independent answer key and test the other
  two pinned bills before promotion. Their live generations were not run here.
- Production integration still needs confirmed budgets, worker lifecycle support,
  and reader-visible unresolved provisions. Do not enable this experimental runner
  as a production validator or claim the approved plan is fully implemented.
