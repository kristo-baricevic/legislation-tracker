# Shared bill enhancements

Bill enhancements are generated from public bill sources, not user prompts. Completed results and pending/running work are reused across signed-in users. Existing results are reused in place; no paid backfill is needed.

Reuse requires the active document ID and text hash to match. Reader-schema results also require the same extraction contract ID/hash so item explanations cannot attach to a different provision inventory. Prompt/model setting changes alone do not invalidate a usable result. Changed bill text is a distinct analysis. Partial results and failed/refused/unknown outcomes are not treated as completed shared analyses.

Creation and retries lock the bill row before looking for shared work. The existing owner/request uniqueness remains for private audit history; the bill lock serializes cross-user creation. The second caller returns the existing job without dispatching another attempt or requiring their API key. An owner retry also checks for another user's completed/in-progress work first.

API keys, credential revisions, usage and attempt diagnostics are not exposed to other users. Attempt history remains payer-scoped. Only the owner may retry a specific attempt; other users may explicitly authorize a new attempt with their own key after a failure. Failed/unknown calls may still have incurred provider charges: this prevents duplicate completed generation, not all retry charges.

Migration 0021 preserves shared results when the paying account is deleted by clearing payer attribution instead of deleting the result. Apply it before API deployment. No live paid requests are needed to activate sharing. Reverse migration requires handling rows with null payer attribution first.

The current endpoints still require sign-in. Personalized prompts are not supported by this cache and must use a separate scope if introduced later.
