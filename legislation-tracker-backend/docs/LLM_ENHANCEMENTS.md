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

The provider-neutral harness supports OpenAI, Anthropic, Gemini and
OpenAI-compatible endpoints including OpenRouter.

### Free-model reader execution

For `openrouter/free`, the first returned (or already validated cached) free
model is persisted in `BillEnhancementAttempt.pinned_model`. New calls in that
attempt, including later worker deliveries and split retries, use that exact
model ID. No model is hardcoded globally and a mismatched response is rejected.
Previously validated cached results remain reusable even when the old run used
different free models. An unresolved router response never authorizes a paid model.

The existing size-based planner budgets prose and citations. A known truncated
response is subdivided by target/output size (or passage bytes for full-source
review), preserving complete source context. Only its children are requested;
validated siblings and rejected parents are durably reused across deliveries.
Subdivision stays within the confirmed call reserve and stops at indivisible units.

OpenRouter uses explicit `low` reasoning when the legacy `none` configuration
is selected. Explicit low/medium/high settings are preserved. The effective
effort appears in the estimate, request fingerprint, and attempt diagnostics;
reasoning is not disabled. Prose regex checks run locally rather than in the
provider's constrained decoder; citation ID and shape constraints remain.
OpenAI-compatible production calls use an async HTTP
client with a total elapsed-time deadline, in addition to transport timeouts.
Deadline expiry cancels the HTTP operation and records an unknown outcome; it
does not automatically resend a possibly processed request. Cancellation cannot
guarantee that a remote provider has stopped computing.

## Durable reader batching (2026-11-22)

Apply migrations **0027–0028** before deploying this API/worker revision.
They add per-attempt work nodes and the `paused` status. An already completed
public analysis is not rewritten by these migrations.

- Work nodes persist pending requests, split ancestry and validated outputs.
  Worker deliveries rebuild the result from those nodes; cached reads and local
  reconstruction do not consume the confirmed provider-call allowance.
- Full-source reviews now estimate output from owned passage bytes, citations,
  coverage decisions and financial findings. Default reasoning remains enabled
  where the provider enables it. The planner reserves half the output allowance
  for reasoning; this is an estimate, not a prediction of model behavior.
- Output-limit recovery divides ownership by text size and retains the source
  context and citation IDs. It deliberately does **not** drop neighboring legal
  conditions to shrink input. An indivisible unit can use one larger output
  allowance within the model cap and the already-confirmed aggregate budget.
  At that cap it stops; retries cannot loop indefinitely.
- Valid independent components of a rejected review are saved. Findings sharing
  owned citations form one component; an invalid component is retried together.
  No unvalidated response prose is retained as successful work.
- Actual dispatches, input/output token ceilings and per-delivery limits are
  checked separately. Missing usage retains its conservative reservation. Budget
  exhaustion saves progress as `paused`; **Continue** opens the existing estimate
  modal and requires confirmation before any further request. Key rotation does
  not change the pinned model in a continued plan.
- Cache identity includes effective model and execution semantics. Validated
  cache entries are revalidated. Unknown provider outcomes remain reserved and
  are never blindly resent. Reuse is guaranteed for the same work identity, not
  across arbitrary prompt, model or source changes.
- Diagnostics retain reasoning/visible usage when the provider reports it,
  requested/resolved model, reservations, ownership, and failure codes. Final
  counters distinguish dispatched calls from validated work units.

`LLM_READER_MODEL_CAPACITIES` is an optional JSON object keyed by
`provider/model`, with `context_tokens`, `output_tokens`, and `visible_fraction`.
Use published limits for the selected model. Without an override the planner
uses application caps and conservative UTF-8-byte input estimates; it does not
claim to know an unspecified free-router model's capabilities. Input plus output
plus transport headroom must fit. The effective pinned model is checked again
before dispatch. No model-catalog or LLM calls occur during planning.

Read-only audit:

```bash
rtk proxy python manage.py benchmark_reader_planner 18343 --provider openrouter --model openrouter/free
rtk proxy python manage.py benchmark_reader_planner 460 --bills --provider openrouter --model openrouter/free
```

Local verification: bill 460/document 537 planned 25 calls in 1.487 seconds,
with 81/81 owned passages. Document 18343 planned 495 calls in 53.109 seconds,
with 4,852/4,852 owned passages and 1,134/1,134 XML sections. Neither plan had
missing, duplicate or oversized assignments. This establishes scheduling
coverage, **not** semantic accuracy or successful live generation. The latter
document still has 53 chunks whose complete surrounding context is unavailable;
that limitation is retained, not silently treated as resolved.

The follow-up corrected both comparison gaps. Large HTML documents now use
the complete reader planner even without an existing NLP contract. XML
contents-only section wrappers are excluded from the operative inventory;
mixed contents/operative sections remain included, and source text is unchanged.
Document 11639's text matched exactly: its former error was an empty TOC wrapper,
not a mismatched source version.

Read-only rerun (2026-11-23): document 11639 planned 462 calls in 50.371 seconds,
with 4,427/4,427 passages and 1,093 XML sections; document 18340 planned 613 calls
in 25.958 seconds, with 4,836/4,836 passages. Neither had missing, duplicate or
oversized assignments. They retain 34 and 87 incomplete-context chunks,
respectively. These counts establish scheduling coverage, not interpretation
accuracy or guaranteed API success. No AI calls were made.

The same audit found both non-AI document jobs had exhausted five attempts
under the shared 60-second timeout. Extraction now merges structural markers
incrementally, reuses the parent index and operative parse, indexes payment
children and clause overlaps, and normalizes glossary evidence once per line.
Read-only full extraction completed without legacy fallback for 18340 (34.61s)
and 11639 (65.62s). Document-contract deliveries now have a 180-second soft /
210-second hard CPU budget, below the ten-minute lease; network stages retain
their 60/75-second limits. These are runtime checks, not a claim that every
legal provision has been correctly interpreted.

Live local durable replay completed on the first replay attempt for both:
18340 in 65.78s (contract 32139), and 11639 in 79.31s (contract 32140), including
persistence. Document 18340 is not the marked active version (18344 is), so its
saved version analysis did not replace the current bill analysis. Document
11639 initially retained an incomplete-amendment coverage warning. The follow-up
fix recognizes direct “is amended as follows:” replacement text and associates
child conditions by source position rather than repeated section labels. It
keeps qualifying lists together, preserving permission versus obligation and
the source conjunction. Regression tests cover deletion/background text and
repeated labels, with exact evidence-offset checks.

The local 2.1.25 replay saved contract 32142 in 82.24 seconds. Verification of
the saved result found one marine-inspector pay permission containing both
eligibility conditions, including the Commandant determination. The
incomplete-amendment warning cleared and the bill is marked processed. Separate
reader-quality warnings remain (`reader_required_slot_missing` and
`reader_uncertain_clause`); this check establishes recovery of this amendment,
not perfect interpretation of every provision. No AI calls were made.

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

## Provider credentials and harness evaluation

Before the reader execution version 7 → 9 cutover, pause new enhancement create and retry requests at the ingress, keeping the previous workers and dispatcher running. Wait for all pending and running version 7 reader attempts to finish, then stop the previous workers, run migrations, start the updated services and reopen submissions. Migration 0032 blocks cutover while an incompatible reader attempt is still active. If it blocks, resume the previous workers and retry the migration after they drain. Keep historical ambiguous call reservations intact.

Apply the forward account and legislation migrations before starting the updated API and worker. Second-provider writes are gated by `LLM_MULTI_PROVIDER_WRITES_ENABLED` (default false). Set it to true after routing all settings and enhancement traffic to upgraded services. Existing encrypted keys, revisions and attempt references are preserved. Use the expanded schema for application rollback once an account has two providers.

Settings retain one key and model per provider. A user's active selection authorizes new estimates. Confirmation binds the exact key identity and revision, selected model, adapter and capability fingerprint. An existing shared result can be returned without generating again.

Refresh the OpenRouter catalog with `rtk proxy .venv/bin/python manage.py refresh_enhancement_models` at initial setup. Celery Beat refreshes it every six hours; entries expire after 24 hours. Choose a listed concrete free model for new requests when an older selection is `openrouter/free`. Pricing with missing metadata appears as unknown. The original direct adapters remain the defaults. `LLM_OPENROUTER_ADAPTER=langchain` selects the experimental OpenRouter transport for new confirmations; set it to `existing` for rollback. Preserve both implementations while prior attempts drain. There is no automatic free-to-paid fallback.

Free OpenRouter models appear in Settings only while the cached catalog reports zero pricing, structured outputs, reasoning, a maximum-token control and positive context and completion limits. The dynamic `openrouter/free` alias cannot be selected for new work. Set `LLM_OPENROUTER_EXCLUDED_MODELS` to a comma-separated list of exact model IDs to omit additional models, including a configured default. Apply that configuration to the API and workers. Account keys and saved results survive a model exclusion. A timeout or rate limit alone does not establish model incompatibility.

Set `LLM_READER_OWNED_TOKEN_TARGET` only for a comparison arm. The 1000, 2000 and 4000 targets use conservative UTF-8-byte estimates when no matching tokenizer is available. Total envelopes still undergo capacity checks. Confirmation stores the chosen target on the attempt. In-flight reader work retains that target across worker deliveries when the flag changes. The planner records missing context and rejects work exceeding the legal-context budget before generation. Leave the default at zero outside an evaluation.

Private transport diagnostics are off by default. A positive `LLM_DIAGNOSTIC_RETENTION_DAYS` enables visible response and sanitized request capture for reader steps. Access requires the owning account on the bill's diagnostic endpoint. Expired artifacts become inaccessible immediately and the recovery task prunes them in batches. Deleting the account cascades to its diagnostic artifacts.

The comparison command defaults to offline inspection. A live invocation requires a recorded attempt/work unit, owner, concrete free model, an explicit token ceiling, two calls, a zero-dollar ceiling and a private evidence directory. The command records a reservation before each dispatch; preserve the directory across retries. A fresh directory represents a new experiment and requires separate authorization. Investigate unknown outcomes before authorizing any additional call.
