# User-Owned AI Bill Enhancements

## Current status

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

The backend builds one canonical UTF-8 JSON request from bill metadata and
exact stored contract evidence or active-document chunks. The complete request,
including instructions and output schema, must fit both configured limits.

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
Each accepted attempt authorizes at most one provider call.

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
LLM_ENHANCEMENT_MODEL=gpt-5.6-luna
LLM_ENHANCEMENT_REASONING_EFFORT=none
LLM_ENHANCEMENT_MAX_REQUEST_BYTES=120000
LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS=60000
LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS=4000
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
