# Source checklist evaluation — 2026-10-16

## Outcome

The source-accounting safeguards are implemented. **The three-bill release gate still fails.** These changes do not establish whole-bill accuracy, and no evaluation output was published to the app.

Final recorded run: `source-checklist-v10-20261016-200414-BILLS-*.json`, model `gpt-6-luna`, prompt `source-first-10`. Accepted sections from earlier runs were revalidated and reused; these are targeted retries, not three fresh full generations. Source texts and independent answer keys remain pinned.

| Bill | Sections passing mechanical checks | Calls in final retry | Remaining blockers |
| --- | --- | --- | --- |
| H.R. 9300 | 4/5 | 3 | Section 5 omits the financial entry for required uses of grant funds; its repair failed wire validation. |
| H.R. 1589 | 13/22 | 5 | Missing financial entries, comparator/condition checks, malformed responses and an output-limit failure. Section 203 also genuinely requires absent outside-law context. |
| S. 5 | 2/3 | 3 | Enforcement section has conditions assigned to unmapped source blocks and invalid/incomplete financial threshold representation. |

Counts include short-title sections and are **not** semantic coverage percentages. All accepted rows were revalidated offline after the final repeated-condition fix. Rejected available responses were also rechecked: some false rejections disappeared, but no rejected section became fully valid. No further provider calls were made for this check.

## Implemented

- Partition each owning source passage into deterministic, lossless blocks before generation; keep full owning passages and supplied context available.
- Require every block to map to claims and explanations, or carry an explicit unresolved reason. Preserve source access for rejected sections.
- Let the model supply short source IDs and explanations on each claim. Build numeric indexes on the server, eliminating out-of-range model-generated indexing.
- Require financial entries for recognized financial candidate blocks, including restricted uses of funds without fixed dollar amounts.
- Check that quoted conditions occur in the mapped source blocks or supplied context, rather than merely somewhere in the section.
- Reject visibly unfinished reader sentences; allow more short explanations instead of cramming many rules into twelve paragraphs.
- Reserve estimated output space when batching; keep existing hard call/output ceilings.
- Record reused rows for reproducible offline replay. Review packets include source accounting and readability measurements over details as well as summaries.

The inventory is source-block accounting, not a complete inventory of legal propositions. Financial signals are heuristics. Matching a quote or assigning a source block does not establish semantic entailment. Independent meaning/readability review remains necessary.

## Validation

Final backend command:

```sh
rtk proxy env DATABASE_URL=sqlite:///:memory: LEGAL_NLP_V21_WRITE_ENABLED=False LLM_ENHANCEMENTS_ENABLED=False .venv/bin/pytest -q
```

**1,285 passed; 15 skipped**, with two existing Django deprecation warnings. Skips include PostgreSQL-specific tests, the opt-in synthetic benchmark and Redis-dependent coverage. This turn does not establish PostgreSQL/Redis or frontend acceptance.

Earlier attempts inherited the app database/feature flags: the first could not connect under sandbox restrictions; the SQLite rerun still inherited enabled features and failed nine default-state assertions. The explicit test-only overrides above resolved those environment mismatches without changing app configuration.

Independent review found two validator defects: schema-valid `0.0` indexes could crash indexing, and repeated condition searches stopped after two occurrences. Both have regression tests; the third-occurrence test was observed failing before the fix. Ruff checks and tracked whitespace checks passed.

## Remaining work, not completed by these safeguards

1. Repair remains section-level. A failed claim can still reject its whole section; preserving accepted claims within that section needs claim-level repair/merge semantics and tests.
2. Wire failures still report `source_first_wire_schema`, without the exact safe schema path/reason. Preserve bounded diagnostic codes before another paid retry, so malformed output can be distinguished from source-assignment failures.
3. Resolve the actual remaining money/condition failures against source passages; do not weaken validators just to improve pass counts. Existing comparator/scope checks can also overreject and need adjudication.
4. Reassess output sizing for dense sections: the 80-token-per-block planning estimate did not prevent one provider output-limit failure.
5. Complete independent answer-key review and actual-screen comprehension checks only after generation is usable. Mechanical acceptance is not the release gate.

Earlier artifacts from this work are retained under `source-checklist-live-20261016-195019-*` and `source-checklist-retry-20261016-195818-*`. They are historical diagnostics, not evidence of a current pass.

No app restart, feature enablement, publication, commit or push was performed for this work.
