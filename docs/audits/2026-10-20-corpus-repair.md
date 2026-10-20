# Corpus completeness repair — 2026-10-20

## Scope and result

Rechecked the same 8,605 bills as the initial audit (IDs 1–8605). Ingestion remained running, so newly ingested bills are outside this fixed comparison cohort. The active-document backfill itself checked 8,830 documents, including newly ingested bills.

| Check | Before | After |
| --- | ---: | ---: |
| Active source with no reader line items | 107 | 0 |
| Missing latest analysis | 211 | 0 |
| Marked complete despite missing basic analysis/source | 72 | 0 |
| Missing usable active text | 189 | 5 |
| Missing summary | 189 | 5 |

The five remaining text/summary exceptions are IDs 3, 4665, 4753, 6241 and 8046: Congress records titled **Reserved for the Speaker** (H.R. 2, 10, 5, 8 and 3 respectively). Congress's text-version API returned no versions. They remain processing, not complete, with discovery scheduled to recheck publication.

All 8,600 records with active text have a document-backed 2.1 reader analysis. Automated checks found no invalid evidence offsets, missing display citations, or empty reader breakdowns in this cohort. These checks establish structural integrity, not universal factual or semantic completeness.

## Repairs

- Recovered all 267 originally dead-lettered HTTP 429 downloads. A Congress XML throttle can fall back to the exact same version on GovInfo; repeated throttles retain durable work and honor Retry-After without exhausting the ordinary failure budget.
- Zero-version discovery remains scheduled instead of succeeding permanently before source text appears. Rechecking the 18 remaining missing-document bills recovered 13 published versions.
- Metadata-only fallbacks cannot mark a bill complete or overwrite an existing document-backed analysis.
- Preserved unquoted amendment instructions, funding reauthorizations, penalty formulas, proportional grant reductions, relative deadlines and deeply nested eligibility alternatives.
- Distinguished inserted law from deleted/background quotations, including nested insertion instructions and conforming-table language.
- Fixed statutory abbreviations splitting sentences, nested amendment target inheritance, long official titles being rejected, and taxes on transfers being mistaken for transfer instructions.
- Retained complete source wording when a conditional or nonbinding provision cannot safely be simplified. This is explicitly source-preserving output, not a claim that it has become a polished plain-English explanation.
- Indexed structural parents and bounded quote-classification caching to remove repeated whole-document scans during extraction.
- Added regression tests for the confirmed failures and negative examples, including deleted quotes, nonbinding language, conditional formulas and retry behavior.

## Remaining source interpretation warnings

Three bills retain `incomplete_amendment_extraction` and are not marked complete. Their original stored XML was inspected, not just the flattened text:

- **877 / H.R. 1923**, document 1053: an instruction says a section “is amended—” immediately before quoted subsection (d), without specifying the operation. Another nearby insertion is explicit, but it is a different provision.
- **2665 / H.R. 4275**, document 3477: the marine-inspector pay provision says a subsection “is amended as follows” before quoted replacement-like language, without an explicit replacement instruction.
- **3182 / H.R. 7390**, document 4209: a substantial federal-preemption quotation follows an instruction that only inserts cross-reference numbers into a different section. The XML does not establish the quotation's intended insertion point.

The source remains available. No inferred amendment operation was substituted merely to remove a warning.

## Coverage limitations

The broad lexical screen still identifies potential coverage gaps: 1,248 bills with monetary matches, 1,986 with definition matches, 1,667 with deadline matches, 1,121 with percentage matches, and 1,835 with duty matches outside the corresponding category's evidence. These sets overlap. They include references, deleted text, historical statements and provisions represented elsewhere; they are **review candidates, not confirmed bug counts**. This repair does not certify every extracted legal meaning or every possible omission across the corpus.

## Reproduction artifacts

Final verification: **1,476 backend tests passed, 15 skipped**. Skipped tests remain unverified, not counted as passing. Frontend type checking and the focused financial-ledger component tests passed during this repair. The live bill page returned HTTP 200 after the final API/worker reload. Final processing states: 8,597 complete, three explicitly incomplete, five awaiting published source.

- Original screening data: `/tmp/legislation-corpus-audit-20261020.json`
- Post-repair screening data: `/tmp/legislation-corpus-audit-after-20261020.json` (completed 20:42 UTC; the empty-table warning for bill 7099 was separately repaired afterward).
- Corpus processing records: `/tmp/legislation-repair-corpus-v21-{0,1,2,3}.jsonl`
- Confirmed regression tests: `apps/legislation/tests/test_corpus_completeness.py`, `test_inserted_amendments.py`, and ingestion download/task tests.

No LLM calls were made during this corpus repair. Local database backfills are not part of the Git changes; other deployments must run their own backfill after applying the code and migrations.
