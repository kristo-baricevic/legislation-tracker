# Production Readiness Remediation Design

**Date:** 2026-08-31
**Status:** Implemented
**Scope:** Authentication, dependency integrity, Congress rollover, ingestion and document durability, strict APIs, truthful frontend states, and repository maintenance

## Summary

This remediation closes the ten production-readiness findings from the full project audit. It keeps the browser extension's bearer-token flow intact while moving the web application to secure cookie-backed authentication, makes manual ingestion and document processing durable and bounded, removes Congress 119 assumptions, and makes API and UI failures explicit instead of silently broadening queries or presenting empty data.

GitHub Actions, RSS feeds, and newsletters remain outside this scope by prior product decision.

## Invariants

1. Registration validates email and Django password policy, does not expose a special duplicate-account response, and is protected by endpoint-specific throttles.
2. Web refresh credentials are HttpOnly cookies and never enter browser storage; unsafe cookie-authenticated requests require CSRF. Extension bearer authentication remains supported.
3. Scheduled work resolves the current Congress when it executes using the January 3 boundary in the Washington, DC civil date. Explicit historical Congress arguments still work.
4. A manual bill request is represented by durable database work before the API returns `202 Accepted`; tracking intent survives broker and worker outages.
5. Remote documents are streamed through byte, page, and extracted-text limits. Oversized or malformed documents become observable durable failures and can use the existing replay controls.
6. Invalid filters return `400 Bad Request`; they never become an unfiltered query.
7. A failed frontend request retains previously loaded data, displays the failure, and offers a retry. Failure never masquerades as a legitimate empty result.
8. Production dependency installs are reproducible from a hash-locked file and include a non-vulnerable cryptography release.

## Authentication

Registration uses a DRF serializer with `EmailField`, bounded field lengths, normalized email, and `validate_password`. Creation is transactional and catches the database uniqueness race. The public response is generic and identical for a newly accepted address and an already-existing address; the web client follows registration with a normal session login, so possession of an existing account is not disclosed by the registration endpoint.

Endpoint-specific anonymous throttles protect registration, login, and refresh. Authenticated application throttles remain unchanged.

The web application uses dedicated session endpoints. Access and refresh JWTs are stored only in Secure/HttpOnly/SameSite cookies. A readable CSRF cookie, plus the CSRF bootstrap response for a separately hosted app, supplies the `X-CSRFToken` header on unsafe requests. Cookie authentication enforces CSRF, refresh rotation blacklists the previous refresh token, and logout blacklists the submitted refresh token before clearing cookies. Browser tabs serialize rotation with a named Web Lock, and an invalid stale refresh response cannot clear cookies written by a concurrent successful rotation. Existing token JSON endpoints remain available for the production browser extension.

## Current Congress

`current_congress(on_date=None)` is the only implicit Congress resolver. It converts the supplied instant to `America/New_York`, or uses that zone's current date, and applies the constitutional January 3 transition. `CURRENT_CONGRESS_OVERRIDE` can pin execution for backfills or emergency operation. Scheduled task signatures default to `None`; Beat does not contain Congress arguments. API filter metadata supplies the current value, and the frontend initializes from that metadata rather than a source constant.

## Durable Bill Requests

Manual ingestion validates and canonicalizes a positive Congress and bounded numeric bill number before it creates or reuses an `IngestionWorkItem` and a user-owned pending tracking request in one transaction. If the bill already exists, tracking can be fulfilled immediately. Otherwise the ingestion worker fulfills matching requests after the bill is committed. The response includes the work identifier and a status URL. Replays operate on the same work and fulfill the original tracking request after recovery. A later explicit manual request restores an intentionally removed tracking row, while ordinary background ingestion does not re-follow bills the user unfollowed; successful work is reopened if its bill was subsequently removed.

## Bounded Documents

Downloads use streamed HTTP responses, reject an excessive declared content length early, and enforce the same limit against decoded chunks. Bytes are copied into `SpooledTemporaryFile` while computing the checksum incrementally. PDF parsing enforces a page cap before extracting and a text-character cap during extraction; malformed and empty XML is terminal rather than falling through to tag stripping. Temporary resources are closed for every success and failure path. Existing ingestion failure persistence classifies these terminal validation failures without losing replay visibility.

## Strict APIs and Truthful UI

Bill, contract, vote, representative, topic, and document list query parameters are validated by strict serializers. Invalid integer, choice, date, or boolean values and unknown/typo keys return structured 400 responses instead of silently widening the result set. Detail-action query contracts are validated independently so valid parameters such as related-bill `limit` are preserved.

Contract, vote, topic, tracked-topic, bill-filter metadata, and topic-choice frontend requests have independent loading and error state. A failure does not overwrite successfully loaded data or remove the current-Congress default. Invalid URL/form filters block the request and display their validation error. Each failed section displays a retry control and is covered by behavior-level component tests. Keyed bill-detail instances discard every bill-specific state value during client-side route changes.

## Dependency and Maintenance Policy

Backend production requirements compile to an exact, hash-locked artifact. Docker installs that artifact with hash checking. Pytest uses an isolated in-memory cache and broker rather than depending on a developer's Redis process. Black and Ruff configuration is committed, generated migrations are excluded from formatting churn, and genuine lint findings are resolved. Documentation names the deterministic legal-NLP v2 pipeline as current, documents Node 22 and pnpm, and marks superseded phase plans as historical. Tracked editor and runtime artifacts are removed. A local verification command exercises all supported backend, web, extension, build, lint, and dependency-audit gates without adding CI.

## Verification Record

The completed implementation passed 387 backend tests on isolated SQLite and 390 on PostgreSQL 16, with only the documented Django 6 deprecation warnings. The web application passed 37 behavior-level component tests and 25 API/contract tests, TypeScript, ESLint, dependency audit, and the webpack production build. The extension passed 11 tests plus syntax checks. The live Django/Celery/Next/Chromium E2E suite passed all three persistence flows. Backend and frontend production dependency audits reported no known vulnerabilities, and a whole-diff adversarial review found no remaining high-confidence Critical or Important findings.
