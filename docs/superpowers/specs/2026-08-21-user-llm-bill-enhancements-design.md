# User-Owned LLM Bill Enhancements Design

**Date:** 2026-08-21
**Status:** Revised after adversarial review; production implementation has not started
**Scope:** Toggleable BYOK LLM settings, provider abstraction, bounded bill enhancements, durable execution, private API, bill-detail UI, and operational controls

## Summary

Add an optional, user-triggered LLM layer over the existing deterministic legal-NLP output. A signed-in user can save their own provider API key and explicitly request an enhanced explanation for one bill. The backend creates one durable execution attempt, makes at most one bounded provider request for that attempt, validates the structured response and its citation references, and stores the result as a private user-owned overlay.

The deterministic `BillContract`, `EvidenceSpan`, bill metadata, and `ChangeLog` remain canonical and shared. An LLM enhancement never changes ingestion output, never runs automatically, and never replaces canonical data. The deployment can disable the feature globally, and each user can disable or delete their credential independently.

OpenAI is the first provider behind a provider-agnostic adapter. The initial implementation uses the Responses API with Structured Outputs. The configured requested model defaults to the cost-sensitive `gpt-5.6-luna`; deployments may override it without a schema migration. The application records both the requested model and the provider-returned resolved model because aliases may move over time.

## Safety Invariants

These are implementation requirements, not aspirations:

1. One confirmed create or retry request creates exactly one `BillEnhancementAttempt` and authorizes that attempt to make at most one outbound provider request.
2. The provider SDK, Celery, and stale-work recovery never automatically repeat a provider request. Another possible charge always requires another user confirmation.
3. A broker outage cannot strand accepted work. Pending attempts are durable database work discovered by a periodic dispatcher.
4. A worker crash or timeout after provider acceptance may be unknowable. Such an attempt becomes `outcome_unknown`; it is never silently replayed.
5. A queued attempt can use only the exact credential revision, provider, and requested model that the user confirmed.
6. The complete serialized provider request—not only source quotations—must fit byte and estimated-token limits before work is accepted.
7. The server validates citation integrity, not factual entailment. The product must not label model output or citations as verified.
8. Credentials and private enhancement responses are authenticated, owner-scoped, encrypted at rest, excluded from logs, and never cacheable by shared intermediaries.

## Goals

- Let a user opt into paid LLM enhancement with a provider key they control.
- Make every possible provider charge an explicit, confirmed action for one bill.
- Bound the complete provider request and show a conservative input estimate before confirmation.
- Attach every displayed substantive claim to exact source references selected by the server.
- Keep credentials encrypted at rest, redacted from responses, and absent from task payloads and logs.
- Preserve private history by source and execution configuration without altering shared bill records.
- Deduplicate concurrent or repeated requests so accidental clicks do not create duplicate attempts.
- Make failures, refusals, uncertain outcomes, and stale results visible without corrupting canonical data.
- Keep provider-specific code isolated so another provider can be added without changing API ownership or persistence boundaries.

## Non-goals

- Running an LLM during bill, document, representative, vote, topic, or contract ingestion.
- Using an application-owned provider key on behalf of all users.
- Replacing or mutating deterministic legal-NLP contracts, evidence, topics, similarity, or change history.
- Automatically enhancing tracked bills, new bills, or a backlog.
- Automatically retrying any provider request.
- Multi-pass whole-document analysis, embeddings, retrieval infrastructure, agents, tools, or provider-side actions.
- Proving that a generated claim is entailed by its cited text.
- Sharing one user's enhancement or credential with another user.
- Claiming that an enhancement is legal advice, exhaustive, authoritative, or complete.
- Adding LLM support to the browser extension in the first release.

## Product Boundaries

Three gates must all be open before an attempt can be created:

1. `LLM_ENHANCEMENTS_ENABLED` is enabled by the deployment.
2. The signed-in user has an enabled credential validated for its current revision, provider, and requested model.
3. The user explicitly confirms the current request estimate, source fingerprint, credential revision, and execution configuration.

There are no scheduled or ingestion-triggered provider calls. Loading a bill, loading settings, estimating a request, polling status, and viewing history never contact the provider. The periodic dispatcher only delivers already confirmed database work; it does not create attempts or authorize new calls.

The UI labels output **AI enhancement** and displays the requested model, resolved model when available, creation time, source version, attempt usage, truncation state, and a fixed legal-information disclaimer. It must not visually replace the deterministic contract section.

## Architecture

The feature is split across existing domains:

- `apps.accounts` owns encrypted user credentials and settings endpoints.
- `apps.legislation` owns request construction, enhancement and attempt records, provider adapters, durable dispatch, execution, and enhancement endpoints.
- The Next.js client owns the authenticated settings page and bill enhancement panel.
- Celery executes durable attempts but is not the source of truth for accepted work.

Suggested backend modules:

| File | Responsibility |
| --- | --- |
| `apps/accounts/llm_credentials.py` | Versioned authenticated encryption, decryption, envelope validation, redaction, and key rotation. |
| `apps/accounts/llm_serializers.py` | Credential input and redacted output contracts. |
| `apps/accounts/llm_views.py` | Authenticated settings CRUD and explicit validation. |
| `apps/legislation/enhancements/types.py` | Provider-neutral request, response, usage, and error types. |
| `apps/legislation/enhancements/providers/base.py` | Provider adapter protocol and error taxonomy. |
| `apps/legislation/enhancements/providers/openai.py` | OpenAI Responses API implementation with SDK retries disabled. |
| `apps/legislation/enhancements/provider_registry.py` | Strict configured-provider lookup. |
| `apps/legislation/enhancements/source_packet.py` | Deterministic bounded source selection, references, estimates, and fingerprints. |
| `apps/legislation/enhancements/schema.py` | JSON Schema and citation-integrity validation. |
| `apps/legislation/enhancements/service.py` | Transactional preflight, deduplication, attempt creation, and result promotion. |
| `apps/legislation/enhancements/dispatch.py` | Database work discovery, dispatch leases, and expired-run recovery. |
| `apps/legislation/enhancements/prompts.py` | Versioned provider-neutral instructions and canonical request assembly. |
| `apps/legislation/tasks.py` | Top-level Celery task entry points imported by `app.autodiscover_tasks()`. |

Internal enhancement code may live in the nested package, but public Celery task definitions must live in `apps/legislation/tasks.py` or be explicitly imported there. Relying on autodiscovery to import `apps.legislation.enhancements.tasks` is not allowed.

The provider boundary is intentionally small:

```python
class EnhancementProvider(Protocol):
    provider_name: str

    def validate_credential(
        self,
        *,
        api_key: str,
        requested_model: str,
        timeout_seconds: int,
    ) -> CredentialCheck:
        ...

    def enhance_bill(
        self,
        *,
        api_key: str,
        request: ProviderEnhancementRequest,
        timeout_seconds: int,
    ) -> ProviderEnhancementResult:
        ...
```

Provider exceptions are converted at the adapter boundary into stable internal categories. Provider SDK objects, raw HTTP responses, and raw provider error text do not cross into views, serializers, tasks, or customer-visible persistence.

## Data Model

### `LLMCredential`

Add a one-to-one credential in `apps.accounts`:

| Field | Purpose |
| --- | --- |
| `user` | One-to-one owner; cascade on account deletion. |
| `provider` | Provider slug; initially `openai`. |
| `encrypted_envelope` | Authenticated ciphertext containing contextual key material; never serialized. |
| `key_suffix` | Last four characters for recognition only. |
| `encryption_key_id` | Deployment encryption key used for the row. |
| `revision` | Monotonically increasing integer changed on every key or provider replacement. |
| `enabled` | User-level toggle. |
| `validation_status` | `unverified`, `valid`, or `invalid`. |
| `validated_revision` | Credential revision checked by the last non-stale validation. |
| `validated_provider` | Provider checked by the last non-stale validation. |
| `validated_model` | Requested model checked by the last non-stale validation. |
| `validated_at` | Time of the last non-stale validation outcome. |
| `created_at`, `updated_at` | Audit timestamps. |

Saving or replacing a key increments `revision` and atomically resets all validation fields to `unverified`/null. Changing provider also increments the revision. Changing only `enabled` does not re-encrypt the key, but disabled credentials cannot create or start attempts. A deployment provider or requested-model change makes the credential effectively unverified until explicit validation succeeds for the new configured values.

The API never returns plaintext, ciphertext, key length, key prefix, or provider error detail. It returns only redacted state including `provider`, `key_suffix`, `revision`, `enabled`, validation state, and timestamps.

Deleting the credential immediately prevents new work and any not-yet-started attempt from making a call. A provider request already in progress cannot be recalled; its sanitized result and usage may still be recorded. The UI explains this race before deletion.

### `BillEnhancement`

`BillEnhancement` is the immutable logical result identity:

| Field | Purpose |
| --- | --- |
| `user` | Owner; cascade on account deletion. |
| `bill` | Enhanced bill; cascade with the bill. |
| `provider` | Immutable requested provider. |
| `requested_model` | Immutable configured model sent to the provider. |
| `reasoning_effort` | Immutable configured reasoning effort. |
| `prompt_version` | Immutable application prompt version. |
| `output_schema_version` | Stored response-contract version. |
| `source_packet_version` | Source selection algorithm version. |
| `source_fingerprint` | SHA-256 of canonical selected sources and source identities. |
| `request_fingerprint` | SHA-256 of the full canonical provider-neutral request envelope. |
| `source_manifest_json` | Source IDs/hashes, selection counts, and truncation flags. |
| `source_snapshot_json` | Exact bounded server-owned sources used for citations. |
| `status` | Derived latest state: `pending`, `running`, `succeeded`, `failed`, `refused`, or `outcome_unknown`. |
| `result_json` | Validated provider-neutral output; immutable after success. |
| `successful_attempt` | Nullable one-to-one pointer to the attempt promoted as the result. |
| `input_tokens`, `output_tokens`, `total_tokens` | Cumulative provider-reported usage across all attempts when known. |
| `created_at`, `updated_at`, `completed_at` | Lifecycle timestamps. |

The database enforces one logical enhancement for the exact canonical request:

```text
(user, bill, request_fingerprint)
```

The fingerprint includes provider, requested model, reasoning effort, prompt content/version, schema content/version, packet content/version, metadata, and output bound. The immutable columns remain separately stored for filtering, display, and defense-in-depth consistency checks.

Repeated requests after success return the existing result without an attempt or provider call. A pending or running match returns its current state. A failed, refused, or uncertain match is never reset in place; an explicit eligible retry creates a new attempt for its existing logical enhancement.

### `BillEnhancementAttempt`

Each explicit confirmation creates one durable, append-only attempt:

| Field | Purpose |
| --- | --- |
| `enhancement` | Parent logical enhancement. |
| `sequence` | Monotonic sequence unique within the enhancement. |
| `credential` | Nullable `SET_NULL` audit reference. |
| `credential_revision` | Exact revision authorized by confirmation. |
| `status` | `pending`, `running`, `succeeded`, `failed`, `refused`, or `outcome_unknown`. |
| `available_at` | Earliest time the dispatcher may publish this confirmed attempt. |
| `dispatch_token`, `dispatch_lease_expires_at` | Short lease preventing competing dispatchers from publishing normal duplicates. |
| `run_token`, `lease_expires_at` | Worker ownership and ambiguity boundary. |
| `estimated_input_tokens` | Conservative full-request estimate confirmed by the user. |
| `input_tokens`, `output_tokens`, `total_tokens` | Usage attributable to this outbound attempt when reported. |
| `provider_response_id` | Private support identifier when available. |
| `resolved_model` | Exact model identifier returned by the provider when available. |
| `failure_category` | Stable sanitized category, never raw provider text. |
| `started_at`, `completed_at`, `created_at`, `updated_at` | Lifecycle timestamps. |

Required indexes are `(status, available_at)`, `(status, dispatch_lease_expires_at)`, `(status, lease_expires_at)`, and `(enhancement, created_at)`. The database enforces unique `(enhancement, sequence)`. The creation service uses a row lock, and a supported-database partial constraint enforces at most one `pending` or `running` attempt for an enhancement. SQLite tests verify the service-level invariant.

Attempt results and usage are persisted before a successful result is atomically promoted to `BillEnhancement`. There can be only one promoted success. Enhancement cumulative usage is the sum of known attempt usage and is never inferred from an attempt whose outcome is unknown.

Enhancement records are not written to `ChangeLog`, because they are private user state rather than canonical bill changes.

## Credential Encryption and Rotation

Add `cryptography` and use Fernet authenticated encryption with a dedicated deployment key ring. Encryption is not derived from `DJANGO_SECRET_KEY` and does not use a database-stored key.

The plaintext before encryption is a versioned canonical envelope:

```json
{
  "version": 1,
  "user_id": "42",
  "provider": "openai",
  "revision": 3,
  "api_key": "..."
}
```

After decryption, the service verifies the envelope's user, provider, revision, and version against the database row before exposing the API key to the adapter. It also recomputes the suffix and rejects a mismatch. Copying ciphertext between users, providers, or revisions therefore fails closed even when the same Fernet key encrypted both rows.

Configuration:

- `LLM_ENHANCEMENTS_ENABLED=False`
- `LLM_CREDENTIAL_ENCRYPTION_KEYS=<key_id:fernet_key,...>`
- `LLM_CREDENTIAL_ACTIVE_KEY_ID=<key_id>`
- `LLM_ENHANCEMENT_PROVIDER=openai`
- `LLM_ENHANCEMENT_MODEL=gpt-5.6-luna`
- `LLM_ENHANCEMENT_REASONING_EFFORT=none`
- `LLM_ENHANCEMENT_MAX_REQUEST_BYTES=120000`
- `LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS=60000`
- `LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS=4000`
- `LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS=90`
- `LLM_ENHANCEMENT_RUN_LEASE_SECONDS=180`
- `LLM_ENHANCEMENT_CREATE_RATE=10/hour`
- `LLM_ENHANCEMENT_ALLOW_INSECURE_HTTP_IN_DEBUG=False`
- `LLM_ENHANCEMENT_PRODUCTION_TLS_CONFIRMED=False`
- `LLM_ENHANCEMENT_SECRET_LOG_REDACTION_CONFIRMED=False`

The request byte/token defaults are conservative operational starting points and must be validated against the selected model before rollout. The run lease must exceed the provider timeout by at least 30 seconds so response validation and persistence cannot race lease recovery.

When the feature is enabled, startup checks reject an empty key ring, missing active ID, duplicate IDs, malformed Fernet keys, an unregistered provider, unrecognized reasoning effort, non-positive bounds, or a run lease that is too short. When disabled, missing provider/encryption configuration is allowed. Settings reads and deletion remain available while disabled so users can inspect or remove stored material.

Decryption selects the row's `encryption_key_id`; failure is terminal and sanitized. A management command rotates rows in bounded transactions while preserving their logical revision and re-encrypting the same contextual envelope with the active key. Operators retain old keys until the command proves no rows reference them. Plaintext exists only in process memory for the shortest practical scope.

## Credential Settings API

All settings endpoints use normal JWT authentication, `IsAuthenticated`, and `request.user` scoping. Every response, including errors, sets `Cache-Control: private, no-store`.

### `GET /api/settings/llm/`

Returns global capability and redacted user state without contacting a provider:

```json
{
  "feature_available": true,
  "configured": true,
  "provider": "openai",
  "key_suffix": "1234",
  "revision": 3,
  "enabled": true,
  "validation_status": "valid",
  "validated_revision": 3,
  "validated_at": "2026-08-21T12:00:00Z",
  "requested_model": "gpt-5.6-luna"
}
```

### `PUT /api/settings/llm/`

Accepts `api_key` and/or `enabled`. `provider` is accepted only when registered and deployment-allowed. A new key is wrapped in a contextual envelope and atomically replaces the previous ciphertext while incrementing `revision` and invalidating prior validation. The key is never echoed. Enabling without a key returns `400`. Creating, replacing, or enabling while globally unavailable returns `503`; disabling remains available.

### `DELETE /api/settings/llm/`

Deletes the current user's credential and returns `204`. It does not delete enhancement history. This endpoint remains available while globally disabled and does not decrypt the key.

### `POST /api/settings/llm/validate/`

The UI explicitly warns that validation may incur one small provider charge. The endpoint snapshots credential ID, revision, provider, requested model, and ciphertext identity, then performs exactly one minimal provider request with SDK retries disabled and the configured timeout. After the response, it updates validation fields only with a compare-and-swap requiring the same credential ID, revision, provider, model, and ciphertext identity. A concurrent replacement causes the stale result to be discarded.

Valid authentication/model access marks the matching row `valid`. Invalid authentication or access marks it `invalid`. Provider timeout, rate limiting, or unavailability leaves it `unverified`. Validation itself is never retried automatically. No credential is validated on save, startup, login, or page load.

## Complete Request Construction and Cost Bound

Source construction is deterministic and provider-neutral. The provider cannot fetch a URL or access the database.

Preferred sources:

1. The bill's current `latest_contract` structured JSON and its `EvidenceSpan` rows.
2. When current contract evidence is unusable, section-aware chunks from the active `BillDocument.extracted_text` or `raw_text`.
3. When neither source exists, enhancement is unavailable and no attempt is created.

Each reference has an opaque server ID and exact stored text:

```json
{
  "source_ref": "src_0007",
  "kind": "contract_evidence",
  "field_path": "requirements[0].display_text",
  "section_label": "SEC. 3",
  "quoted_text": "Not later than 180 days ...",
  "start_char": 820,
  "end_char": 911
}
```

Contract evidence is ordered by source offset, de-duplicated by range and quote, and selected across categories in round-robin order. Document fallback chunks preserve exact offsets and legal section boundaries where practical. One reference may not exceed 4,000 characters.

Preflight builds the complete provider-neutral request envelope before estimating or accepting work. That envelope includes provider slug, versioned instructions, bill metadata, the allowed contract subset, source references, output schema and version, source-packet version, requested model, reasoning effort, and maximum output setting. It is serialized as canonical UTF-8 JSON with sorted keys and stable separators.

The builder calculates:

- exact serialized UTF-8 byte length; and
- a conservative local input estimate of `ceil(serialized_utf8_bytes / 2)` tokens.

An adapter may provide a more conservative model-specific estimator, but it may never lower this safety estimate. Source selection shrinks deterministically until the complete request is below both `LLM_ENHANCEMENT_MAX_REQUEST_BYTES` and `LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS`. If fixed instructions, metadata, and schema alone exceed either bound, preflight fails without creating work. The estimate endpoint and worker independently rebuild and verify the same canonical request and fingerprint.

The provider request sets:

- `max_output_tokens=LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS`;
- `reasoning.effort=LLM_ENHANCEMENT_REASONING_EFFORT` (default `none`);
- `truncation="disabled"`;
- `store=false`;
- `prompt_cache_options={"mode":"explicit","ttl":"30m"}` with no cache breakpoints, disabling implicit prompt caching; and
- no conversation, `previous_response_id`, tools, browsing, or actions.

`max_output_tokens` includes visible output and any reasoning tokens. The configured reasoning effort is therefore part of both estimate/configuration identity and staleness. Provider context-limit rejection is a sanitized terminal `request_too_large` failure; the adapter does not retry with automatic truncation.

`source_fingerprint` covers canonical selected sources and identities. `request_fingerprint` covers the complete serialized provider-neutral envelope. `source_manifest_json.truncated` records omitted material. When truncated, fixed server UI copy says **Based on selected source-backed provisions; other provisions may not be represented.**

The first release makes at most one provider request per attempt. It does not recursively summarize, map/reduce chunks, or retry by splitting input.

## Enhancement Output Contract

The provider receives fixed developer instructions, bill metadata, the bounded source packet as untrusted data, and a strict JSON Schema. Instructions require atomic observations and prohibit legal advice, completeness claims, absence claims, and instructions embedded in bill text.

Output schema version `1.1` uses cited atomic items:

```json
{
  "schema_version": "1.1",
  "overview": [
    {"text": "The bill directs the Secretary to issue a rule.", "source_refs": ["src_0001"]}
  ],
  "key_impacts": [
    {"text": "Covered entities would have a new reporting duty.", "source_refs": ["src_0002"]}
  ],
  "obligations": [
    {
      "actor": "Secretary of Health and Human Services",
      "modality": "required",
      "action": "Issue the specified rule.",
      "conditions": null,
      "source_refs": ["src_0003"]
    }
  ],
  "funding_and_timing": [
    {"kind": "timing", "text": "The rule is due within 180 days.", "source_refs": ["src_0004"]}
  ],
  "uncertain_language": [
    {
      "text": "The cited phrase uses 'as appropriate' without a listed factor.",
      "why_it_matters": "Implementation may depend on later agency interpretation.",
      "source_refs": ["src_0005"]
    }
  ]
}
```

JSON Schema limits string lengths, array sizes, enum values, and object properties, with `additionalProperties: false` throughout. Every substantive item requires at least one source reference. There is no provider-authored `coverage_notes` escape hatch. Coverage, truncation, and legal-information notices are fixed server copy.

After schema validation, citation-integrity validation requires each reference ID to exist in `source_snapshot_json` and verifies that stored text and its recorded hash still match. The server ignores any provider-authored quotation and expands **Cited source** content only from its stored snapshot. Unknown, missing, or corrupted references make the complete response `invalid_output`; partial display is forbidden.

Citation membership does not prove semantic support. The server cannot automatically establish that a claim is entailed by cited text, and product copy must never call citations “verified evidence.” Quality is controlled through the evaluation process below.

The OpenAI adapter uses Responses API Structured Outputs and handles structured success, refusal, incomplete output, missing output, and malformed output before application validation. It creates the client with `max_retries=0` and an explicit timeout; OpenAI SDK defaults must never control retry or timeout behavior.

References:

- <https://developers.openai.com/api/docs/guides/structured-outputs>
- <https://developers.openai.com/api/reference/cli/resources/responses/methods/create>
- <https://github.com/openai/openai-python#retries>

## Enhancement API

The existing public `BillViewSet` explicitly disables authentication and uses `AllowAny`; enhancement endpoints must not be actions on that viewset. They use separate views/routes with normal JWT authentication, `IsAuthenticated`, and owner-filtered lookups. Ownership failures return `404`. Every private response, including estimate, list, latest, detail, create/retry outcomes, and errors, sets `Cache-Control: private, no-store`.

### `GET /api/bills/{bill_id}/enhancements/estimate/`

Builds the complete current request without contacting the provider. It returns:

- provider, requested model, reasoning effort, prompt/schema/packet versions;
- source and request fingerprints and a source description;
- credential revision expected at confirmation;
- conservative estimated input tokens and serialized request bytes;
- maximum output tokens and the note that it includes reasoning;
- truncation state and fixed coverage copy;
- whether the user can enhance and a stable unavailable reason;
- matching enhancement/current-attempt state, if any.

The estimate is not a price promise. Provider pricing is not hard-coded.

### `GET /api/bills/{bill_id}/enhancements/`

Returns the current user's paginated logical enhancement history, newest first, with attempt summaries. It never returns another user's rows, credential material, source snapshots, provider response IDs, or raw errors.

### `POST /api/bills/{bill_id}/enhancements/`

Accepts the confirmed `source_fingerprint`, `request_fingerprint`, and `credential_revision`. The server rebuilds preflight under a transaction and returns `409` when source, request configuration, or credential revision changed. It atomically gets or creates the logical enhancement and, when needed, creates exactly one pending attempt.

Responses:

- `202` when one new attempt was durably accepted;
- `200` for an existing matching pending/running attempt or successful result, without a new attempt;
- `409` for changed preflight, invalid credential state, an existing terminal state that requires the retry flow, or unavailable source;
- `429` for per-user confirmation throttling;
- `503` when globally unavailable.

### `GET /api/bills/{bill_id}/enhancements/latest/`

Returns the newest owned enhancement plus staleness against the current source and execution identity. It returns `404` when none exists.

### `GET /api/bills/{bill_id}/enhancements/{enhancement_id}/`

Returns logical status, validated result with server-expanded cited sources, attempt history, per-attempt and cumulative known usage, sanitized categories, requested/resolved model, timestamps, staleness, and a bounded polling hint. It never exposes internal snapshots or provider response IDs.

### `POST /api/bills/{bill_id}/enhancements/{enhancement_id}/retry/`

Retry is another paid-action confirmation. It requires current `source_fingerprint`, `request_fingerprint`, and `credential_revision`, repeats full preflight, and creates exactly one new attempt. It is allowed only for API-declared retryable failures or `outcome_unknown`; refusal, invalid output, source loss, invalid credentials, quota exhaustion, and disabled feature states require remediation rather than replay. Quota exhaustion resets validation for only the credential revision used by the failed attempt; after resolving billing or quota, the user must explicitly validate that revision before retry becomes available.

When the previous state is `outcome_unknown`, the confirmation explicitly warns that the earlier provider request may have completed and another attempt may duplicate provider-side usage. The server never retries merely because a category is transient.

## Durable Dispatch and Execution

`BillEnhancementAttempt` is the durable work queue. Celery messages are disposable delivery hints containing only `attempt_id` and a random `dispatch_token`; they contain no credential or source data.

### Acceptance and dispatch

1. The API transaction commits the logical enhancement and one pending attempt.
2. `transaction.on_commit` performs a best-effort dispatcher wake. Broker errors are caught and logged by ID/category only; the accepted attempt remains pending.
3. A Celery Beat task in `apps/legislation/tasks.py` runs `dispatch_bill_enhancement_attempts` on a short interval and scans due pending attempts even if every on-commit wake failed.
4. A dispatcher locks a pending row, assigns a random `dispatch_token` and short dispatch lease, commits, and publishes `run_bill_enhancement_attempt(attempt_id, dispatch_token)`.
5. A publish failure releases or lets the dispatch lease expire so a later scan can publish again. An ambiguous publish may create duplicate messages, but not duplicate provider calls.

### Worker claim and call

1. The worker atomically claims only a pending attempt whose dispatch token matches, setting `running`, a random `run_token`, and a lease longer than provider timeout plus persistence overhead. Duplicate deliveries exit when that transition is no longer available.
2. Before decryption or network access, it verifies the global flag; user and bill existence; credential ownership/enabled state; exact credential revision; validation for that revision/provider/requested model; logical source/request fingerprints; and execution versions.
3. It decrypts and validates the contextual credential envelope.
4. It makes exactly one Responses API create call with `max_retries=0`, explicit timeout, complete request bounds, disabled truncation/storage, in-memory prompt caching, and no tools or conversation state.
5. It validates the response and persists only if its `run_token` still owns the attempt. Known usage is written on every response/error path where the provider supplied it.
6. Success atomically stores the attempt result, promotes it to the parent if no success exists, and recomputes cumulative known usage.

Celery task-level automatic retry is disabled for provider calls. Broker redelivery is safe because the attempt has already transitioned out of `pending`. The task must acknowledge late enough for delivery reliability, but a redelivered task cannot reclaim `running`, terminal, or expired-running work.

### Recovery and uncertain outcomes

A periodic recovery task scans expired `running` leases and marks them `outcome_unknown`. It never returns them to `pending` and never publishes them again. This conservative state covers process death, hard timeout, and any failure where the application cannot prove whether the provider accepted or completed the call.

A synchronous adapter timeout, connection interruption after request transmission, or worker failure before a definitive response also becomes `outcome_unknown`. A connection failure proven to occur before request transmission may be `failed/provider_unavailable`, but it is still not automatically retried. All additional calls require the explicit retry endpoint and a new attempt.

Terminal/sanitized categories include:

- `invalid_credentials`
- `model_access_denied`
- `quota_exhausted`
- `content_refusal`
- `invalid_output`
- `request_too_large`
- `source_unavailable`
- `feature_disabled`
- `credential_disabled`
- `credential_changed`
- `encryption_error`
- `provider_rate_limited`
- `provider_timeout`
- `provider_unavailable`
- `outcome_unknown`

Categories such as rate limit or known pre-send unavailability may be API-declared eligible for a user-confirmed retry, but never trigger one themselves.

Logs contain IDs, provider, requested/resolved model, status, duration, known usage, sequence, and sanitized category. They never contain API keys, ciphertext, request bodies, source text, prompts, result text, source quotes, or raw provider errors.

## Staleness and History

An enhancement is stale when any of these differ from current configuration:

- source fingerprint;
- request fingerprint;
- provider;
- requested model;
- reasoning effort;
- prompt version;
- output schema version; or
- source packet version.

Stale results remain private and readable with a clear label. A changed identity creates a separate logical enhancement. Replacing a key alone does not stale a completed result, but queued work bound to an earlier credential revision fails closed and requires new confirmation.

The provider-returned resolved model is stored per attempt/result for audit. It does not participate in preflight uniqueness because it is unknown before execution. A requested alias may resolve differently later, so stored results are auditable but not guaranteed exactly reproducible.

Deleting a bill or user cascades enhancements and attempts. Deleting a credential does not delete history. The first release retains the bounded source snapshot with the result so citations remain stable.

## Frontend

### Settings

Add authenticated `/settings` using `RequireAuth` and a Settings link in `AuthNav` for signed-in users.

The LLM section contains:

- global availability;
- provider and configured requested model;
- password-type API key input and masked suffix;
- Save, Validate, enable/disable, and Delete controls;
- copy stating that the encrypted key is used only for user-confirmed requests billed by the provider;
- a validation warning that exactly one small request may be charged;
- sanitized validation/configuration errors.

The client never stores a key in local/session storage, URL parameters, analytics, or persisted application state. It holds plaintext only for the save form and clears the input after submission.

### Bill detail

Add a separate panel after the deterministic contract. Anonymous users see a login link. When globally disabled, the panel is omitted. Signed-in users without a valid enabled credential see a Settings link.

For an eligible user:

1. Load the latest owned enhancement and complete-request estimate.
2. **Enhance with AI** opens confirmation showing provider, requested model, reasoning effort, conservative estimated input tokens, maximum output tokens, truncation/coverage copy, credential revision, and billing warning.
3. Confirm using current source/request fingerprints and credential revision.
4. Poll only `pending` and `running`; stop on terminal state, unmount, authentication failure, or bill change.
5. Success renders atomic overview, impacts, obligations, funding/timing, uncertain language, expandable **Cited source** text, per-attempt/cumulative usage, requested/resolved model, history, and fixed disclaimer.
6. Stale success remains visible with **Enhance current version**.
7. A retry control appears only when the API declares eligibility and always opens a new paid-action confirmation.
8. An `outcome_unknown` retry warning says the previous request may already have incurred usage.

The UI never labels output verified, optimistically displays provider output, or falls back to unvalidated raw text. A deduplicated `200` response is rendered as the existing job/result.

## Security and Privacy

- All credential and enhancement routes use JWT authentication and `IsAuthenticated` in separate views from the public `BillViewSet`.
- Object access filters by `request.user` before ID lookup.
- Fernet authenticated encryption plus contextual envelope checks prevent database-row ciphertext swapping.
- Request bodies containing keys are explicitly redacted/excluded in reverse-proxy access logs, Django request/error logging, APM, tracing, analytics, and exception reporting.
- Secrets are absent from serializers, admin displays, task arguments, structured logs, and raw errors.
- Provider calls use only the fixed configured provider/base URL; users cannot supply endpoints.
- OpenAI calls use `store=false`, explicit prompt-cache mode with no breakpoints, and no tools, browsing, conversations, or prior response IDs.
- Bill content is untrusted data and cannot enable actions.
- Structured schema and citation-integrity validation are mandatory before persistence as success.
- Every authenticated settings/enhancement response uses `Cache-Control: private, no-store`.
- Analytics record only coarse feature events/status and no key, source, prompt, or result content.

### Production transport prerequisite

The feature must fail closed in production unless HTTPS is enforced end to end or a trusted TLS-terminating proxy is explicitly configured. Production startup checks require secure proxy/header configuration where applicable, `SECURE_SSL_REDIRECT`, HSTS, secure cookies, `LLM_ENHANCEMENT_PRODUCTION_TLS_CONFIRMED=True`, and `LLM_ENHANCEMENT_SECRET_LOG_REDACTION_CONFIRMED=True`. The confirmation settings are explicit deployment assertions for external ingress and observability controls that Django cannot inspect. The public API container port must not provide an unencrypted bypass around the trusted ingress.

Local development may use HTTP only when both `DEBUG=True` and `LLM_ENHANCEMENT_ALLOW_INSECURE_HTTP_IN_DEBUG=True`. There is no production insecure-transport override. Readiness reports the feature as disabled or safely configured without contacting a provider or exposing configuration values.

This design reduces accidental disclosure but cannot protect secrets from a compromised application process. Operators must protect and rotate the key ring after suspected compromise.

## Rate Limits and Usage Visibility

Create and retry confirmations share a per-user throttle, initially `10/hour`. Validation uses a lower separate throttle. Estimate, history, detail, and polling make no provider calls and retain normal API abuse controls.

Before confirmation, the client displays the conservative estimate for the complete serialized request and the output ceiling. After completion, it displays provider-reported usage per attempt and cumulative known usage. `outcome_unknown` usage may be unavailable and is explicitly labeled unknown. The application does not calculate currency cost or promise provider pricing.

The worker independently rejects any changed or oversized request before a provider call. The output token parameter plus schema string/array bounds cap returned and persisted output.

## Quality Evaluation

Schema and citation integrity are necessary but not sufficient for semantic quality. Release requires a human-labeled evaluation corpus of at least 25 representative federal source packets, including:

- complete and truncated packets;
- amendments and cross-references;
- conflicting or conditional provisions;
- sparse evidence;
- funding, deadlines, obligations, and discretionary language; and
- prompt-injection-like instructions embedded in source text.

CI uses deterministic mocked/recorded adapter fixtures and never calls a live provider. A separate non-CI management command may run the versioned corpus only with a dedicated test key and an explicit `--execute` flag. It must show and enforce a bounded case count, maximum input/output budget, requested model, and reasoning effort before making calls.

Human reviewers score each atomic displayed claim for source support, overstatement, unsupported inference, citation selection, and prohibited completeness/absence language. Initial release gates are:

- 100% schema and citation-integrity validity;
- at least 95% of displayed claims judged supported by cited source text;
- zero uncited substantive claims; and
- zero completeness or absence claims for truncated inputs.

Failures require prompt/schema/source-selection revision and a new version before reevaluation. These are reviewed semantic gates, not automated claims of entailment.

## Operational Configuration and Rollout

Deployment sequence:

1. Ship migrations and code with `LLM_ENHANCEMENTS_ENABLED=False`.
2. Configure production TLS/proxy enforcement and log redaction; verify there is no direct insecure API path.
3. Generate a dedicated Fernet key and configure identical feature/provider/model/reasoning/bounds/key-ring settings in API, Beat, and worker environments.
4. Run startup checks, migrations, and all automated tests.
5. Run the bounded evaluation corpus with a dedicated non-production key and complete human review.
6. Enable in a non-production environment and validate credential races, durable broker-outage recovery, uncertain outcomes, redaction, usage, and deletion.
7. Enable production for an internal cohort, then the global deployment flag.

Beat schedules both pending-attempt dispatch and expired-running recovery. Monitoring covers pending age, dispatch failures, running lease expiry, outcome-unknown rate, provider category rates, duration, known usage, and validation failures without content or secrets.

Changing provider, requested model, reasoning effort, prompt, schema, or packet version makes previous results stale but readable. Provider/model changes also make credentials effectively unverified until revalidated. Encryption rotation is independent.

## Testing

No normal automated test makes a live provider request or uses a real key.

### Backend

- Credential envelope round trip, wrong key, key ID selection, rotation, tamper detection, and cross-user/provider/revision ciphertext swap rejection.
- Revision increments and validation reset on replacement/provider change.
- Validation compare-and-swap discards a response when key, provider, model, revision, or ciphertext changes during the network call.
- Validation success/refusal/error mapping with one SDK call, `max_retries=0`, and bounded timeout.
- Settings CRUD ownership/redaction, disabled-feature behavior, no-store headers, and request/error-log secret exclusion.
- Complete request canonicalization, byte limit, conservative token estimate, fixed-overhead failure, deterministic shrinking, truncation, and fingerprint stability.
- Adapter arguments for storage/cache/truncation/tools/conversation/reasoning/output/timeout controls.
- Schema bounds and citation-integrity rejection of unknown, missing, or corrupted references.
- Atomic claim schema and rejection of provider coverage, completeness, and absence fields.
- Authenticated enhancement views: anonymous, expired/stale JWT, cross-user, and owner cases; verify the separate public `BillViewSet` remains public.
- Concurrent create deduplication: one logical row, one attempt, one dispatcher-visible work item.
- Concurrent retry deduplication and exactly one new attempt per accepted retry confirmation.
- Broker publish failure after API commit followed by Beat discovery and successful delivery.
- Dispatcher duplicate/ambiguous publish, dispatch lease expiry, token mismatch, and duplicate worker delivery without a second adapter call.
- Credential changed/deleted/disabled between confirmation and claim fails before decryption/network access.
- Worker success, refusal, known failure, timeout, process-loss simulation, expired lease to `outcome_unknown`, and proof that recovery never calls the adapter.
- Assertions that SDK retry and Celery provider-call retry are disabled.
- Per-attempt usage, cumulative known usage, resolved model, history, and staleness across every identity input.
- Log capture proving distinctive fake keys, request bodies, source quotes, prompts, and result text do not appear on success or failure.
- Production configuration checks reject insecure transport, missing proxy/log-redaction assertion, invalid key ring, and mismatched lease/timeout.
- PostgreSQL constraint/index integration coverage plus SQLite service-invariant tests.

### Frontend

- Settings request/error handling, redaction, input clearing, validation charge warning, revision changes, enable/disable, deletion race copy, unavailable feature, and auth redirect.
- Bill panel anonymous, unconfigured, invalid, disabled, eligible, confirmation, deduplicated response, polling, success, refusal, failure, uncertain outcome, retry confirmation, stale, and bill-change states.
- Confirmation displays complete-request estimate, requested model/reasoning, credential revision, truncation, and billing warning.
- `outcome_unknown` displays duplicate-usage warning before retry.
- Citation expansion labels server text **Cited source** and never **Verified evidence** or provider-authored quotations.
- Poll cleanup and stale-response protection between bills.
- No-store header checks for all private routes.
- Playwright flow with a mocked adapter for save, validate, enhance, broker-delayed dispatch, poll, render, revisit, stale, uncertain outcome, explicit retry, and delete-key history.

### Final verification

- Full backend pytest suite on SQLite and PostgreSQL-specific integration coverage.
- Backend formatting/lint and migration consistency checks.
- Frontend Vitest and Node API suites.
- TypeScript typecheck, ESLint, and production build.
- Playwright end-to-end suite.
- Bounded non-CI provider evaluation and documented human gate results before production enablement.

## Acceptance Criteria

- With the global flag off, no provider call can occur and existing behavior is unchanged.
- A user can save, validate, enable, disable, replace, and delete only their own encrypted key without any API returning it.
- A stale credential-validation response cannot mark a replacement key valid.
- One accepted create/retry confirmation creates exactly one durable attempt and that attempt makes at most one provider request.
- No SDK, Celery, dispatcher, or recovery path automatically repeats a provider request.
- A broker outage cannot lose accepted work; Beat later discovers pending attempts.
- An expired running lease becomes `outcome_unknown` and requires warned user confirmation before another possible charge.
- A queued attempt cannot run with a different credential revision, provider, requested model, source, or version than confirmed.
- Repeated/concurrent requests for pending, running, or successful identity create no new attempt or provider call.
- The complete canonical request fits byte and conservative estimated-token bounds before work is accepted and before a call starts.
- Every displayed substantive claim carries server-owned cited-source references; integrity failure rejects the complete result.
- The product clearly states that citations are not automatically verified for entailment and passes the human quality release gates.
- Results are private, immutable, historical overlays and never alter deterministic contracts or `ChangeLog`.
- Source or execution-identity changes mark older results stale and permit a separate logical enhancement.
- Production enablement fails closed without secure transport, credential/log redaction, durable dispatcher/recovery, and valid configuration.
- The UI shows requested/resolved model and known usage without claiming an exact monetary price.
- Automated suites pass without live network access or real provider credentials.

## Deferred Work

- Additional providers.
- Organization-managed keys, shared billing, budgets, or administrator-issued credits.
- Multi-pass or full-document aggregation.
- Provider pricing lookup and currency estimates.
- Automated semantic entailment checking; human evaluation remains the release gate.
- Enhancement sharing, export, or public URLs.
- Browser-extension integration.
- Automatic enhancement workflows.
