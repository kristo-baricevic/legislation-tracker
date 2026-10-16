# User-Owned AI Bill Enhancements

## Current status

### Citation resolution

Before final validation, the worker resolves citation locations against only the
immutable source snapshot sent to the model. Whitespace and hyphenated line wraps
are tolerated without changing source text or offsets. A uniquely located quote
can have its source reference corrected; overlapping chunks with the same absolute
span count as one location. Distinct occurrences remain ambiguous.

Ambiguous citations may trigger **one** targeted repair request per attempt. It
contains only the affected claims and a shared table of server-built, uniquely
located excerpts (each at most 800 characters). Each excerpt contains the unchanged
original quote. The model returns only a citation ID and an allowed candidate ID;
it cannot write replacement quotations, change actors or amounts, or change claims.
The same model and privacy controls apply. Missing evidence, invalid
patches, or ambiguity after repair still fail validation. There are no automatic
repair retries. A valid citation location does not establish semantic support.

Candidate tables are deduplicated across claims. If an occurrence cannot be
represented uniquely within the excerpt bound, the resolver leaves the citation
unresolved rather than silently hiding that alternative. Policy version 2 is
included in request fingerprints so an in-flight old request is not reinterpreted.

The confirmation warning discloses the potential second paid call. Repair input is
bounded by the initial conservative input estimate and application caps; output
uses the original output cap. The repair policy is in the request fingerprint, so
older confirmations cannot silently authorize the new behavior. Credentials,
feature availability, source identity and worker lease are rechecked before repair.

`BillEnhancementAttempt.citation_resolution_json` records original/corrected
citations, source offsets, unresolved IDs, response IDs and per-call usage. Initial
usage and repair intent are saved before the second call. Successful known usage is
summed; missing usage or interrupted repair leaves aggregate usage unknown, with
the known initial usage retained in the audit. Apply migration `0015` before
deploying the updated worker/API. Historical results are not rewritten.

Both whole-bill offline replay and live evaluation use the same resolver. Live
`evaluate_bill_enhancements` requires `--repair-citations` to authorize a second
call; its displayed maximum call/output budget includes that call. Offline replay
never calls a provider and preserves the original output alongside corrections.

The optional bill-enhancement layer is implemented for federal bills and is
disabled by default. It is a private, user-funded overlay on the deterministic
legal-NLP contract; it does not replace or modify `BillContract`,
`EvidenceSpan`, ingestion output, or `ChangeLog`.

OpenAI is the only production provider adapter in the initial release. The
adapter boundary is provider-neutral so another provider can be added without
changing credential ownership, enhancement persistence, or the public API.

## User flow

1. A signed-in user opens **Settings**, saves their own provider API key, and
   explicitly validates it. The key is entered through a password field and is
   never returned by the API.
2. On an eligible federal bill, **Enhance with AI** shows the requested model,
   reasoning effort, conservative input bound, output ceiling, credential
   revision, truncation notice, and provider-billing warning.
3. Confirming creates one durable `BillEnhancementAttempt`. Loading, estimating,
   polling, or viewing history never contacts the provider.
4. The bill panel polls pending/running work through transient failures and
   stops on a terminal result, authentication loss, navigation, or unmount.
5. Successful output is shown with server-expanded **Cited source** text,
   provider-reported usage, requested/resolved model, a disclaimer, attempt
   history, and paginated enhancement history. Older and stale results remain
   readable.

State and other non-federal bills show the current federal-only limitation
without querying private credential or enhancement endpoints. When the global
feature flag is disabled, the enhancement UI is omitted.

## API surface

| Endpoint | Authentication | Purpose |
| --- | --- | --- |
| `GET /api/capabilities/` | Public | Returns only the non-secret deployment capability flag. |
| `GET/PUT/DELETE /api/settings/llm/` | JWT | Reads redacted settings, saves or changes a key, enables/disables it, or deletes it. |
| `POST /api/settings/llm/validate/` | JWT | Makes one explicit validation call with SDK retries disabled. |
| `GET /api/bills/{bill_id}/enhancements/estimate/` | JWT | Builds the current request and returns eligibility, bounds, fingerprints, and confirmation identity. |
| `GET/POST /api/bills/{bill_id}/enhancements/` | JWT | Returns newest-first paginated history or creates one confirmed logical request/attempt. |
| `GET /api/bills/{bill_id}/enhancements/latest/` | JWT | Returns the latest complete owned enhancement or `404`. |
| `GET /api/bills/{bill_id}/enhancements/{id}/` | JWT | Returns complete detail for one owned historical enhancement. |
| `POST /api/bills/{bill_id}/enhancements/{id}/retry/` | JWT | Creates one explicitly confirmed retry attempt when the API says retry is allowed. |

All private responses use `Cache-Control: private, no-store`. Object lookup is
scoped to `request.user`; credential material, source snapshots, provider
response IDs, and raw provider errors are not serialized.

## Request and response safety

The backend builds one canonical UTF-8 JSON request from bill metadata and the
stored active document. Source-packet version 1.2 selects complete sections;
all citation chunks within a selected section travel together. It no longer
substitutes a balanced selection of extracted fragments when the full bill is
too large. Oversized sections are explicitly omitted, not cut halfway through
their conditions. If no complete section fits, preflight returns `request_too_large`.
The complete request, including instructions, coverage metadata, and output
schema, must fit both configured limits.

Only model-input whitespace is compacted, using the citation matcher's layout
rules. Saved source snapshots retain verbatim text and original offsets. The
coverage manifest lists selected and omitted section ranges and lexical section
references absent from the packet. Those reference diagnostics do not resolve
external law or prove that a similarly numbered section is the correct target.
Prompt version 1.3 requires complete conditions and explicit qualification when
a referenced rule is missing. This instruction is not a semantic correctness
guarantee. A partial packet is not a complete bill analysis. Bills exceeding
the configured limits need a larger validated budget or separately budgeted
multi-pass processing; multi-pass processing is not implemented.

The default conservative input budget is 100,000, with a separate 120,000-byte
request cap and an 8,000-token output ceiling (including reasoning). This fits
the complete pinned H.R. 1589 input, approximately 81 KB, without multi-pass
processing. These are application spending/size limits, not model context-window
claims. Full source inclusion does not prove complete or accurate generated
coverage; that still requires an executed evaluation. Increasing the output
ceiling permits higher output cost but does not preallocate or bill that many
tokens. Environment overrides remain supported.

`estimated_input_tokens` is deliberately the serialized UTF-8 byte count. This
one-byte-per-token local bound prevents the request-content undercount caused by
punctuation-heavy or non-BMP input. It is intentionally more conservative than
a model-specific tokenizer estimate.

OpenAI Structured Outputs accepts only a subset of JSON Schema. The provider
receives `PROVIDER_OUTPUT_SCHEMA`, which removes unsupported keywords such as
`uniqueItems`; the server then validates the response against the stronger
local `OUTPUT_SCHEMA` and exact citation references before persisting success.
The OpenAI SDK floor is `2.54` so the installed client supports the request
shape used by the adapter.

Provider calls use `store=False`, `max_retries=0`, disabled truncation, no tools,
no conversation state, an explicit timeout, and explicit prompt-cache behavior.
Each accepted attempt authorizes one generation call and, only when needed,
at most one bounded citation-only repair call. Neither call is automatically retried.

## Durable execution

`BillEnhancementAttempt` is the source of truth; Celery messages contain only an
attempt ID and dispatch token. The API writes pending work before its best-effort
broker wake, and Celery Beat rediscoveries prevent broker outages from losing
accepted work.

A dispatch token is retained across lease expiry because publication may have
succeeded even when delivery is delayed. Republishing with the same token lets
either message win the single atomic pending-to-running claim. A known publish
failure clears the token before a later dispatch. Duplicate or stale messages
cannot make a second provider call after an attempt is claimed.

A running lease that expires becomes `outcome_unknown`; it is never silently
returned to pending. Another possible provider charge always requires a new
user confirmation with an explicit duplicate-usage warning.

## Configuration

The same settings must be supplied to the Django API, Celery worker, and Celery
Beat processes:

```bash
LLM_ENHANCEMENTS_ENABLED=False
LLM_CREDENTIAL_ENCRYPTION_KEYS=primary:<fernet-key>
LLM_CREDENTIAL_ACTIVE_KEY_ID=primary
LLM_ENHANCEMENT_PROVIDER=openai
LLM_ENHANCEMENT_MODEL=gpt-6-luna
LLM_ENHANCEMENT_REASONING_EFFORT=none
LLM_ENHANCEMENT_MAX_REQUEST_BYTES=120000
LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS=100000
LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS=8000
LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS=90
LLM_ENHANCEMENT_RUN_LEASE_SECONDS=180
LLM_ENHANCEMENT_CREATE_RATE=10/hour
LLM_ENHANCEMENT_VALIDATION_RATE=5/hour
```

Production additionally requires enforced TLS, secure cookies/HSTS, and the
explicit TLS and secret-log-redaction confirmations documented in
[PRODUCTION_OPERATIONS.md](PRODUCTION_OPERATIONS.md). `/health/` reports the
feature as `disabled`, `ok`, or `error` without decrypting a key or contacting
OpenAI.

## Evaluation and automated coverage

The versioned evaluation corpus contains 25 human-labeled federal cases,
including multi-source packets, truncation, conflicting provisions,
cross-references, sparse evidence, and prompt-injection-shaped source text.
Evaluation artifacts include the review rubric and per-case labels. Running the
provider evaluation command still requires a dedicated non-user key, explicit
`--execute`, case/token limits, and an output path for source/output material.

The Playwright enhancement test does not intercept enhancement routes. It uses
live Django APIs, encrypted credential persistence, a real filesystem Celery
broker and worker, delayed asynchronous completion, browser polling, and
persisted history/detail reads. Its deterministic provider exists only behind
`config.settings.e2e`; production configuration explicitly rejects that test
provider gate.

Current verification for the implementation branch:

- Backend: 314 passed, 4 skipped.
- Frontend: 25 Vitest tests and 18 Node/API tests passed.
- Browser: all 3 Chromium E2E flows passed.
- TypeScript, ESLint, changed-file Ruff/Black, Django checks, migration
  consistency, and the production webpack build passed.

No automated suite sends a live OpenAI request or uses a real provider key.
# Source-first rollout

The optional `2.0-source-first` pipeline, per-call audit records, aggregate spending
confirmation, partial retries and versioned reader are documented in
[SOURCE_FIRST_ANALYSIS.md](SOURCE_FIRST_ANALYSIS.md). Its flag defaults off pending
independent benchmark acceptance. Legacy generation and stored results remain supported.
