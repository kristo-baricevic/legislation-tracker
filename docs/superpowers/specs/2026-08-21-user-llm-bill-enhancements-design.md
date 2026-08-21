# User-Owned LLM Bill Enhancements Design

**Date:** 2026-08-21
**Status:** Proposed design for implementation
**Scope:** Toggleable BYOK LLM settings, provider abstraction, source-grounded bill enhancements, asynchronous execution, private API, bill-detail UI, and operational controls

## Summary

Add an optional, user-triggered LLM layer over the existing deterministic legal-NLP output. A signed-in user can save their own provider API key in settings and explicitly request an enhanced explanation for one bill. The backend performs one bounded, asynchronous provider request, validates a strict structured response, verifies every substantive citation against stored source text, and stores the result as a private user-owned overlay.

The deterministic `BillContract`, `EvidenceSpan`, bill metadata, and `ChangeLog` remain canonical and shared. An LLM enhancement never changes ingestion output, never runs automatically, and never replaces canonical data. The deployment can disable the feature globally, and each user can disable or delete their own credential independently.

OpenAI is the first provider implementation behind a provider-agnostic adapter. The initial OpenAI implementation uses the Responses API with Structured Outputs. The model is deployment-configurable and defaults to `gpt-5.6`; changing the configured model does not require a schema migration.

## Goals

- Let a user opt into paid LLM enhancement with a provider key they control.
- Make every provider call an explicit, confirmed action for one bill.
- Keep provider usage bounded to one request per enhancement and show an input-size estimate before confirmation.
- Ground every substantive generated claim in exact source references supplied by the server.
- Keep credentials encrypted at rest, redacted from every response, and absent from task payloads and logs.
- Preserve enhancement history by source, provider, model, and prompt version without altering shared bill records.
- Deduplicate concurrent or repeated requests so accidental clicks do not create duplicate charges.
- Make provider failures, refusals, invalid output, and stale results visible and recoverable without corrupting canonical data.
- Keep provider-specific code isolated so another provider can be added without changing API or persistence contracts.

## Non-goals

- Running an LLM during bill, document, representative, vote, topic, or contract ingestion.
- Using an application-owned OpenAI key on behalf of all users.
- Replacing or mutating deterministic legal-NLP contracts, evidence, topics, similarity, or change history.
- Automatically enhancing tracked bills, newly ingested bills, or an entire backlog.
- Multi-pass whole-document analysis, embeddings, retrieval infrastructure, agents, tools, or provider-side actions.
- Sharing one user's enhancement or credential with another user.
- Claiming that an enhancement is legal advice, exhaustive, or authoritative.
- Adding LLM support to the browser extension in the first release.

## Product Boundaries

Three gates must all be open before an enhancement can be created:

1. `LLM_ENHANCEMENTS_ENABLED` is enabled by the deployment.
2. The signed-in user has an enabled, successfully validated credential.
3. The user explicitly confirms an enhancement for the current bill source fingerprint.

There are no scheduled or ingestion-triggered provider calls. Loading a bill, loading settings, estimating a request, polling a job, and viewing history never contact the provider.

The UI labels the output **AI enhancement** and displays the provider, model, creation time, source version, usage, and fixed legal-information disclaimer. It must not visually replace the deterministic contract section.

## Architecture

The feature is split across the existing domains:

- `apps.accounts` owns encrypted user provider credentials and settings endpoints.
- `apps.legislation` owns source-packet construction, enhancement records, provider adapters, asynchronous execution, and bill enhancement endpoints.
- The Next.js client owns the authenticated settings page and bill enhancement panel.
- Celery remains the background execution boundary, but LLM jobs are separate from durable ingestion work.

Suggested backend modules:

| File | Responsibility |
| --- | --- |
| `apps/accounts/llm_credentials.py` | Versioned authenticated encryption, decryption, redaction, and key-rotation helpers. |
| `apps/accounts/llm_serializers.py` | Credential settings input and redacted output contracts. |
| `apps/accounts/llm_views.py` | Authenticated settings CRUD and explicit validation endpoint. |
| `apps/legislation/enhancements/types.py` | Provider-neutral request, response, usage, and error types. |
| `apps/legislation/enhancements/providers/base.py` | Provider adapter protocol and error taxonomy. |
| `apps/legislation/enhancements/providers/openai.py` | OpenAI Responses API implementation. |
| `apps/legislation/enhancements/provider_registry.py` | Strict configured-provider lookup. |
| `apps/legislation/enhancements/source_packet.py` | Deterministic bounded source selection, references, estimates, and fingerprints. |
| `apps/legislation/enhancements/schema.py` | JSON Schema plus semantic citation validation. |
| `apps/legislation/enhancements/service.py` | Transactional creation, deduplication, retry eligibility, and result persistence. |
| `apps/legislation/enhancements/tasks.py` | Celery task and transient retry policy. |
| `apps/legislation/enhancements/prompts.py` | Versioned provider-neutral instructions and prompt assembly. |

The provider boundary is intentionally small:

```python
class EnhancementProvider(Protocol):
    provider_name: str

    def validate_credential(self, *, api_key: str, model: str) -> CredentialCheck:
        ...

    def enhance_bill(
        self,
        *,
        api_key: str,
        model: str,
        instructions: str,
        source_packet: dict[str, object],
        output_schema: dict[str, object],
    ) -> ProviderEnhancementResult:
        ...
```

Provider exceptions are converted at the adapter boundary into stable internal categories. Provider SDK objects, raw HTTP responses, and raw provider error text do not cross into views, serializers, tasks, or stored customer-visible fields.

## Data Model

### `LLMCredential`

Add a one-to-one credential in `apps.accounts`:

| Field | Purpose |
| --- | --- |
| `user` | One-to-one owner; cascade on account deletion. |
| `provider` | Provider slug; initially only `openai`. |
| `encrypted_api_key` | Authenticated ciphertext; never serialized. |
| `key_suffix` | Last four characters for recognition only. |
| `encryption_key_id` | Identifies the deployment encryption key used for this row. |
| `enabled` | User-level feature toggle. |
| `validation_status` | `unverified`, `valid`, or `invalid`. |
| `validated_at` | Time of the last successful or failed explicit validation. |
| `created_at`, `updated_at` | Audit timestamps. |

Saving a new API key always sets `validation_status=unverified`. Changing only `enabled` does not re-encrypt or revalidate the key. The API never returns the plaintext, ciphertext, length, prefix, or provider error detail. It returns only `configured`, `provider`, `key_suffix`, `enabled`, validation state, and timestamps.

Deleting the credential immediately prevents new work and queued jobs from starting. Existing enhancement results remain available to their owner. A running provider request cannot be recalled, but its result may finish and be stored after deletion; the UI and API explain this race when deletion is confirmed.

### `BillEnhancement`

Add a private enhancement record in `apps.legislation`:

| Field | Purpose |
| --- | --- |
| `user` | Owner; cascade on account deletion. |
| `bill` | Enhanced bill; cascade with the bill. |
| `credential` | Nullable `SET_NULL` reference for audit without blocking credential deletion. |
| `provider`, `model` | Immutable execution identity copied onto the job. |
| `prompt_version` | Immutable application prompt version. |
| `output_schema_version` | Stored response-contract version. |
| `source_packet_version` | Source selection algorithm version. |
| `source_fingerprint` | SHA-256 of the canonical source packet and its source identities. |
| `source_manifest_json` | Contract/document IDs, hashes, selection counts, and truncation flags. |
| `source_snapshot_json` | Exact bounded source references sent to the provider for reproducible citations. |
| `status` | `pending`, `running`, `retrying`, `succeeded`, `failed`, or `refused`. |
| `result_json` | Validated provider-neutral output; empty until success. |
| `input_tokens`, `output_tokens`, `total_tokens` | Actual provider-reported usage when available. |
| `failure_category` | Stable sanitized category, never raw provider text. |
| `attempt_count` | Worker attempts for this logical enhancement. |
| `run_token`, `lease_expires_at` | Crash-safe ownership lease for the active worker attempt. |
| `provider_response_id` | Optional private support identifier, not exposed by normal APIs. |
| `started_at`, `completed_at`, `created_at`, `updated_at` | Lifecycle timestamps. |

The database enforces uniqueness across:

```text
(user, bill, source_fingerprint, provider, model, prompt_version, output_schema_version, source_packet_version)
```

The row is the logical enhancement for that exact configuration. Concurrent creates return the same row. Repeated successful requests return the existing result without a provider call. An eligible transient failure is retried by resetting the same row through the explicit retry endpoint; it does not create another billable logical job.

Enhancement records are not written to `ChangeLog`, because they are private user state rather than canonical bill changes.

## Credential Encryption and Rotation

Add `cryptography` and use Fernet authenticated encryption. Encryption is not derived from `DJANGO_SECRET_KEY` and does not use a database-stored key.

Configuration:

- `LLM_ENHANCEMENTS_ENABLED=False` by default.
- `LLM_CREDENTIAL_ENCRYPTION_KEYS` is a comma-separated key ring of `key_id:fernet_key` entries.
- `LLM_CREDENTIAL_ACTIVE_KEY_ID` selects the key used for new writes.
- `LLM_ENHANCEMENT_PROVIDER=openai` selects the registered provider.
- `LLM_ENHANCEMENT_MODEL=gpt-5.6` selects the initial OpenAI model.
- `LLM_ENHANCEMENT_MAX_SOURCE_CHARS=60000` bounds provider input.
- `LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS=4000` bounds output.
- `LLM_ENHANCEMENT_CREATE_RATE=10/hour` sets the per-user create throttle.

When the global feature is enabled, startup checks must reject an empty key ring, a missing active ID, duplicate IDs, or malformed Fernet keys. When disabled, missing encryption configuration is allowed. Provider validation, credential creation/replacement, and enhancement creation report unavailable without attempting decryption, but redacted settings reads and credential deletion remain available so a user can always inspect or remove stored key material.

Decryption selects the row's `encryption_key_id`; failure is terminal and sanitized. A management command rotates rows to the active key in bounded transactions. Operators retain old keys until the command reports that no rows reference them. Plaintext exists only in process memory for the shortest practical scope and is never included in exceptions or logs.

## Credential Settings API

All settings endpoints require JWT authentication and are scoped to `request.user`:

### `GET /api/settings/llm/`

Returns feature capability and redacted user state:

```json
{
  "feature_available": true,
  "configured": true,
  "provider": "openai",
  "key_suffix": "1234",
  "enabled": true,
  "validation_status": "valid",
  "validated_at": "2026-08-21T12:00:00Z",
  "model": "gpt-5.6"
}
```

### `PUT /api/settings/llm/`

Accepts `api_key` and/or `enabled`. `provider` may be accepted only if it names a registered and deployment-allowed provider. A new key is encrypted immediately and replaces the previous ciphertext atomically. The key is never echoed back. Enabling without a configured key returns `400`. Creating, replacing, or enabling a credential while the deployment feature is unavailable returns `503`; disabling an existing credential remains available.

### `DELETE /api/settings/llm/`

Deletes the current user's credential and returns `204`. It does not delete enhancement history. This endpoint remains available while the global feature is disabled and does not require decryption.

### `POST /api/settings/llm/validate/`

Performs one explicit minimal provider request against the configured enhancement model. This may incur a small provider charge and the UI states that before submission. A valid response marks the row `valid`. Invalid authentication or model access marks it `invalid` and returns a sanitized validation result. Transient provider unavailability returns `503` and leaves the row `unverified` rather than incorrectly invalidating it.

No credential is automatically validated on save, application startup, login, or page load.

## Source Packet and Cost Bound

Source construction is deterministic and provider-neutral. It never asks the provider to fetch a URL or access the database.

Preferred source order:

1. The bill's current `latest_contract` structured JSON and its `EvidenceSpan` rows.
2. If the current contract has no usable evidence, section-aware chunks from the active `BillDocument.extracted_text` or `raw_text`.
3. If neither source exists, enhancement is unavailable and no job is created.

Every source reference has an opaque server-assigned ID and exact stored text:

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

Contract evidence is ordered by first source offset, de-duplicated by source range and quote, and selected across categories in round-robin order so one large category cannot consume the packet. Document fallback chunks preserve exact offsets and legal section boundaries where possible. No source reference exceeds 4,000 characters.

The canonical JSON packet, model-independent instructions, and source identities are hashed into `source_fingerprint`. Selection stops before `LLM_ENHANCEMENT_MAX_SOURCE_CHARS`; `source_manifest_json.truncated` records whether material was omitted. The UI must say **Based on selected source-backed provisions** when truncation occurred and must never describe the result as complete bill coverage.

The first release performs at most one provider request per enhancement. It does not recursively summarize, map/reduce chunks, or retry by splitting the source. A source packet that cannot fit the configured bound fails before enqueueing.

## Enhancement Output Contract

The provider receives:

- fixed developer instructions;
- bill metadata;
- a bounded source packet represented as data;
- a strict JSON Schema; and
- no tools, URLs to fetch, credentials other than provider authentication, or action capabilities.

The instructions explicitly identify legislative text as untrusted quoted content and tell the model to ignore instructions found inside it. The model may only analyze supplied content and cite supplied `source_ref` values.

Output schema version `1.0` contains:

```json
{
  "schema_version": "1.0",
  "overview": {
    "text": "This bill would require ...",
    "source_refs": ["src_0001", "src_0004"]
  },
  "key_impacts": [
    {"text": "...", "source_refs": ["src_0002"]}
  ],
  "obligations": [
    {
      "actor": "Secretary of Health and Human Services",
      "modality": "required",
      "action": "...",
      "conditions": null,
      "source_refs": ["src_0003"]
    }
  ],
  "funding_and_timing": [
    {"kind": "funding", "text": "...", "source_refs": ["src_0005"]}
  ],
  "ambiguities": [
    {
      "text": "The implementation standard is not defined in the selected provisions.",
      "why_it_matters": "...",
      "source_refs": ["src_0006"]
    }
  ],
  "coverage_notes": []
}
```

JSON Schema limits string lengths, array sizes, enum values, and object properties, with `additionalProperties: false` throughout. Every substantive item requires at least one source reference. `coverage_notes` may contain only constrained non-substantive caveats; the server supplies the legal-information disclaimer separately.

After schema validation, semantic validation requires every returned reference to exist in `source_snapshot_json`. The server ignores provider-generated quotations and expands citations from its own stored snapshot. A response with an unknown or missing required reference is `invalid_output`; it is never partially displayed.

The OpenAI adapter uses the Responses API Structured Outputs shape documented at:

- <https://developers.openai.com/api/docs/guides/structured-outputs>
- <https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.6#migrate-to-gpt-56>
- <https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.6#prompting-best-practices>

It explicitly handles successful structured output, provider refusal, incomplete output, and missing output before passing data to application validation.

## Enhancement API

All enhancement endpoints require authentication. Ownership failures return `404` so callers cannot discover another user's record.

### `GET /api/bills/{bill_id}/enhancements/estimate/`

Builds the current source packet without contacting a provider. It returns:

- provider and model;
- source fingerprint and source description;
- estimated input tokens using a documented conservative local estimate;
- configured maximum output tokens;
- truncation state;
- whether the current user can enhance;
- an existing matching enhancement ID and status, if present; and
- a stable reason when unavailable.

The estimate is informational, not a price promise. Provider pricing is not hard-coded because it changes independently of the application.

### `GET /api/bills/{bill_id}/enhancements/`

Returns the current user's paginated enhancement history for that bill, newest first. It never returns another user's rows or source snapshot internals.

### `POST /api/bills/{bill_id}/enhancements/`

Accepts the `source_fingerprint` shown during confirmation. The server rebuilds the packet and returns `409 source_changed` if it no longer matches. It then atomically gets or creates the unique logical enhancement and enqueues the Celery task only after transaction commit.

Responses:

- `202` for a newly queued enhancement;
- `200` for an existing matching pending, running, or successful enhancement;
- `409` for source change, invalid credential state, terminal prior failure, or unavailable source;
- `429` when the per-user create throttle is exceeded;
- `503` when the feature is globally unavailable.

### `GET /api/bills/{bill_id}/enhancements/latest/`

Returns the newest user-owned enhancement plus `is_stale`, computed against the current source fingerprint, provider, model, prompt version, and schema version. It returns `404` when the user has no enhancement for the bill.

### `GET /api/bills/{bill_id}/enhancements/{enhancement_id}/`

Returns status, validated result and server-expanded citations, usage, sanitized failure category, timestamps, and staleness. Pending polling includes a bounded `retry_after_seconds` hint.

### `POST /api/bills/{bill_id}/enhancements/{enhancement_id}/retry/`

Retries only an owner-matching row whose last failure is classified transient and whose source/configuration is still current. It atomically returns the row to `pending` and enqueues after commit. Invalid credentials, quota exhaustion, refusal, invalid output, source loss, and disabled feature states are not replayable through this endpoint.

## Asynchronous Lifecycle and Error Policy

The Celery payload contains only `enhancement_id`. The worker reloads the enhancement, current feature state, credential, and source snapshot. It decrypts the credential immediately before constructing the provider client.

Lifecycle:

1. Lock the enhancement row and claim `pending`, due `retrying`, or expired `running` work with a random run token and a lease longer than the provider timeout; duplicate deliveries with a live lease exit safely.
2. Verify the global toggle, credential ownership/enabled/valid state, and source snapshot.
3. Decrypt the key and perform one provider request outside the database transaction.
4. Parse, schema-validate, and citation-validate the response.
5. Lock the row again and persist only when the run token still owns the lease, then atomically store success, refusal, or sanitized failure plus usage and timestamps.

Automatic Celery retry is limited to provider rate limiting, timeout, connection failure, and provider 5xx responses. A retryable attempt stores `retrying`, clears its lease, records the next retry time, and uses exponential backoff with jitter, a low fixed attempt cap, and the same logical row. Exhaustion stores `failed` with an API-visible `retryable` flag. Provider idempotency metadata includes the enhancement ID when supported. Lease expiry prevents a worker crash from leaving a job permanently `running`; the redelivered task can reclaim it after the lease. Because a connection can fail after the provider accepted a request, or a worker can die after the provider succeeds but before persistence, retries can occasionally create provider-side duplicate usage even though the application does not create duplicate records. The UI and documentation disclose this boundary.

Terminal categories include:

- `invalid_credentials`
- `model_access_denied`
- `quota_exhausted`
- `content_refusal`
- `invalid_output`
- `source_unavailable`
- `feature_disabled`
- `credential_disabled`
- `encryption_error`

Transient categories include:

- `provider_rate_limited`
- `provider_timeout`
- `provider_unavailable`

Logs contain IDs, provider, model, status, duration, usage counts, attempt count, and failure category. Logs never contain API keys, ciphertext, bill source text, prompts, generated result text, source quotes, or raw provider errors.

## Staleness and History

An enhancement is stale when any of these differ from current configuration:

- source fingerprint;
- provider;
- model;
- prompt version;
- output schema version; or
- source packet version.

Stale results remain readable and are clearly labeled. Creating an enhancement for the new configuration creates a separate history row. Changing a user's API key alone does not stale a successful result because the result identity is provider/model/source/prompt based, not secret based.

Deleting a bill or user cascades their enhancements. Deleting a credential does not. A future retention policy may prune source snapshots, but the initial release retains them with the result so citations remain reproducible.

## Frontend

### Settings

Add authenticated `/settings` using the existing `RequireAuth` boundary and add a Settings link to `AuthNav` only when signed in.

The LLM section contains:

- global availability state;
- provider and configured model;
- password-type API key input;
- masked saved-key suffix;
- Save key, Validate key, enable/disable, and Delete key controls;
- explicit copy that the key is encrypted on this server, used only for user-triggered requests, and billed by the provider;
- a warning that validation makes a small provider request; and
- sanitized validation and configuration errors.

The client never stores the API key in local storage, session storage, URL parameters, analytics, or component state longer than the save request. After save, the input is cleared.

### Bill detail

Add a separate enhancement panel after the deterministic contract section. Anonymous users see a login link. When globally disabled, the panel is omitted. Signed-in users without a valid enabled credential see a Settings link.

For an eligible user:

1. Load the latest owned enhancement and local estimate.
2. Clicking **Enhance with AI** opens an inline confirmation showing provider, model, estimated input tokens, maximum output tokens, source/truncation note, and the provider-billing warning.
3. Confirming posts the current source fingerprint.
4. Pending, running, and retrying jobs poll their detail endpoint using the server hint and stop on terminal state, unmount, authentication failure, or bill change.
5. Success renders overview, impacts, obligations, funding/timing, ambiguities, expandable exact citations, usage, history metadata, and disclaimer.
6. Stale success remains visible with **Enhance current version**.
7. Retry appears only for an API-declared retryable failure.

The UI never optimistically displays provider output and never falls back to unvalidated raw text. It handles a deduplicated `200` response exactly like the original job.

## Security and Privacy

- All credential and enhancement APIs require JWT authentication.
- Object access is always filtered by `request.user` before ID lookup.
- Fernet provides authenticated encryption; the database alone is insufficient to decrypt keys.
- Secrets are redacted from serializers, admin displays, task arguments, logs, tracing, and error reporting.
- Provider calls use the user key only for the chosen provider and configured API base URL; users cannot supply arbitrary endpoints.
- No tools, browsing, function calls, or provider-side actions are enabled.
- Bill content is treated as untrusted data and cannot change system instructions.
- Strict output schema and server-side source-reference validation are mandatory before persistence as success.
- API responses include `Cache-Control: private, no-store` for credential settings and private enhancement detail.
- Application analytics record only feature events and coarse status, never key material, source text, prompts, or generated content.

This protects against accidental secret exposure and prompt-driven actions. It does not make a compromised application process safe; operators must protect the encryption key ring and rotate it after suspected compromise.

## Rate Limits and Usage Visibility

The create endpoint uses a per-user authenticated throttle, initially `10/hour` and configurable. Credential validation uses a separate lower throttle. Estimate, list, detail, and polling endpoints do not trigger provider calls and have normal API abuse controls.

Before confirmation, the client displays a conservative local token estimate and configured output ceiling. After completion, it displays actual provider-reported input, output, and total tokens when available. The application does not calculate currency cost or promise provider pricing.

The backend must reject a packet above configured limits before enqueueing and must set the provider's maximum output token parameter. Array and string bounds in the response schema cap persisted output size.

## Operational Configuration and Rollout

Deployment sequence:

1. Ship migrations and code with `LLM_ENHANCEMENTS_ENABLED=False`.
2. Generate a dedicated Fernet key, configure the key ring and active ID in the API and Celery worker environments, and restart both.
3. Run configuration checks and the full test suite.
4. Enable the feature in a non-production environment and validate with a dedicated test account and test provider key.
5. Verify credential redaction, queue behavior, refusal/error rendering, usage reporting, and deletion.
6. Enable production for an internal account or environment first, then enable the global deployment flag.

API and workers must use identical feature, provider, model, prompt, output, and encryption-key configuration. Readiness should report the LLM feature as disabled or correctly configured without contacting the provider or exposing configuration values.

Changing model, prompt version, output schema, or packet version makes previous results stale but readable. Encryption rotation is independent and uses the management command before an old key is removed.

## Testing

No automated test makes a live provider request or uses a real API key.

### Backend

- Credential encryption round trip, wrong key, key ID selection, rotation, and ciphertext tamper detection.
- Settings create/update/delete ownership, redaction, disabled feature behavior, and validation state transitions.
- Provider adapter success, refusal, incomplete output, authentication, access, quota, rate limit, timeout, 5xx, and malformed output mapping with mocked SDK responses.
- Deterministic source selection, exact offsets, category balancing, truncation, size limits, fingerprint stability, and source-change detection.
- JSON Schema bounds and semantic rejection of unknown, missing, or fabricated source references.
- Enhancement creation authentication, ownership, deduplication under concurrency, transaction-on-commit enqueue, and per-user throttling.
- Worker duplicate delivery, success, sanitized failure, retry cap/backoff classification, deleted/disabled credential, global shutdown, and secret-free task arguments.
- History ordering, latest selection, staleness across every identity input, private serialization, and credential deletion preserving results.
- A log-capture test asserting that a distinctive fake key and source quotation never appear in expected success and failure logs.

### Frontend

- API client request and error handling for settings, estimate, create, latest, detail, retry, and delete.
- Settings redaction, key input clearing, validation warning, enable/disable, deletion confirmation, unavailable feature, and auth redirect.
- Bill panel anonymous, unconfigured, invalid, disabled, eligible, confirmation, deduplicated job, polling, success, refusal, failure, retryable, stale, and bill-change states.
- Citation expansion uses server-returned exact citations and never provider-authored quote text.
- Polling cleanup on unmount and stale-response protection when navigating between bills.
- Playwright flow with mocked provider adapter for save, validate, enhance, poll, render, revisit, stale, and delete-key history behavior.

### Final verification

- Full backend pytest suite on SQLite and PostgreSQL-specific integration coverage where required.
- Backend formatting/lint and migration consistency checks.
- Frontend Vitest and Node API test suites.
- TypeScript typecheck, ESLint, and production build.
- Playwright end-to-end suite.

## Acceptance Criteria

- With the global flag off, no LLM provider call can occur and the existing application behavior is unchanged.
- A user can save, validate, enable, disable, replace, and delete only their own encrypted OpenAI key without the API ever returning it.
- An authenticated eligible user can explicitly confirm one enhancement for a bill and observe its asynchronous status.
- Repeated or concurrent requests for the same enhancement identity do not create another application job or provider call.
- Every displayed substantive claim cites one or more exact server-owned source references; invalid citations make the entire result fail closed.
- Successful results are private, immutable, historical overlays and never change deterministic contracts or `ChangeLog`.
- Source, model, prompt, schema, or packet changes mark older results stale and allow one new enhancement identity.
- Provider failures are sanitized and classified; only transient failures retry automatically or expose replay.
- The UI shows usage and a preflight estimate but never claims an exact monetary price.
- Test suites pass without live network access or real provider credentials.

## Deferred Work

- Additional providers.
- Organization-managed keys, shared billing, budgets, or administrator-issued credits.
- Multi-pass or full-document chunk aggregation.
- Provider pricing lookup and currency cost estimates.
- Enhancement sharing, collaboration, export, or public URLs.
- Browser-extension integration.
- Automatic enhancement workflows.
