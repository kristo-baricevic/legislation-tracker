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

- NLP extractor `federal-rules-2.1.1`: recognizes XML's unquoted definitions and
  purpose syntax; connects enumerated activities to parent requirements; retains
  optional examples; fixes letter/roman hierarchy and list-versus-heading parsing;
  preserves funding minimums, percentage units, bases, and complete purposes.
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

## Diagnosing failed app requests

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
