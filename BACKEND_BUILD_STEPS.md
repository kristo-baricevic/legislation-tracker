# Legislation Tracker Backend — Build Steps

A sequential checklist to build out `legislation-tracker-backend`. Each section can be a single PR or a logical chunk of work.

**Status as of 2026-08-31:** phases 1–7 and 10 are implemented. RSS feeds,
newsletters, and GitHub Actions remain intentionally deferred by product decision;
their unchecked boxes are not regressions in the implemented platform.

---

## Phase 1: Scaffold

- [x] **1.1** Create directory `legislation-tracker-backend/` at repo root.
- [x] **1.2** Set up Python env: `python -m venv .venv`, add `.venv/` to `.gitignore` (or use existing project ignore).
- [x] **1.3** Create `requirements/base.txt`: Django 5.x, psycopg[binary], redis, celery, django-environ, django-storages, boto3, djangorestframework, djangorestframework-simplejwt, gunicorn (prod).
- [x] **1.4** Create `requirements/dev.txt`: extends base + pytest, pytest-django, black, ruff, django-extensions, ipython.
- [x] **1.5** Create `requirements/prod.txt`: extends base (no dev tools).
- [x] **1.6** Run `django-admin startproject config .` from inside `legislation-tracker-backend/` (so `config/` is the project package).
- [x] **1.7** Add `config/celery.py` and wire Celery to Django (app = Celery('config'); app.config_from_object; autodiscover_tasks). Update `config/__init__.py` to load the Celery app on Django startup.
- [x] **1.8** Create `.env.example` with: `DATABASE_URL`, `REDIS_URL`, `DJANGO_SECRET_KEY`, `CONGRESS_API_KEY`, `GOVINFO_API_KEY`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_BUCKET_NAME`, `AWS_S3_ENDPOINT_URL` (for MinIO), `DEBUG`, `ALLOWED_HOSTS`.
- [x] **1.9** Configure settings to use `django-environ` for env vars, separate `config.settings.base`, `config.settings.dev`, `config.settings.prod` (or single file with env-based overrides).
- [x] **1.10** Add `config/settings` (or main settings): `DATABASES` from `DATABASE_URL`, `CACHES`/Celery broker from `REDIS_URL`, `INSTALLED_APPS` (rest_framework, simplejwt, etc.), `REST_FRAMEWORK` and JWT config, CORS for `legislation-tracker-client` origin.
- [x] **1.11** Create `docker-compose.yml` in `legislation-tracker-backend/`: services for **postgres** (PostgreSQL 15+), **redis**, **minio** (S3-compatible, create bucket via MC or init script), optional **celery** and **celery-beat** (or run locally). Set env vars and volumes as needed.
- [x] **1.12** Document in README how to run: `docker-compose up -d`, `pip install -r requirements/dev.txt`, `cp .env.example .env`, `python manage.py runserver` (and run celery/beat locally or via compose).

---

## Phase 2: Django apps and models

- [x] **2.1** Create apps: `python manage.py startapp accounts`, same for `legislation`, `congress`, `changelog`, `ingestion`. Move each into `apps/` and add `apps/` to `PYTHONPATH` or set `config.settings` so `INSTALLED_APPS` references `apps.accounts`, etc.
- [x] **2.2** **accounts**: Custom user model (extends AbstractUser, e.g. email as USERNAME_FIELD). Create and run migration. Add `UserPreference` model (user FK, topic FK nullable, state, chamber, last_sent_at). Migration.
- [x] **2.3** **congress**: `Representative` (bioguide_id unique, name, chamber, party, state, district, is_current, created_at, updated_at). Migration.
- [x] **2.4** **legislation**: `Topic` (name, slug unique, description). `Bill` with all fields from plan (jurisdiction, session, bill_number, title, summary, status, processing_status enum, introduced_at, last_action_at, sponsor FK to Representative, latest_contract FK to BillContract nullable — add BillContract in next step and then add this FK in a later migration if needed), source_api_id, raw_text_url, pdf_url, metadata_hash, created_at, updated_at. UniqueConstraint (session, bill_number). Migration.
- [x] **2.5** **legislation**: `BillDocument` (bill FK, version_label, is_active_version, object_storage_key, content_type, file_size_bytes, source_url, raw_text, extracted_text, content_hash, downloaded_at, parsed_at, contract_generated_at, created_at). UniqueConstraint (bill, version_label). Migration.
- [x] **2.6** **legislation**: `BillContract` (bill FK, document FK, schema_version, contract_json JSONB, contract_hash, computed_at). Migration. Then add `Bill.latest_contract` FK to BillContract (migration).
- [x] **2.7** **legislation**: `EvidenceSpan` (bill FK, document FK, contract FK, field_path, start_char, end_char, quoted_text, page_number). Migration.
- [x] **2.8** **legislation**: `BillTopic` (bill FK, topic FK, confidence_score). Migration.
- [x] **2.9** **legislation**: `BillSimilarity` (bill_a FK, bill_b FK, similarity_score, method, computed_at). UniqueConstraint (bill_a, bill_b, method). Add check or app logic: bill_a_id < bill_b_id. Migration.
- [x] **2.10** **congress**: `Vote` (bill FK, chamber, roll_number, vote_date, result, yeas, nays). `VoteRecord` (vote FK, representative FK, position). Migrations.
- [x] **2.11** **changelog**: `ChangeLog` model (bill FK, document FK nullable, contract FK nullable, change_type, old_value JSONB, new_value JSONB, created_at). PostgreSQL migration `changelog.0003_partition_by_created_at` converts it to a monthly UTC RANGE-partitioned parent and preserves ORM writes to the parent table name; SQLite remains a normal table for local development.
- [x] **2.12** **ingestion**: `IngestionState` (jurisdiction, congress, last_polled_at, last_bill_update_seen_at). Migration.
- [x] **2.13** Add indexes per BACKEND_PLAN §7 (Bill, BillDocument, BillContract, ChangeLog, BillTopic, VoteRecord, BillSimilarity). Can be in same migrations or follow-up migration.

---

## Phase 3: Celery and ingestion tasks

- [x] **3.1** `poll_congress` resolves the current Congress at execution time, uses the persisted cursor, discovers bill identifiers, and records durable ingestion work before dispatching it. It is registered with Beat.
- [x] **3.2** `process_bill` fetches and hashes metadata, updates the bill and `ChangeLog`, fulfills matching tracking requests, and schedules version and vote processing. Failures are retried through durable work rather than being lost with a broker message.
- [x] **3.3** `process_bill_versions` creates or updates document versions, maintains the active version, and creates bounded `download_document` work for new or changed documents.
- [x] **3.4** `process_bill_votes` imports votes and vote records, creates associated representatives as needed, and writes vote change-log events. A separate member sync keeps the representative roster complete.
- [x] **3.5** Celery Beat schedules Congress polling, tracked-bill polling, representative synchronization, similarity recomputation, and durable-work recovery without a hard-coded Congress number.
- [x] **3.6** Retries, lease recovery, dead-letter persistence, status inspection, and replay controls are implemented through `IngestionWorkItem` and `IngestionTaskFailure`. Operators can inspect work and failure state through the operational APIs and durable database records.

---

## Phase 4: Document storage (S3)

- [x] **4.1** Configure django-storages + boto3 for S3 (and MinIO via custom endpoint in dev). Settings: `AWS_*`, `AWS_S3_ENDPOINT_URL` for MinIO; optional `USE_LOCAL_DOCUMENT_STORAGE=True` for filesystem under `local_media/` (no MinIO).
- [x] **4.2** Implement `download_document(document_id)`: download from `BillDocument.source_url`, upload with key `bills/{session}/{bill_number}/{version_label}.{ext}`, set `object_storage_key`, `downloaded_at`, `file_size_bytes`, `content_hash`, `extracted_text` (PDF/XML/HTML), `parsed_at`; enqueue deterministic contract generation. Short-circuit if `content_hash` unchanged. Retries on HTTP errors.
- [x] **4.3** `process_bill_versions` already enqueues `download_document` per document (unchanged from Phase 3).

---

## Phase 5: Interpretation layer (BillContract + EvidenceSpan)

- [x] **5.1** Canonical JSON + hash: `apps/legislation/contract_json.py` — `canonical_json_string`, `contract_hash_from_dict` (sorted keys, normalized strings).
- [x] **5.2** `generate_contract(document_id)`: builds deterministic structured `contract_json` from source text (summary, key points, requirements, funding mentions, effective dates); skips if hash unchanged; creates `BillContract`, sets `Bill.latest_contract`, `BillDocument.contract_generated_at`, `ChangeLog(contract_update)`, and exact `EvidenceSpan` citations for source-backed fields; enqueues `update_topics` and `schedule_similarity_for_bill`. See **[legislation-tracker-backend/docs/PHASE_5_CONTRACT.md](legislation-tracker-backend/docs/PHASE_5_CONTRACT.md)**.
- [x] **5.3** Implement the provider-free, versioned deterministic legal-NLP v2 pipeline with validated schema and exact evidence spans. The earlier LLM-oriented **[Phase 5.3 plan](legislation-tracker-backend/docs/PHASE_5_3_PLAN.md)** is retained as historical context only.

---

## Phase 6: Topics and similarity

- [x] **6.1** Implement `update_topics(contract_id)`: keyword-based topic inference from `topic_taxonomy.py` (22 canonical topics); matches against bill title, summary, and contract fields; updates BillTopic with confidence scores; computes topic_set_hash; inserts ChangeLog(topic_update) on change. Seed topics via `python manage.py seed_topics`. Backfill existing contracts via `python manage.py backfill_topics [--sync]`.
- [x] **6.2** Implement `recompute_similarity_batch`: periodic Beat task (hourly); enqueues `schedule_similarity_for_bill` per bill; deterministic topic/text similarity with thresholding; upserts BillSimilarity with `bill_a_id < bill_b_id` ordering.
- [x] **6.3** Wire: `generate_contract` enqueues `update_topics` and `schedule_similarity_for_bill`; Beat runs `recompute_similarity_batch` hourly. Topics included in bill list and detail API responses (`BillTopicSerializer`) and rendered in Next.js frontend (badges with confidence %).

---

## Phase 7: API (DRF)

- [x] **7.1** DRF and Simple JWT are configured. The web app uses secure cookie-backed session routes with CSRF protection; bearer-token routes remain available for the extension.
- [x] **7.2** Bills support paginated list/detail APIs, validated filters, current-Congress metadata, related bills, tracking status, and latest-contract summaries.
- [x] **7.3** Bill documents have list/detail and download/text endpoints. Local stored objects stream from the API; object storage redirects to its generated download URL.
- [x] **7.4** Bill contract history and detail APIs expose versioned contracts and exact evidence spans.
- [x] **7.5** Representatives have list/detail APIs with validated chamber, state, district, and current-member filters.
- [x] **7.6** Votes have list/detail APIs with vote-record pagination and validated filters.
- [x] **7.7** Current-user tracking APIs manage followed bills, topics, and representatives; the consolidated tracking models preserve user intent through ingestion.
- [x] **7.8** CORS and exact trusted-origin settings support the web app; authentication accepts either the protected web session or extension bearer tokens.

---

## Phase 8: RSS and feeds

**Status: intentionally deferred.**

- [ ] **8.1** RSS endpoint: e.g. `GET /rss?topic=climate&state=NY&days=7`. Resolve topic to topic_id; get bill_ids from BillTopic; query ChangeLog where bill_id IN (...) and created_at > cutoff, order by created_at DESC, limit 50; render as RSS XML (title, link, description, pubDate from ChangeLog + Bill).
- [ ] **8.2** Optional: feed for single bill, or for “all changes” (no topic filter).

---

## Phase 9: Newsletters

**Status: intentionally deferred.**

- [ ] **9.1** Query logic: given user, load UserPreference (topics, state, chamber); get bill_ids matching preferences (via BillTopic, Representative state/chamber); query ChangeLog for those bills since user’s last_sent_at (or preference.last_sent_at); group by bill; format as “New bills,” “Status changes,” “Contract updates,” “Votes.”
- [ ] **9.2** Newsletter send: job (Beat or on-demand) that for each user with digest preference runs the query, builds email body, sends (e.g. SendGrid/Mailgun), updates last_sent_at.
- [ ] **9.3** Optional: store rendered newsletter HTML in S3 and link in email; or keep stateless and render on send.

---

## Phase 10: Polish and ops

- [x] **10.1** Required model and queue indexes are present in migrations, including `ChangeLog` indexes on the PostgreSQL partitioned parent and its child partitions.
- [x] **10.2** `/health/live/` supplies liveness; `/health/` verifies database, Redis, and configured storage readiness for orchestration.
- [x] **10.3** Django admin registers bills, documents, contracts, change logs, representatives, votes, users, preferences, and ingestion state for debugging.
- [x] **10.4** Task start/failure logging and durable final-failure records are implemented. `IngestionTaskFailure` and durable work/replay endpoints provide the operational context for failed work.
- [x] **10.5** The repository and backend READMEs document local setup, Docker services, environment variables, Celery worker/Beat, tests, production operations, and architecture.

---

## Summary checklist (high level)

| Phase | Status | Focus                                                                                         |
| ----- | ------ | --------------------------------------------------------------------------------------------- |
| 1     | Complete | Scaffold: project, deps, config, docker-compose, Celery app                                 |
| 2     | Complete | All Django apps and models, migrations, ChangeLog partitioning, indexes                     |
| 3     | Complete | Durable Congress ingestion, document/vote processing, Beat, retries, and replay controls   |
| 4     | Complete | S3/local storage, bounded downloads, extraction, and document access                        |
| 5     | Complete | BillContract + EvidenceSpan + deterministic legal-NLP v2                                    |
| 6     | Complete | Topic inference and similarity recomputation                                                  |
| 7     | Complete | DRF auth, bills, documents, contracts, representatives, votes, and tracking APIs            |
| 8     | Deferred | RSS endpoint from ChangeLog                                                                   |
| 9     | Deferred | Newsletter query and delivery                                                                 |
| 10    | Complete | Indexes, health, admin, logging, and documentation                                            |

If the deferred product work resumes, implement RSS before newsletters so the
same `ChangeLog` query behavior can be exercised in a public, inspectable feed.
