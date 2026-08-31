# Production Readiness Remediation Implementation Plan

**Status:** Implemented and verified

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:test-driven-development` for each behavior change and `superpowers:verification-before-completion` before completion.

**Goal:** Implement every approved production-readiness fix while preserving the extension token contract and intentionally excluding GitHub Actions, RSS, and newsletters.

**Architecture:** Harden the existing Django/DRF boundary, retain durable database work as the ingestion source of truth, and make the Next application consume server-provided configuration and secure session cookies. Changes are organized by independent ownership seams and integrated through the repository-wide verification command.

**Spec:** `docs/superpowers/specs/2026-08-31-production-readiness-remediation-design.md`

### Task 1: Registration, throttling, and web session security

**Files:**
- Modify: `legislation-tracker-backend/apps/accounts/views.py`
- Create: `legislation-tracker-backend/apps/accounts/serializers.py`
- Create: `legislation-tracker-backend/apps/accounts/authentication.py`
- Create: `legislation-tracker-backend/apps/accounts/throttles.py`
- Modify: `legislation-tracker-backend/config/settings/base.py`
- Modify: `legislation-tracker-backend/config/settings/prod.py`
- Modify: `legislation-tracker-backend/config/urls.py`
- Modify/create: account API tests
- Modify: frontend auth API/client/components and tests

- [x] Add failing API tests for malformed/oversized registration, Django password validation, duplicate/race behavior, and scoped throttles.
- [x] Add failing session tests for HttpOnly cookie issuance, CSRF rejection, refresh rotation/blacklisting, logout revocation, and unchanged bearer auth.
- [x] Implement serializers, throttles, cookie JWT authentication, session endpoints, cookie/CORS/CSRF/CSP settings, and token blacklisting.
- [x] Add failing frontend tests proving no JWT is written to localStorage and auth/session/logout uses cookies plus CSRF.
- [x] Migrate the web client and auth components; keep extension code unchanged.
- [x] Run focused backend and frontend auth tests.

### Task 2: Dynamic Congress rollover

**Files:**
- Create: `legislation-tracker-backend/apps/congress/current.py`
- Modify: ingestion tasks/views, Celery Beat, and API filter metadata
- Modify: dashboard and bills frontend filters
- Add focused backend and component tests

- [x] Write failing boundary/override/task/default tests for 2027 and 2029 January 2/3.
- [x] Implement the single resolver and make scheduled task parameters optional.
- [x] Remove production `119` constants while retaining explicit historical task support.
- [x] Initialize frontend filters from API metadata and test rollover behavior.
- [x] Run focused backend/frontend tests and a repository search for production `119` defaults.

### Task 3: Durable manual ingestion and tracking intent

**Files:**
- Modify: ingestion models, migration, work queue, tasks, views, URLs/serializers
- Add ingestion API, queue, replay, and worker tests

- [x] Write failing tests proving `202` is returned only after work and tracking intent persist, broker failure cannot lose work, duplicate requests dedupe, existing bills track immediately, and replay fulfills the request.
- [x] Add the pending tracking request model and migration.
- [x] Enqueue deterministic manual work transactionally and expose a work-status endpoint.
- [x] Fulfill matching requests after bill persistence and retain intent across failures.
- [x] Run focused ingestion tests and migration checks.

### Task 4: Bounded document download and extraction

**Files:**
- Modify: ingestion HTTP/document helpers and settings
- Modify/create: document ingestion tests

- [x] Write failing tests for missing/excess content length, decoded chunk overflow, excessive PDF pages, extracted-text overflow, timeout, malformed files, and resource cleanup.
- [x] Stream into `SpooledTemporaryFile`, hash incrementally, and enforce configurable byte/page/text limits.
- [x] Map bounded validation failures into durable failure/dead-letter behavior compatible with replay.
- [x] Run focused document and ingestion-failure tests.

### Task 5: Strict query validation and storage-independent download tests

**Files:**
- Modify: legislation/congress view filters and serializers
- Modify: public document tests

- [x] Add failing negative tests for invalid bill, Congress/session, contract, vote, date, boolean, chamber, and unknown filters.
- [x] Add strict typed query serializers and return structured `400` responses.
- [x] Replace filesystem-dependent stored-object assertions with a fake storage and isolated media root.
- [x] Run the affected API/test modules in a clean temporary media environment.

### Task 6: Truthful frontend loading, error, and retry states

**Files:**
- Modify: bill detail, topic, tracked-topic hooks/components/pages
- Modify/create: component tests

- [x] Add failing tests where contract, vote, topic, and tracked-topic calls reject after data exists.
- [x] Add independent loading/error state without replacing existing data on failure.
- [x] Render section-specific error copy and retry controls; keep empty states only for successful empty responses.
- [x] Run component tests, typecheck, and lint.

### Task 7: Reproducible backend dependencies

**Files:**
- Modify: `legislation-tracker-backend/requirements/base.txt`
- Create: exact hash-locked production requirements
- Modify: backend Dockerfile/deployment docs

- [x] Raise cryptography to the audited safe major range.
- [x] Compile exact transitive production dependencies with hashes using the repository-supported compiler.
- [x] Make production image installation require the lock and hashes.
- [x] Rebuild/install in a clean environment and run dependency audit plus focused encryption tests.

### Task 8: Formatting, cleanup, documentation, and local verification gate

**Files:**
- Create/modify: backend `pyproject.toml`
- Modify: README and active architecture/phase docs
- Remove: tracked `.DS_Store`, `Untitled`, and `celerybeat-schedule.db`
- Create: local repository check script/command

- [x] Configure Black/Ruff for Django and exclude historical migrations from churn.
- [x] Format backend and resolve actionable Ruff findings.
- [x] Update Node 22/pnpm instructions and deterministic NLP v2 documentation; mark superseded phase plans historical.
- [x] Remove tracked local/runtime artifacts.
- [x] Add a single local check that runs backend tests/lint/audit, frontend tests/typecheck/lint/audit/build, and extension tests/syntax checks.

### Task 9: Repository-wide verification

- [x] Run backend unit/integration tests against clean SQLite and PostgreSQL.
- [x] Run `makemigrations --check`, Django system checks, Black check, Ruff, and backend dependency audit.
- [x] Run frontend component tests, typecheck, lint, production webpack build, and dependency audit.
- [x] Run extension tests and JavaScript syntax checks.
- [x] Run E2E coverage supported by the local environment.
- [x] Inspect the complete diff for secrets, stale hard-coding, ignored errors, migrations, and unrelated changes.
- [x] Fix every regression and repeat the entire matrix before reporting completion.
