# Reader-quality evaluations

The goal is an understandable explanation with complete, correctly qualified money
items and usable source citations—not merely valid JSON.

## Free, offline runs

From the backend directory:

```sh
rtk proxy .venv/bin/python manage.py evaluate_reader_quality --output /tmp/reader-nlp.json
rtk proxy .venv/bin/python manage.py evaluate_reader_quality --case hr9300-119-ih --replay /tmp/ai-results.json --output /tmp/reader-ai.json
```

These commands make no provider calls and do not modify the database. NLP mode
runs the actual v2.1 extractor and renderer. Replay checks a saved provider result
against the same annotated facts, validates its schema and source hashes, and
checks exact quotations. A failure writes its report before exiting nonzero.
Missing case results fail; they are not silently skipped. Select `--case` when
replaying only one case. Legacy schema 1.1 results remain evaluable.

Hard checks: annotated-fact recall, forbidden claims, all expected financial
items, sentence fragments, exact duplicates, source-reference/quote integrity,
extraction fallback, and whole-bill absence assertions from truncated inputs.
Financial annotations include amount units, minimum/maximum qualifiers, purpose,
and percentage bases, all required within the same displayed item.

Other metrics: item length, entries over 60 words, broad citations, runtime,
token usage, and optional cost. Unknown usage/cost is null, not zero. Supply both
`--input-usd-per-million` and `--output-usd-per-million` using verified prices for
the recorded model to estimate cost; this is not an invoice and does not account
for cached-token discounts. Failed requests without known usage remain unknown.

To enforce readability in a release gate, add `--max-item-words 60`. Without this
flag, length is reported but does not obscure independently measured factual
regressions. The current H.R. 9300 NLP output still exceeds this stricter gate:
the initial implementation fixes omissions and qualifiers, not all legal prose.

## Bounded live AI evaluation

```sh
rtk proxy .venv/bin/python manage.py evaluate_bill_enhancements \
  --execute --reader-case hr9300-119-ih --case-limit 1 \
  --max-input-tokens 30000 --max-output-tokens 4000 \
  --fail-on-quality --output /tmp/ai-results.json
```

Requires the separately configured `LLM_ENHANCEMENT_EVALUATION_API_KEY`.
It never reads a user's saved key. Every selected request is budget-checked before
the first paid call. Limits must also fit application safety caps. Input estimates
are deliberately conservative byte-based upper bounds. Provider success and
quality success are distinct fields. Replay the resulting artifact to apply the
readability gate and current pricing without another call. No automatic paid
repair loop, scheduler, or GitHub Actions workflow is added.

## Corpus and interpretation

`apps/legislation/tests/fixtures/reader_evals/` contains the complete stored
introduced H.R. 9300 text with manually annotated reader facts, plus clearly
labeled synthetic money/modality edge cases. The existing 25+ public-domain
extraction fixtures and 25+ provider cases remain in place. The old v2 extraction
gate explicitly disables v2.1 so a developer's `.env` cannot change its contract.

Add cases with source/version, full source text, required fact patterns, forbidden
patterns, and expected financial count. Patterns are conjunctions evaluated within
one displayed item, not across unrelated passages. They are regression proxies:
passing does **not** prove semantic entailment, complete coverage of arbitrary
legislation, neutrality, or readability. Reports always retain these human-review
requirements. Unannotated legacy provider cases report null fact recall, not 100%.
Review synonyms before interpreting a missing pattern as a factual error.

Mutation tests remove minimum qualifiers and whole facts, fabricate citations,
duplicate sentences, change source text, and force tiny readability limits to
prove the gates fail. Existing ledger tests verify all financial items remain
available and percentage caps are not presented as dollars.

## Pipeline changes

- Extractor `federal-rules-2.1.7` parses shared source-owned clause context once
  for payment extraction and synopsis generation. It distinguishes operative,
  prohibited, discussed, and unasserted clauses; retains ancestor introductions
  as evidence; and uses the existing abbreviation-aware sentence boundaries.
  Parent fee introductions no longer create duplicate child prices. Independent
  fees, surcharges, and exemptions retain their own amounts. Synopsis templates
  consume affirmative clause facts, including eligibility dates, rather than
  independently searching the full section text.
- `test_operative_matrix.py` tests deadlines versus prohibitions, negative
  eligibility conditions, abbreviations, whitespace, reversed payment order,
  prefixed amounts, exemptions, explicit/implicit child prices, parent reporting
  scopes, and positive/negative residence-date statements. These are deterministic
  regression guarantees, not proof of arbitrary legal entailment. API and UI
  schemas are unchanged. Existing immutable analyses require re-extraction.

- Extractor `federal-rules-2.1.6` rejects negative and reporting payment/synopsis
  contexts across wrapped lines, while retaining explicit payment exceptions.
  It retains multiple payment categories and coordinated or enumerated fee
  prices, and recognizes `must not exceed` caps. Regression tests exercise the
  public contract output and exact source offsets. Existing stored contracts
  require re-extraction; deploying code does not rewrite historical analyses.

- Extractor `federal-rules-2.1.5` preserves appropriations alongside account
  availability rules, binds payment amounts to payment expressions (not income
  thresholds), retains percentage rates/caps and fiscal-year filters, and rejects
  prohibited or merely contemplated grant programs in the synopsis. Regression
  tests include mixed fee/appropriation sentences and governing year ranges.

- Extractor `federal-rules-2.1.2` classifies application fees, surcharges,
  fines, fee exemptions, and account-availability rules separately from spending.
  Payment clauses retain their source wording and conditions. Unspecified fees
  are not treated as zero or as appropriations. New API action filters and reader
  labels expose these categories; deploy the frontend validators with the backend
  before regenerating contracts. No migration is required.
- The full H.R. 1589 introduced text is now an annotated evaluation case.
  Its eight financial fact checks pass, including both fee caps, the counsel
  surcharge, fine, grant purpose, exemption, processing fee, and account rule.
  The full-reader gate still reports nonfinancial fragments and duplicates;
  financial coverage passing is not a claim that the entire reader output passes.
  `test_reader_fees.py` separately gates the financial output and API shapes.

- NLP extractor `federal-rules-2.1.1`: recognizes XML's unquoted definitions and
  purpose syntax; connects enumerated activities to parent requirements; retains
  optional examples; fixes letter/roman hierarchy and list-versus-heading parsing;
  preserves funding minimums, percentage units, bases, and complete purposes.
- Disjunctive and explicitly numbered choices remain grouped obligations rather
  than separate compulsory duties. Nested percentage reservations recognize both
  minimums and caps. The money ledger displays the qualified extraction text, not
  just the bare amount.
- Definitions exceeding the schema's field or display limits are omitted with a
  `reader_definition_too_long` warning and a reader-facing coverage notice. The
  full wording remains in the bill text; unrelated provisions and money items
  remain available instead of forcing the entire bill into legacy extraction.
- Reservation extraction requires a monetary object or a bare list introduction;
  reserving rights, authority, or rooms does not create a budget entry merely
  because the same clause mentions a dollar amount.
- AI prompt/schema 1.2: checks nested uses of funds, resolves local definitions,
  preserves financial conditions, and requests short exact supporting quotations.
  Every quote must match uniquely inside its saved source. The server calculates
  offsets; the model cannot invent offsets. Existing 1.1 results remain readable;
  new 1.2 requests cannot downgrade validation by returning 1.1.
- Citation expansion displays the selected quotes instead of entire chunks; the
  full immutable source snapshot remains stored. Multiple quotes from one source
  render independently in the client.

Existing contracts and AI results are immutable. Re-extract affected documents to
create updated NLP contracts. New AI behavior applies on a newly confirmed
enhancement; do not silently regenerate paid results or reinterpret old output.

Oversized requirements, including cumulative nested-list context and rendered
sentence overhead, are omitted individually instead of invalidating the whole
contract. Their source text remains unchanged. The reader displays the coverage
note outside collapsed details, including omitted-definition and requirement
warnings, with a full-text link when the document text URL is available.

## Rule-based synopsis

Extractor `federal-rules-2.1.3` adds a cited synopsis when no explicit purpose
clause is available. Initial supported patterns cover conditional residence,
protected-status residence pathways, nonprofit applicant-assistance grants,
and recognized financial categories. Residence dates come from the source;
amounts are not combined into a misleading bill-wide total.

This is deliberately limited template coverage, not a general semantic summary
of every bill or every eligibility condition. Official summaries retain priority.
The reader provides expandable source evidence for generated synopses.
Unsupported patterns retain the existing fallback. Existing contracts require
re-extraction; no paid AI requests are made.

`test_reader_synopsis.py` checks the full H.R.1589 fixture, changed source dates,
negative/reporting language, quoted amendments, exact evidence offsets, and
preservation of explicit purpose clauses. These checks do not imply that all
detailed line items pass the broader reader-quality gate.

## Diagnosing failed app requests

### Glossary quality

Extractor `federal-rules-2.1.4` separates source-matched plain-English glossary
explanations from the retained legal definition and evidence. Reviewed rules
match the entire definition, including conditions, not merely the term. Unknown
wording stays labelled legal text; incorporated external definitions are marked
unresolved rather than guessed. This does not implement external-law retrieval.
Both the glossary and per-provision linked terms display the same explanation.

The H.R.9300 corpus adds NLP-only `glossary_facts`, matched within a named term.
They check graduation versus transfer, evidence-tier qualifications, and explicit
disclosure of unclear source wording. Mutation tests remove qualifiers and move
an explanation to the wrong term. Citation-only explanations fail the quality
gate. Metrics separately count unresolved references, literal definitions, and
ambiguous definitions; disclosure is not counted as successful resolution.
These regression checks do not establish legal entailment for arbitrary bills.

After migration `0014`, attempts retain `failure_detail` alongside
`failure_category`. The owner-scoped API returns a stable code, a static
plain-English message, and an allowlisted field path (for example,
`/overview/0/source_quotes/0/quote`). The bill page displays the reason.
Reasons distinguish missing/ambiguous quotes, source-reference mismatches,
schema constraints, invalid JSON, incomplete provider responses, and output-token
limits. No rejected text, raw exception messages, credentials, or provider response
bodies are retained in this field. Token usage continues to be retained separately.
Older failures have no detailed reason; migration does not invent one. Capturing
diagnostics does not automatically retry a request or make another paid call.
