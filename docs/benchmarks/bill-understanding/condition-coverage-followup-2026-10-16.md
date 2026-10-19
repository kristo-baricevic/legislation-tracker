# Condition preservation and source coverage: implementation follow-up

## Implemented

- Conditional lists remain one complete source-backed group rather than independent sufficient conditions. Nested alternatives, exceptions, and wrapped references are retained. The reader uses the existing expandable source fallback where a safe paraphrase is not available; this is a correctness improvement, not a claim of finished plain-English presentation.
- Group preservation is distinguished from an uninterpretable clause. Existing supported financial extraction and high-level synopsis recognition remain available; genuinely ambiguous branches still suppress unsafe interpretations.
- ASCII `--` introductions now carry context like Unicode dashes. This matters for the actual pinned GovInfo text, not just clean XML fixtures.
- H.R. 9300's financial percentage bases retain exclusions after a legislative heading. The 20%, 5%, and technical-assistance 2% entries no longer incorrectly use the gross appropriation base.
- Source-packet 1.2 uses complete document sections, with all citation chunks selected together. It does not fall back to incomplete extracted fragments. Selected/omitted ranges and unresolved lexical section references are recorded explicitly. Contents entries are not counted as operative sections.
- Model input uses layout-only whitespace compaction with the same rules as citation matching. Verbatim snapshots and original offsets are retained. No dollar values, words, punctuation, conditions, or token-budget limits were changed to make a packet fit.
- Prompt 1.3 requires complete AND/OR conditions and distinguishes missing input from genuine ambiguity. Prompt instructions are not proof of semantic correctness.
- The whole-bill harness now prepares the current production source policy offline, separately from historical AI replay, and labels that distinction in its reports.

## Three-bill rerun

See `condition-coverage-2026-10-16.json` and `.md` for full regenerated NLP, evidence, prepared packets, and historical AI replay.

| Pinned version | Current request bytes | Complete current source packet | New NLP items | Historical AI items |
|---|---:|---|---:|---:|
| H.R. 9300 introduced | 24,098 | Yes | 25 | 19 |
| H.R. 1589 introduced | 59,694 | No | 167 | 26 |
| S. 5 enrolled | 19,046 | Yes | 14 | 10 |

All six output assessments have zero mechanical evidence failures. **This is not a semantic pass.** The previously identified AI factual errors remain in the saved responses, and the broader reader-quality findings remain open except where specifically corrected above.

H.R. 1589 still omits complete sections 306–313 under the unchanged single-request budget. Compaction improves coverage, but does not make the whole bill fit. Those sections include important financial provisions. A full-coverage AI analysis therefore still needs a separately budgeted multi-pass implementation or an explicitly revised budget; it must not be presented as solved by this change. Source selection now reports the omission instead of disguising it as a complete analysis.

No new AI generations or paid provider requests were made. Historical replay does not verify how the model responds to the revised prompt/packet. No running application service was restarted and no production database was backfilled. Changes are local and unpushed.

## Verification

- Regression tests were observed failing before fixes for independent eligibility conditions, nested alternatives, wrapped references, pinned H.R. 9300 percentage bases, section-level packet atomicity, omitted-reference coverage, and false contents coverage.
- Focused checks cover source compaction without lexical loss and citations mapping back to exact original offsets, plus preservation of existing fee behavior.
- Full PostgreSQL/Redis suite: **1,122 passed, 1 failed, 1 skipped**, 102.35 seconds. The skipped SQLite fallback was then run on SQLite and passed (the SQLite partition module: 3 passed, 3 PostgreSQL-only skips already covered in the full run).
- Remaining test failure: `apps/accounts/tests/test_recommendations_performance.py::test_synthetic_postgresql_query_and_latency_budget`; cached recommendations took 264.79 ms against a 250 ms limit. A preceding run measured 257.53 ms. No threshold was relaxed and this result is not reported as green. Query-count checks passed. This is outside the changed NLP/source-packet code; the timing cause was not diagnosed here.
- An additional nested-condition regression passed after the full run, with no subsequent production-code change.
- Ruff checks on changed extraction/source/evaluation files and `git diff --check` passed.
- Test infrastructure was isolated from the application database. An initial sandbox networking failure was diagnosed and the suite rerun with access to the isolated local services.

## Remaining acceptance work

1. Complete multi-pass source coverage for oversized bills, with explicit total-call/cost confirmation before paid execution.
2. Generate fresh AI output using the new policy and review against the unchanged answer keys. Do not reuse the historical AI success status as acceptance.
3. Address the remaining synopsis, eligibility/definition, financial-inventory, and readability findings in `semantic-review-2026-10-16.md`.
4. Keep semantic and actual-screen acceptance blocked until those checks are performed. Safe source fallback is preferable to a false explanation, but is not the final reading experience.
