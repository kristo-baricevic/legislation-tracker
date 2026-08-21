# User-Owned LLM Bill Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Checked steps record the completed implementation.

**Implementation status (2026-08-21):** Complete and locally verified on PR #4. The feature remains disabled by default and is not deployed. All task checkboxes below record completed implementation work; expected RED failures describe the TDD checkpoints that preceded the final code.

**Post-review implementation corrections:** OpenAI receives a provider-compatible schema while the server retains stronger local validation; request content uses a one-UTF-8-byte-per-token conservative bound; ambiguous dispatch rollover reuses its token; the OpenAI SDK floor is 2.54; transient browser polling recovers; bill pages expose paginated enhancement history/detail; non-federal eligibility is resolved before private calls; the 25-case corpus includes labels/rubric and multi-source adversarial cases; and Playwright exercises live Django/Celery persistence through an explicitly gated deterministic E2E provider.

**Goal:** Deliver a globally toggleable, private BYOK OpenAI enhancement flow for one bill at a time, with encrypted credentials, bounded source-backed requests, durable one-call attempts, history, and settings/bill UI.

**Architecture:** `apps.accounts` owns revisioned encrypted credentials and authenticated settings APIs. `apps.legislation.enhancements` owns deterministic request construction, schema/citation validation, provider adapters, logical enhancements, durable attempts, execution, and authenticated bill APIs; top-level legislation Celery tasks provide Beat-discovered delivery. The Next.js client adds a private settings route and an enhancement panel after the deterministic contract.

**Tech Stack:** Django 5.2, Django REST Framework, SimpleJWT, Celery, SQLite/PostgreSQL, Fernet (`cryptography`), OpenAI Python SDK Responses API, Next.js 16 App Router, React 19, TypeScript, Vitest, Testing Library, Node test runner, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-21-user-llm-bill-enhancements-design.md`

## Global Constraints

- The deployment flag defaults to `False`; disabled means no provider call path.
- One accepted create/retry confirmation creates one append-only attempt and authorizes at most one provider request.
- OpenAI client uses `max_retries=0`, a 90-second timeout, `store=False`, disabled truncation, no tools/conversation state, and no implicit prompt-cache breakpoint.
- Default requested model is `gpt-5.6-luna`; default reasoning effort is `none`.
- The complete canonical request is capped at 120,000 UTF-8 bytes and a conservative 60,000 estimated input tokens; output is capped at 4,000 tokens.
- All credential/enhancement routes use JWT plus `IsAuthenticated`, owner-filtered lookup, and `Cache-Control: private, no-store`; they are never actions on the public `BillViewSet`.
- No key, ciphertext, request/source/prompt/result body, provider raw error, or provider response ID enters normal API responses, Celery payloads, logs, tracing, or analytics.
- Schema validation proves shape and citation integrity only; UI copy says **Cited source**, never verified evidence.
- Tests use fake keys, mocked SDK adapters, or the explicitly gated deterministic E2E provider; normal suites make no live provider request.
- Current OpenAI reference deprecates `prompt_cache_retention`; use `prompt_cache_options={"mode": "explicit", "ttl": "30m"}` with no cache breakpoints to disable implicit prompt caching.

---

### Task 1: Configuration, encryption, and revisioned credential persistence

**Files:**
- Modify: `legislation-tracker-backend/requirements/base.txt`
- Modify: `legislation-tracker-backend/config/settings/base.py`
- Modify: `legislation-tracker-backend/config/settings/prod.py`
- Create: `legislation-tracker-backend/apps/accounts/llm_credentials.py`
- Modify: `legislation-tracker-backend/apps/accounts/models.py`
- Create: `legislation-tracker-backend/apps/accounts/migrations/0006_llmcredential.py`
- Create: `legislation-tracker-backend/apps/accounts/tests/test_llm_credentials.py`
- Create: `legislation-tracker-backend/apps/accounts/tests/test_llm_configuration.py`

**Interfaces:**
- Produces: `LLMCredential`, `encrypt_credential(*, user_id, provider, revision, api_key) -> tuple[str, str]`, `decrypt_credential(credential) -> str`, `parse_encryption_key_ring() -> dict[str, Fernet]`, and `llm_feature_configuration_errors() -> list[str]`.

- [x] **Step 1: Write failing encryption/model/configuration tests**

```python
credential = LLMCredential.objects.create_for_key(user=user, provider="openai", api_key="sk-test-secret")
assert credential.revision == 1
assert decrypt_credential(credential) == "sk-test-secret"
credential.replace_key("sk-test-second")
assert credential.revision == 2
assert credential.validation_status == LLMCredential.ValidationStatus.UNVERIFIED
```

Cover tampering, wrong key ID, ciphertext copied to another user/revision, suffix mismatch, malformed key rings, enabled-feature missing config, and production secure-transport assertions.

- [x] **Step 2: Run RED tests**

Run: `rtk run ".venv/bin/pytest apps/accounts/tests/test_llm_credentials.py apps/accounts/tests/test_llm_configuration.py -q"`
Expected: collection/import failure because the model/helpers do not exist.

- [x] **Step 3: Implement dependencies, settings, contextual Fernet envelope, model, and migration**

```python
payload = json.dumps({
    "version": 1,
    "user_id": str(user_id),
    "provider": provider,
    "revision": revision,
    "api_key": api_key,
}, sort_keys=True, separators=(",", ":")).encode()
```

Use a manager/service to lock replacements, increment revision, reset validation fields, and save `key_suffix` and active key ID. Production checks fail closed only when the feature is enabled.

- [x] **Step 4: Run GREEN tests and migration check**

Run: `rtk run ".venv/bin/pytest apps/accounts/tests/test_llm_credentials.py apps/accounts/tests/test_llm_configuration.py -q"`
Run: `rtk run ".venv/bin/python manage.py makemigrations --check --dry-run"`
Expected: tests pass; no ungenerated migration.

### Task 4: Authenticated credential settings and compare-and-swap validation

**Files:**
- Create: `legislation-tracker-backend/apps/accounts/llm_serializers.py`
- Create: `legislation-tracker-backend/apps/accounts/llm_views.py`
- Modify: `legislation-tracker-backend/config/urls.py`
- Create: `legislation-tracker-backend/apps/accounts/tests/test_llm_settings_api.py`

**Interfaces:**
- Produces: `/api/settings/llm/` GET/PUT/DELETE and `/api/settings/llm/validate/` POST.
- Consumes: `get_provider(name)` from Task 3 through a lazy import for explicit validation.

- [x] **Step 1: Write failing private API tests**

```python
response = authenticated_client.put("/api/settings/llm/", {"api_key": "sk-test-one", "enabled": True}, format="json")
assert response.status_code == 200
assert response.json()["key_suffix"] == "-one"
assert "api_key" not in response.json()
assert response["Cache-Control"] == "private, no-store"
```

Cover anonymous 401, cross-user isolation, disabled global flag, disable/delete while unavailable, no secret echo, validation warning state, `max_retries=0`, and a concurrent credential replacement causing validation CAS to discard the stale result.

- [x] **Step 2: Run RED tests**

Run: `rtk run ".venv/bin/pytest apps/accounts/tests/test_llm_settings_api.py -q"`
Expected: 404/import failures for missing routes/views.

- [x] **Step 3: Implement serializers, views, no-store helper, throttles, and routes**

Validation snapshots `(pk, revision, provider, requested_model, encrypted_envelope)` before the one external call and updates with an exact filtered `UPDATE`; a zero row count returns a sanitized stale-validation response.

- [x] **Step 4: Run GREEN tests**

Run: `rtk run ".venv/bin/pytest apps/accounts/tests/test_llm_settings_api.py -q"`
Expected: pass with no live network.

### Task 2: Deterministic complete-request builder and output validation

**Files:**
- Create: `legislation-tracker-backend/apps/legislation/enhancements/__init__.py`
- Create: `legislation-tracker-backend/apps/legislation/enhancements/types.py`
- Create: `legislation-tracker-backend/apps/legislation/enhancements/prompts.py`
- Create: `legislation-tracker-backend/apps/legislation/enhancements/schema.py`
- Create: `legislation-tracker-backend/apps/legislation/enhancements/source_packet.py`
- Create: `legislation-tracker-backend/apps/legislation/tests/test_enhancement_source_packet.py`
- Create: `legislation-tracker-backend/apps/legislation/tests/test_enhancement_schema.py`

**Interfaces:**
- Produces: `build_enhancement_preflight(bill) -> EnhancementPreflight`, `canonical_json_bytes(value) -> bytes`, `estimate_input_tokens(bytes) -> int`, `OUTPUT_SCHEMA`, and `validate_enhancement_output(value, source_snapshot) -> dict`.

- [x] **Step 1: Write failing builder and schema tests**

```python
preflight = build_enhancement_preflight(bill)
assert preflight.estimated_input_tokens == len(preflight.request_bytes)
assert preflight.request_fingerprint == hashlib.sha256(preflight.request_bytes).hexdigest()
assert preflight.source_snapshot[0]["quoted_text"] == "The Secretary shall report."
```

Cover evidence ordering/deduplication, document fallback, round-robin selection, fixed-overhead rejection, deterministic shrinking/truncation, stable fingerprints, exact byte bound, atomic schema, unknown/missing/corrupted refs, and prohibited coverage/absence properties.

- [x] **Step 2: Run RED tests**

Run: `rtk run ".venv/bin/pytest apps/legislation/tests/test_enhancement_source_packet.py apps/legislation/tests/test_enhancement_schema.py -q"`
Expected: import failure for missing enhancement package.

- [x] **Step 3: Implement canonical preflight and validation**

```python
request_bytes = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
estimated_tokens = len(request_bytes)
```

Store exact server-owned quote hashes; output uses arrays of atomic overview/impact items plus obligations, funding/timing, and `uncertain_language`. Server copy supplies disclaimer and truncation notes.

- [x] **Step 4: Run GREEN tests**

Run: `rtk run ".venv/bin/pytest apps/legislation/tests/test_enhancement_source_packet.py apps/legislation/tests/test_enhancement_schema.py -q"`
Expected: pass.

### Task 3: Provider-neutral adapter and OpenAI implementation

**Files:**
- Create: `legislation-tracker-backend/apps/legislation/enhancements/providers/__init__.py`
- Create: `legislation-tracker-backend/apps/legislation/enhancements/providers/base.py`
- Create: `legislation-tracker-backend/apps/legislation/enhancements/providers/openai.py`
- Create: `legislation-tracker-backend/apps/legislation/enhancements/provider_registry.py`
- Create: `legislation-tracker-backend/apps/legislation/tests/test_enhancement_openai_provider.py`

**Interfaces:**
- Produces: `EnhancementProvider`, `ProviderResult`, `ProviderUsage`, `ProviderError(category, outcome_unknown, retry_allowed)`, `PROVIDER_OUTPUT_SCHEMA`, and `get_provider(name)`.

- [x] **Step 1: Write failing adapter tests using a fake SDK client factory**

```python
result = provider.enhance_bill(api_key="sk-test", request=request, timeout_seconds=90)
assert result.output["schema_version"] == "1.1"
assert fake_factory.kwargs == {"api_key": "sk-test", "max_retries": 0, "timeout": 90}
assert fake_responses.kwargs["store"] is False
assert fake_responses.kwargs["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}
assert fake_responses.kwargs["tools"] == []
```

Cover requested args, completed/refused/incomplete/malformed responses, auth/model/quota/rate/5xx mapping, pre-send connection failure, and timeout/ambiguous connection as `outcome_unknown`.

- [x] **Step 2: Run RED tests**

Run: `rtk run ".venv/bin/pytest apps/legislation/tests/test_enhancement_openai_provider.py -q"`
Expected: missing adapter import.

- [x] **Step 3: Implement adapter and registry**

Use OpenAI SDK `>=2.54,<3` and `client.responses.create(text={"format": {"type": "json_schema", "name": "bill_enhancement_v1_1", "schema": PROVIDER_OUTPUT_SCHEMA, "strict": True}}, ...)`. Strip unsupported provider keywords such as `uniqueItems`, retain the full `OUTPUT_SCHEMA` for local validation, inspect terminal status/refusal before `json.loads(response.output_text)`, and never log the raw exception or payload.

- [x] **Step 4: Run GREEN tests**

Run: `rtk run ".venv/bin/pytest apps/legislation/tests/test_enhancement_openai_provider.py -q"`
Expected: pass with exactly one fake SDK call per adapter invocation.

### Task 5: Logical enhancements, durable attempts, service, and private API

**Files:**
- Modify: `legislation-tracker-backend/apps/legislation/models.py`
- Create: `legislation-tracker-backend/apps/legislation/migrations/0007_bill_enhancements.py`
- Create: `legislation-tracker-backend/apps/legislation/enhancements/service.py`
- Create: `legislation-tracker-backend/apps/legislation/enhancements/serializers.py`
- Create: `legislation-tracker-backend/apps/legislation/enhancements/views.py`
- Modify: `legislation-tracker-backend/config/urls.py`
- Create: `legislation-tracker-backend/apps/legislation/tests/test_enhancement_service.py`
- Create: `legislation-tracker-backend/apps/legislation/tests/test_enhancement_api.py`

**Interfaces:**
- Produces: `BillEnhancement`, `BillEnhancementAttempt`, `create_enhancement_attempt(...)`, `retry_enhancement_attempt(...)`, estimate/history/latest/detail/create/retry endpoints.

- [x] **Step 1: Write failing service/API tests**

```python
first = create_enhancement_attempt(user=user, bill=bill, confirmed=confirmation)
second = create_enhancement_attempt(user=user, bill=bill, confirmed=confirmation)
assert first.created is True
assert second.created is False
assert BillEnhancementAttempt.objects.count() == 1
```

Cover exact request fingerprint uniqueness, active-attempt uniqueness, credential/preflight mismatch 409, 200 dedupe, 202 creation, explicit retry sequence, refusal non-retry, unknown-outcome warning, ownership 404, anonymous/stale JWT 401, public bill route remaining public, no-store, private serialization, usage/history, and staleness.

- [x] **Step 2: Run RED tests**

Run: `rtk run ".venv/bin/pytest apps/legislation/tests/test_enhancement_service.py apps/legislation/tests/test_enhancement_api.py -q"`
Expected: missing models/routes.

- [x] **Step 3: Implement models, migration, transactional service, serializers, separate authenticated views, routes, and throttles**

Use parent-row locking for sequence allocation and a conditional unique constraint on active attempt statuses. `transaction.on_commit(request_enhancement_dispatch)` catches broker errors; Beat remains authoritative.

- [x] **Step 4: Run GREEN tests and migration check**

Run: `rtk run ".venv/bin/pytest apps/legislation/tests/test_enhancement_service.py apps/legislation/tests/test_enhancement_api.py -q"`
Run: `rtk run ".venv/bin/python manage.py makemigrations --check --dry-run"`
Expected: pass; migrations match models.

### Task 6: Durable dispatcher, single-call worker, and uncertain-outcome recovery

**Files:**
- Create: `legislation-tracker-backend/apps/legislation/enhancements/dispatch.py`
- Modify: `legislation-tracker-backend/apps/legislation/tasks.py`
- Modify: `legislation-tracker-backend/config/celery.py`
- Create: `legislation-tracker-backend/apps/legislation/tests/test_enhancement_tasks.py`
- Modify: `legislation-tracker-backend/apps/ingestion/tests/test_celery_schedule.py`

**Interfaces:**
- Produces Celery tasks `dispatch_bill_enhancement_attempts`, `run_bill_enhancement_attempt`, and `recover_stale_bill_enhancement_attempts` in `apps.legislation.tasks`.

- [x] **Step 1: Write failing dispatch/worker/recovery tests**

```python
dispatch_bill_enhancement_attempts()
assert fake_apply_async.calls == [(attempt.id, attempt.dispatch_token)]
run_bill_enhancement_attempt(attempt.id, attempt.dispatch_token)
assert fake_provider.call_count == 1
run_bill_enhancement_attempt(attempt.id, attempt.dispatch_token)
assert fake_provider.call_count == 1
```

Cover publish failure returning pending, delayed delivery after dispatch-lease rollover with a stable token, ambiguous duplicate delivery, token mismatch, changed/deleted/disabled credential before network, success/refusal/failure usage, no Celery retry, expired running to `outcome_unknown`, and recovery never invoking adapter.

- [x] **Step 2: Run RED tests**

Run: `rtk run ".venv/bin/pytest apps/legislation/tests/test_enhancement_tasks.py apps/ingestion/tests/test_celery_schedule.py -q"`
Expected: missing tasks/schedule.

- [x] **Step 3: Implement leases and top-level tasks**

Pending dispatch may repeat only message publication. Lease rollover reuses the existing dispatch token because the original message may merely be delayed; a known publish failure clears it. Worker claim is the irreversible boundary: once status becomes running, no delivery or recovery can return it to pending. Timeout/ambiguous connection writes `outcome_unknown`; expired run leases are only marked unknown.

- [x] **Step 4: Run GREEN tests**

Run: `rtk run ".venv/bin/pytest apps/legislation/tests/test_enhancement_tasks.py apps/ingestion/tests/test_celery_schedule.py -q"`
Expected: pass and one adapter call in duplicate-delivery test.

### Task 7: Frontend API client, settings page, and navigation

**Files:**
- Modify: `legislation-tracker-client/lib/api.ts`
- Create: `legislation-tracker-client/app/settings/page.tsx`
- Modify: `legislation-tracker-client/app/components/AuthNav.tsx`
- Create: `legislation-tracker-client/tests/api-llm.test.ts`
- Create: `legislation-tracker-client/tests/components/llm-settings-page.test.tsx`

**Interfaces:**
- Produces typed credential settings/validation helpers and `/settings` UI.

- [x] **Step 1: Write failing API/component tests**

```typescript
render(<SettingsPage />)
await user.type(screen.getByLabelText(/OpenAI API key/i), "sk-test-secret")
await user.click(screen.getByRole("button", { name: /Save key/i }))
expect(screen.getByLabelText(/OpenAI API key/i)).toHaveValue("")
expect(screen.queryByDisplayValue("sk-test-secret")).not.toBeInTheDocument()
```

Cover auth redirect, unavailable state, masked suffix, save/replace, validation charge warning, enable/disable, delete confirmation, sanitized errors, revision updates, and Settings nav visibility only while signed in.

- [x] **Step 2: Run RED tests**

Run: `rtk pnpm vitest run tests/components/llm-settings-page.test.tsx`
Run: `rtk pnpm run test:api -- tests/api-llm.test.ts`
Expected: missing imports/route.

- [x] **Step 3: Implement typed helpers and client settings UI**

Keep key plaintext only in controlled form state, clear after every successful save, and never render/store it elsewhere.

- [x] **Step 4: Run GREEN tests**

Run: `rtk pnpm vitest run tests/components/llm-settings-page.test.tsx`
Run: `rtk pnpm run test:api`
Expected: pass.

### Task 8: Bill enhancement panel and user-confirmed execution flow

**Files:**
- Create: `legislation-tracker-client/app/bills/[id]/bill-enhancement-panel.tsx`
- Modify: `legislation-tracker-client/app/bills/[id]/page.tsx`
- Create: `legislation-tracker-client/tests/components/bill-enhancement-panel.test.tsx`
- Modify: `legislation-tracker-client/tests/components/bill-detail-page.test.tsx`
- Create: `legislation-tracker-client/e2e/llm-enhancement.spec.ts`

**Interfaces:**
- Consumes typed estimate/create/latest/detail/retry APIs from Task 7.

- [x] **Step 1: Write failing panel behavior tests**

```typescript
render(<BillEnhancementPanel billId={42} jurisdiction="federal" />)
await screen.findByRole("button", { name: "Enhance with AI" })
await user.click(screen.getByRole("button", { name: "Enhance with AI" }))
expect(screen.getByText(/estimated input tokens/i)).toBeInTheDocument()
expect(screen.getByText(/provider may charge/i)).toBeInTheDocument()
```

Cover anonymous/configuration links, state-bill eligibility before authentication/private calls, disabled omission, confirmation, dedupe 200, pending/running polling cleanup and transient recovery, success atomic sections, **Cited source**, usage/model display, paginated history and detail selection, stale action, failure/refusal, retry confirmation, and the stronger `outcome_unknown` duplicate-usage warning.

- [x] **Step 2: Run RED tests**

Run: `rtk pnpm vitest run tests/components/bill-enhancement-panel.test.tsx tests/components/bill-detail-page.test.tsx`
Expected: missing component/import.

- [x] **Step 3: Implement enhancement panel and integrate after deterministic contract**

Use effect cleanup and enhancement identity so late polling responses from a previous bill or selected history item cannot update the current panel. Poll only pending/running, retry transient failures, stop on authentication loss, and honor bounded server retry hints. Pass bill jurisdiction into the panel so unsupported bills make no private enhancement request.

- [x] **Step 4: Run GREEN tests**

Run: `rtk pnpm vitest run tests/components/bill-enhancement-panel.test.tsx tests/components/bill-detail-page.test.tsx`
Expected: pass.

### Task 9: Evaluation command, operations documentation, and design synchronization

**Files:**
- Create: `legislation-tracker-backend/apps/legislation/management/commands/evaluate_bill_enhancements.py`
- Create: `legislation-tracker-backend/apps/legislation/tests/fixtures/llm_enhancement/evaluation_cases.json`
- Create: `legislation-tracker-backend/apps/legislation/tests/test_evaluate_bill_enhancements_command.py`
- Modify: `legislation-tracker-backend/docs/PRODUCTION_OPERATIONS.md`
- Modify: `legislation-tracker-backend/.env.example`
- Modify: `legislation-tracker-backend/docker-compose.yml`
- Modify: `docker-compose.production.yml`
- Modify: `docs/superpowers/specs/2026-08-21-user-llm-bill-enhancements-design.md`

**Interfaces:**
- Produces guarded `evaluate_bill_enhancements --execute --case-limit N --max-input-tokens N --max-output-tokens N` and deployment runbook.

- [x] **Step 1: Write failing command/config tests**

```python
with pytest.raises(CommandError, match="--execute"):
    call_command("evaluate_bill_enhancements", case_limit=1)
```

Assert at least 25 versioned federal cases, explicit execution gate, budget summary before calls, hard case/token caps, dedicated environment key, and no raw output/key logging. Assert production compose does not publish the API port directly.

- [x] **Step 2: Run RED tests**

Run: `rtk run ".venv/bin/pytest apps/legislation/tests/test_evaluate_bill_enhancements_command.py apps/ingestion/tests/test_production_compose.py -q"`
Expected: missing command/corpus/config.

- [x] **Step 3: Implement guarded evaluation harness and operational material**

The command writes a local JSON results artifact only when an explicit output path is supplied. The versioned 25-case corpus includes human review labels, a review rubric, multiple sources, truncation, conflicts, cross-references, and prompt-injection-shaped text; artifacts preserve the labels and rubric. Update the design from deprecated `prompt_cache_retention` to explicit-mode/no-breakpoint behavior supported by the current API.

- [x] **Step 4: Run GREEN tests**

Run: `rtk run ".venv/bin/pytest apps/legislation/tests/test_evaluate_bill_enhancements_command.py apps/ingestion/tests/test_production_compose.py -q"`
Expected: pass without a provider call.

### Task 10: Full verification and commit

**Files:** All files above.

- [x] **Step 1: Run backend verification**

Run: `rtk .venv/bin/pytest`
Run changed-file Ruff and Black checks (the repository-wide legacy baseline remains outside this feature diff).
Run: `rtk .venv/bin/python manage.py check`
Run: `rtk .venv/bin/python manage.py makemigrations --check --dry-run`

- [x] **Step 2: Run frontend verification**

Run: `rtk pnpm test`
Run: `rtk pnpm typecheck`
Run: `rtk pnpm lint`
Run: `rtk pnpm exec next build --webpack`
Run: `rtk pnpm test:e2e`

- [x] **Step 3: Inspect secrets and diff**

Run: `rtk grep -R -n -E 'sk-[A-Za-z0-9]{12,}|encrypted_envelope.*print|api_key.*logger' legislation-tracker-backend legislation-tracker-client`
Run: `rtk git diff --check`
Run: `rtk git status --short`

- [x] **Step 4: Commit**

```text
feat(llm): add user-owned bill enhancements
```

**Recorded result:** 314 backend tests passed and 4 skipped; 25 Vitest and 18 Node/API tests passed; all 3 Chromium E2E flows passed; TypeScript, ESLint, changed-file Ruff/Black, Django checks, migration consistency, diff checks, and the production webpack build passed.
