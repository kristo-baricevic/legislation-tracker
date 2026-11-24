# Bill enhancement baseline

The local enhancement worker reported attempt 113 for S.4387 failed with `invalid_output` at 04:10:22 UTC on November 24, 2026. Attempts 112 and 110 also failed validation. Attempt 111 ended with an unknown provider outcome. No new generation was used to establish the baseline.

The starting checkout was `0cd1c46` with pending reader, transport and validation changes. These historical attempts cannot establish the behavior of a new adapter.

The harness fixtures under `apps/legislation/tests/fixtures/harness/` pin official XML bytes and extracted text separately. The two short documents include exact text and annotated character spans. S.4387 authorizes $15 million **per fiscal year** for 2027 through 2029. H.R.9300 uses the full annual appropriation for the 2% Tribal reservation and the remaining appropriation for the 20% minimum.

Document 18343 is bill 15571, S.1071, House engrossed amendment, 119th Congress. Its 3,370,908-character text and XML hashes were measured from the local source store. Its XML hash matches the existing 1,134-section inventory. Sections 8805 and 8806 supply reviewable deadline and conditional-action examples. This sample alone cannot certify the whole bill’s financial coverage.
