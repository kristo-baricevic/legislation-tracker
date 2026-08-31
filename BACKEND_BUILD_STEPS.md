# Legislation Tracker Backend — Build Steps

A sequential checklist to build out `legislation-tracker-backend`. Each section can be a single PR or a logical chunk of work.

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

- [ ] **3.1** In `ingestion/tasks.py`, define `poll_congress`: call Congress API with `fromDateTime=IngestionState.last_bill_update_seen_at`, get list of bill identifiers, update IngestionState, enqueue `process_bill` for each. Register with Beat (e.g. every 5–10 min).
- [ ] **3.2** Define `process_bill(bill_key)`: fetch bill metadata from Congress API, compute metadata_hash, get or create Bill; if hash unchanged set processing_status=complete and return; else update Bill, set processing_status=processing, insert ChangeLog(status_update), enqueue `process_bill_versions` and `process_bill_votes`. On exception set processing_status=failed. Configure retries + backoff.
- [ ] **3.3** Define `process_bill_versions(bill_id)`: fetch bill text versions from Congress API; for each version, get or create BillDocument; if new “current” version, set previous is_active_version=False, new one True; enqueue `download_document` for new/changed docs.
- [ ] **3.4** Define `process_bill_votes(bill_id)`: fetch vote refs from Congress API; for each vote not yet stored, create Vote and VoteRecords (and Representatives if needed), insert ChangeLog(vote).
- [ ] **3.5** Configure Celery Beat schedule in `config/celery.py` (or dedicated config): poll_congress, optional fetch_congress_members daily.
- [ ] **3.6** Add retry + dead-letter behavior: max_retries, retry_backoff, on_failure log to table or structured log (task_id, bill_id, exception). **Operational:** On repeated failures, check the `IngestionTaskFailure` table (or structured logs) for task_id, bill_id, task_name, error_message.

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

- [ ] **7.1** Install and configure DRF + Simple JWT. Add URL routes for `/api/auth/` (login, refresh, register if desired).
- [ ] **7.2** Bills: list (filter by session, topic, status; pagination), retrieve by id or (session, bill_number). Include latest_contract summary if present.
- [ ] **7.3** Bill documents: list for a bill, retrieve one; endpoint to get **pre-signed S3 URL** for document download (object_storage_key).
- [ ] **7.4** Bill contracts: list for a bill, retrieve one; optional nested EvidenceSpans.
- [ ] **7.5** Representatives: list (filter by chamber, state), retrieve by id or bioguide_id.
- [ ] **7.6** Votes: list for a bill, retrieve one with VoteRecords.
- [ ] **7.7** User preferences: CRUD for current user’s UserPreference (topics, state, chamber).
- [ ] **7.8** CORS: allow legislation-tracker-client origin. Auth: JWT in header or cookie as chosen.

---

## Phase 8: RSS and feeds

- [ ] **8.1** RSS endpoint: e.g. `GET /rss?topic=climate&state=NY&days=7`. Resolve topic to topic_id; get bill_ids from BillTopic; query ChangeLog where bill_id IN (...) and created_at > cutoff, order by created_at DESC, limit 50; render as RSS XML (title, link, description, pubDate from ChangeLog + Bill).
- [ ] **8.2** Optional: feed for single bill, or for “all changes” (no topic filter).

---

## Phase 9: Newsletters

- [ ] **9.1** Query logic: given user, load UserPreference (topics, state, chamber); get bill_ids matching preferences (via BillTopic, Representative state/chamber); query ChangeLog for those bills since user’s last_sent_at (or preference.last_sent_at); group by bill; format as “New bills,” “Status changes,” “Contract updates,” “Votes.”
- [ ] **9.2** Newsletter send: job (Beat or on-demand) that for each user with digest preference runs the query, builds email body, sends (e.g. SendGrid/Mailgun), updates last_sent_at.
- [ ] **9.3** Optional: store rendered newsletter HTML in S3 and link in email; or keep stateless and render on send.

---

## Phase 10: Polish and ops

- [ ] **10.1** Add remaining indexes (composite, etc.) from BACKEND_PLAN §7 if not already in migrations.
- [ ] **10.2** Health checks: `/health` (DB + Redis + optional S3 head). Use for load balancer or orchestration.
- [ ] **10.3** Admin: register Bill, BillDocument, BillContract, ChangeLog, Representative, Vote, User, UserPreference, IngestionState in Django admin for debugging.
- [ ] **10.4** Logging: structured logs for task start/fail (task_id, bill_id, document_id). Optional dead-letter table for final failures.
- [ ] **10.5** README: how to run locally (docker-compose, venv, env vars), how to run Celery worker and Beat, how to run tests, link to BACKEND_PLAN and ARCHITECTURE_ELI5.

---

## Summary checklist (high level)

| Phase | Focus                                                                                         |
| ----- | --------------------------------------------------------------------------------------------- |
| 1     | Scaffold: project, deps, config, docker-compose, celery app                                   |
| 2     | All Django apps and models, migrations, ChangeLog partitioning, indexes                       |
| 3     | Celery: poll_congress, process_bill, process_bill_versions, process_bill_votes, Beat, retries |
| 4     | S3 + download_document task                                                                   |
| 5     | BillContract + EvidenceSpan + deterministic legal-NLP v2                                   |
| 6     | update_topics, recompute_similarity_batch                                                     |
| 7     | DRF API: auth, bills, documents, contracts, reps, votes, preferences, pre-signed URLs         |
| 8     | RSS endpoint from ChangeLog                                                                   |
| 9     | Newsletter query + send job                                                                   |
| 10    | Indexes, health, admin, logging, README                                                       |

You can implement in order; phases 4–6 can overlap with 7 once models and tasks exist.
