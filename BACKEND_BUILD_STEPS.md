# Legislation Tracker Backend — Build Steps

A sequential checklist to build out `legislation-tracker-backend`. Each section can be a single PR or a logical chunk of work.

---

## Phase 1: Scaffold

- [ ] **1.1** Create directory `legislation-tracker-backend/` at repo root.
- [ ] **1.2** Set up Python env: `python -m venv .venv`, add `.venv/` to `.gitignore` (or use existing project ignore).
- [ ] **1.3** Create `requirements/base.txt`: Django 5.x, psycopg[binary], redis, celery, django-environ, django-storages, boto3, djangorestframework, djangorestframework-simplejwt, gunicorn (prod).
- [ ] **1.4** Create `requirements/dev.txt`: extends base + pytest, pytest-django, black, ruff, django-extensions, ipython.
- [ ] **1.5** Create `requirements/prod.txt`: extends base (no dev tools).
- [ ] **1.6** Run `django-admin startproject config .` from inside `legislation-tracker-backend/` (so `config/` is the project package).
- [ ] **1.7** Add `config/celery.py` and wire Celery to Django (app = Celery('config'); app.config_from_object; autodiscover_tasks). Update `config/__init__.py` to load the Celery app on Django startup.
- [ ] **1.8** Create `.env.example` with: `DATABASE_URL`, `REDIS_URL`, `DJANGO_SECRET_KEY`, `CONGRESS_API_KEY`, `GOVINFO_API_KEY`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_BUCKET_NAME`, `AWS_S3_ENDPOINT_URL` (for MinIO), `DEBUG`, `ALLOWED_HOSTS`.
- [ ] **1.9** Configure settings to use `django-environ` for env vars, separate `config.settings.base`, `config.settings.dev`, `config.settings.prod` (or single file with env-based overrides).
- [ ] **1.10** Add `config/settings` (or main settings): `DATABASES` from `DATABASE_URL`, `CACHES`/Celery broker from `REDIS_URL`, `INSTALLED_APPS` (rest_framework, simplejwt, etc.), `REST_FRAMEWORK` and JWT config, CORS for `legislation-tracker-client` origin.
- [ ] **1.11** Create `docker-compose.yml` in `legislation-tracker-backend/`: services for **postgres** (PostgreSQL 15+), **redis**, **minio** (S3-compatible, create bucket via MC or init script), optional **celery** and **celery-beat** (or run locally). Set env vars and volumes as needed.
- [ ] **1.12** Document in README how to run: `docker-compose up -d`, `pip install -r requirements/dev.txt`, `cp .env.example .env`, `python manage.py runserver` (and run celery/beat locally or via compose).

---

## Phase 2: Django apps and models

- [ ] **2.1** Create apps: `python manage.py startapp accounts`, same for `legislation`, `congress`, `changelog`, `ingestion`. Move each into `apps/` and add `apps/` to `PYTHONPATH` or set `config.settings` so `INSTALLED_APPS` references `apps.accounts`, etc.
- [ ] **2.2** **accounts**: Custom user model (extends AbstractUser, e.g. email as USERNAME_FIELD). Create and run migration. Add `UserPreference` model (user FK, topic FK nullable, state, chamber, last_sent_at). Migration.
- [ ] **2.3** **congress**: `Representative` (bioguide_id unique, name, chamber, party, state, district, is_current, created_at, updated_at). Migration.
- [ ] **2.4** **legislation**: `Topic` (name, slug unique, description). `Bill` with all fields from plan (jurisdiction, session, bill_number, title, summary, status, processing_status enum, introduced_at, last_action_at, sponsor FK to Representative, latest_contract FK to BillContract nullable — add BillContract in next step and then add this FK in a later migration if needed), source_api_id, raw_text_url, pdf_url, metadata_hash, created_at, updated_at. UniqueConstraint (session, bill_number). Migration.
- [ ] **2.5** **legislation**: `BillDocument` (bill FK, version_label, is_active_version, object_storage_key, content_type, file_size_bytes, source_url, raw_text, extracted_text, content_hash, downloaded_at, parsed_at, contract_generated_at, created_at). UniqueConstraint (bill, version_label). Migration.
- [ ] **2.6** **legislation**: `BillContract` (bill FK, document FK, schema_version, contract_json JSONB, contract_hash, computed_at). Migration. Then add `Bill.latest_contract` FK to BillContract (migration).
- [ ] **2.7** **legislation**: `EvidenceSpan` (bill FK, document FK, contract FK, field_path, start_char, end_char, quoted_text, page_number). Migration.
- [ ] **2.8** **legislation**: `BillTopic` (bill FK, topic FK, confidence_score). Migration.
- [ ] **2.9** **legislation**: `BillSimilarity` (bill_a FK, bill_b FK, similarity_score, method, computed_at). UniqueConstraint (bill_a, bill_b, method). Add check or app logic: bill_a_id < bill_b_id. Migration.
- [ ] **2.10** **congress**: `Vote` (bill FK, chamber, roll_number, vote_date, result, yeas, nays). `VoteRecord` (vote FK, representative FK, position). Migrations.
- [ ] **2.11** **changelog**: `ChangeLog` model (bill FK, document FK nullable, contract FK nullable, change_type, old_value JSONB, new_value JSONB, created_at). Create migration that creates a **partitioned table** by RANGE (created_at) with initial monthly partitions (raw SQL in migration). Ensure Django ORM writes to parent table name.
- [ ] **2.12** **ingestion**: `IngestionState` (jurisdiction, congress, last_polled_at, last_bill_update_seen_at). Migration.
- [ ] **2.13** Add indexes per BACKEND_PLAN §7 (Bill, BillDocument, BillContract, ChangeLog, BillTopic, VoteRecord, BillSimilarity). Can be in same migrations or follow-up migration.

---

## Phase 3: Celery and ingestion tasks

- [ ] **3.1** In `ingestion/tasks.py`, define `poll_congress`: call Congress API with `fromDateTime=IngestionState.last_bill_update_seen_at`, get list of bill identifiers, update IngestionState, enqueue `process_bill` for each. Register with Beat (e.g. every 5–10 min).
- [ ] **3.2** Define `process_bill(bill_key)`: fetch bill metadata from Congress API, compute metadata_hash, get or create Bill; if hash unchanged set processing_status=complete and return; else update Bill, set processing_status=processing, insert ChangeLog(status_update), enqueue `process_bill_versions` and `process_bill_votes`. On exception set processing_status=failed. Configure retries + backoff.
- [ ] **3.3** Define `process_bill_versions(bill_id)`: fetch bill text versions from Congress API; for each version, get or create BillDocument; if new “current” version, set previous is_active_version=False, new one True; enqueue `download_document` for new/changed docs.
- [ ] **3.4** Define `process_bill_votes(bill_id)`: fetch vote refs from Congress API; for each vote not yet stored, create Vote and VoteRecords (and Representatives if needed), insert ChangeLog(vote).
- [ ] **3.5** Configure Celery Beat schedule in `config/celery.py` (or dedicated config): poll_congress, optional fetch_congress_members daily.
- [ ] **3.6** Add retry + dead-letter behavior: max_retries, retry_backoff, on_failure log to table or structured log (task_id, bill_id, exception).

---

## Phase 4: Document storage (S3)

- [ ] **4.1** Configure django-storages + boto3 for S3 (and MinIO via custom endpoint in dev). Settings: AWS_ACCESS_KEY_ID, SECRET, BUCKET, optional ENDPOINT_URL for MinIO.
- [ ] **4.2** Implement `download_document(document_id)`: resolve GovInfo URL for document (from BillDocument.source_url or Congress + GovInfo lookup), download file, upload to S3 with key `bills/{session}/{bill_number}/{version_label}.{ext}`, set BillDocument.object_storage_key, downloaded_at, file_size_bytes, content_hash; extract text if PDF/XML and set extracted_text, parsed_at; enqueue `generate_contract`. Short-circuit if content_hash matches existing. Retries + backoff.
- [ ] **4.3** Call `download_document` from `process_bill_versions` when a new or changed version is detected (or from a separate task enqueued there).

---

## Phase 5: Interpretation layer (BillContract + EvidenceSpan)

- [ ] **5.1** Implement canonical JSON serialization for contract_json: one function that takes a dict, sorts keys, normalizes numbers/whitespace, returns string for hashing. Use it everywhere before computing contract_hash.
- [ ] **5.2** Implement `generate_contract(document_id)` (stub first): load BillDocument; if no extracted_text skip or use placeholder; build minimal contract_json (e.g. empty structure or title-only); compute contract_hash; if same as existing BillContract for this document, exit; else create/update BillContract, set Bill.latest_contract and BillDocument.contract_generated_at, insert ChangeLog(contract_update, document=..., contract=...), enqueue `update_topics` and add bill_id to similarity queue. Create EvidenceSpan rows for each top-level field (stub: one span per field path).
- [ ] **5.3** (Later) Replace stub with real NLP extraction producing contract_json and EvidenceSpans.

---

## Phase 6: Topics and similarity

- [ ] **6.1** Implement `update_topics(contract_id)`: from BillContract generate or infer topic labels; get/create Topic rows; update BillTopic; compute topic_set_hash; if changed insert ChangeLog(topic_update).
- [ ] **6.2** Implement `recompute_similarity_batch`: periodic Beat task; drain similarity queue (or query bills needing similarity); compute pairs with bill_a_id < bill_b_id; upsert BillSimilarity. Use simple method first (e.g. title similarity); add embedding method later.
- [ ] **6.3** Wire: `generate_contract` enqueues `update_topics` and pushes bill_id to similarity queue; Beat runs `recompute_similarity_batch` on schedule.

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

| Phase | Focus |
|-------|--------|
| 1 | Scaffold: project, deps, config, docker-compose, celery app |
| 2 | All Django apps and models, migrations, ChangeLog partitioning, indexes |
| 3 | Celery: poll_congress, process_bill, process_bill_versions, process_bill_votes, Beat, retries |
| 4 | S3 + download_document task |
| 5 | BillContract + EvidenceSpan + generate_contract (stub then real) |
| 6 | update_topics, recompute_similarity_batch |
| 7 | DRF API: auth, bills, documents, contracts, reps, votes, preferences, pre-signed URLs |
| 8 | RSS endpoint from ChangeLog |
| 9 | Newsletter query + send job |
| 10 | Indexes, health, admin, logging, README |

You can implement in order; phases 4–6 can overlap with 7 once models and tasks exist.
