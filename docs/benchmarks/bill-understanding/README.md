# Bill-understanding benchmark: source-backed answer keys

Prepared October 7, 2026. These are internal evaluation references, not the
reader-facing summaries. They were written from the pinned official text,
without using the application's generated analysis as the answer key.

**Status: eight full-source draft keys; two partial omnibus keys.** All keys
are assistant-authored source reviews, pending independent human acceptance.
“Full-source” describes review scope, not a certification of legal accuracy.
This does not yet constitute ten completed, approved benchmark cases.

## Pinned cases

Each link opens the answer key, including source passages and section citations.
Congress and version are part of the identity: do not substitute another version.

| Bill | Pinned version | Why it is included | Answer-key coverage |
|---|---|---|---|
| [H.R. 9300 — Postsecondary Student Success Act](answers/BILLS-119hr9300ih.md) | 119th, introduced | Grant eligibility, funding authorization, nested percentages, definitions | Full-source draft |
| [H.R. 1589 — American Dream and Promise Act](answers/BILLS-119hr1589ih.md) | 119th, introduced | Eligibility alternatives, exceptions, fees, indefinite authorizations | Full-source draft |
| [S. 619 — COVID-19 Origin Act](answers/BILLS-118s619enr.md) | 118th, enrolled | Short bill, disclosure duties, deadline, no specified funding | Full-source draft |
| [S. 777 — Veterans' COLA Act](answers/BILLS-118s777enr.md) | 118th, enrolled | Formula-based money with externally determined rates | Full-source draft |
| [H.R. 8404 — Respect for Marriage Act](answers/BILLS-117hr8404enr.md) | 117th, enrolled | Recognition rules, religious safeguards, preserved benefits | Full-source draft |
| [S. 5 — Laken Riley Act](answers/BILLS-119s5enr.md) | 119th, enrolled | Conjunctive eligibility, arrest versus conviction, financial harm thresholds | Full-source draft |
| [H.R. 7024 — Tax Relief for American Families and Workers Act](answers/BILLS-118hr7024eh.md) | 118th, House-engrossed | Tax ceilings, elections, retroactivity, penalties; not an enacted-law fixture | Full-source draft |
| [H.R. 3746 — Fiscal Responsibility Act](answers/BILLS-118hr3746enr.md) | 118th, enrolled | Caps versus appropriations, rescissions, debt authority, benefit conditions | Full-source draft |
| [H.R. 1 — reconciliation law](answers/PLAW-119publ21.md) | 119th, Public Law 119-21 | Large multi-policy law; appropriations, amendments, fees, rescissions | **Partial; not whole-bill gold** |
| [H.R. 4366 — Consolidated Appropriations Act](answers/BILLS-118hr4366enr.md) | 118th, enrolled | Multi-division appropriations, account restrictions, transfers | **Partial; not whole-bill gold** |

## What each key records

- Purpose, affected people, changes, and material conditions or exceptions.
- Financial expectations: purpose, amount or formula, timeframe, restrictions,
  and whether a provision appropriates, authorizes, limits, rescinds, taxes,
  charges, or merely sets a threshold. Missing dollar amounts are not zero.
- Exact supporting source passages and section/subsection citations.
- Prohibited inferences and unresolved dependencies on prior law or external data.
- Section coverage. The two partial keys explicitly list unfinished scope.

Financial rows are **not necessarily distinct payments or unique provisions**:
some record a shared formula, a nested allocation, or an exception. Never sum
them blindly or use row counts as an automatic recall denominator. Whole-section
evidence preserves qualifiers but still requires checking that the concise
expectation accurately represents them.

## Source integrity and verification

Original GovInfo HTML snapshots are in `sources/`. The [source manifest](sources/manifest.json)
records their URLs, SHA-256 hashes, and decoded text paths. Retain these files
when evaluating a new pipeline version; do not silently fetch replacement text.

Run from the repository root:

```sh
rtk proxy python3 docs/benchmarks/bill-understanding/prepare_sources.py
```

This rebuilds derived text and checks that Markdown blockquotes appear in the
source after whitespace normalization. Results are saved in
[source-check-report.json](source-check-report.json). It does **not** verify
interpretations, the claimed section location of repeated text, or exhaustive
coverage. A successful run is not a passing NLP evaluation. The script records
current hashes; compare against the committed manifest to detect source drift.

The two `*.financial-candidates.json` files are broad, unreviewed source worklists.
Their matches may overlap, include nonfinancial material, or miss provisions.
They are never expected answers or proof of financial completeness.

## Remaining before using this as a release gate

1. Finish every operative section and financial provision in H.R. 1 and H.R. 4366.
   H.R. 1 currently covers selected provisions only; H.R. 4366 covers the opening
   rules and four military-construction accounts, not the remaining divisions.
2. Independently accept or correct the answer keys, especially scope, exceptions,
   amended-law dependencies, and financial classifications. All ten are pending
   human acceptance; none is approved release-gate gold yet.
3. Convert accepted expectations into harness fixtures with unique provision IDs
   and explicit parent/suballocation/exception relationships. Use separate checks
   for factual accuracy, completeness, money semantics, conditions, citations,
   unsupported claims, and understandable presentation.
4. Score generated output against those accepted expectations. Unreviewed source
   regions are unscored, not passing; unresolved outside context requires an
   explicit abstention rather than a guessed answer.

## Step 3: provisional three-bill baseline

The existing `evaluate_reader_quality` command now includes a `whole-bill`
suite for H.R. 9300, H.R. 1589, and S. 5. From the backend directory:

```sh
rtk proxy env DATABASE_URL=sqlite:///:memory: .venv/bin/python manage.py evaluate_reader_quality --suite whole-bill --output ../docs/benchmarks/bill-understanding/baseline.json
```

This runs the real deterministic extractor on pinned text without database
writes or provider calls. It writes JSON and a companion Markdown report before
returning a **nonzero exit status**: the release gate remains blocked until
independent answer-key acceptance and semantic/UI review. The current runner
does not ingest review decisions or certify a passing release.

The [initial baseline](baseline-2026-10-15.md) separates coverage, accuracy,
source support, readability, and honest uncertainty. JSON contains the full
output, evidence, and an unreviewed worksheet for each answer-key expectation.
Source offsets and word counts are mechanical checks, not proof of meaning.
Review unsupported additions as well as missing expectations; verify financial
items are accessible on the actual screen. Keep source and answer hashes with
any completed review.

AI is explicitly `not_run` unless `--replay path/to/artifact.json` supplies a
matching saved artifact. Its top-level `results` list must include, per case:
`case_id`, `source_text_sha256` (the pinned decoded text hash),
`status: "succeeded"`, `source_snapshot`, and `output`. Source snapshots must
include exact `start_char`, `end_char`, and `quoted_text` spans in that text,
plus the source-reference fields required by the production enhancement schema.
The production output validator is applied. Optional `usage`, `resolved_model`,
and `truncated` fields are retained; missing or true `truncated` flags unknown
or partial AI input coverage. Never add a hash to an old artifact without
verifying the text it actually used. Existing artifacts lacking provenance
cannot be credited as this benchmark's AI run.

No live analysis, database data, or stack configuration is changed by running
this suite. Both omnibus keys remain excluded from whole-bill scoring.
