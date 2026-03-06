# Legislation Tracker -- Backend Plan (v2)

Django backend in `legislation-tracker-backend`. PostgreSQL, Celery + Redis, S3.

Incorporates event-driven ChangeLog architecture, structured interpretation layer (BillContract + EvidenceSpan), and hash-based change detection throughout.

---

## 1. Stack

| Layer | Choice |
|-------|--------|
| Framework | Django 5.x |
| DB | PostgreSQL 15+ |
| API | Django REST Framework (or Django Ninja) |
| Auth | JWT via djangorestframework-simplejwt |
| Task queue | Celery + Redis as broker |
| Scheduler | Celery Beat |
| Object storage | AWS S3 (MinIO for local dev) via django-storages + boto3 |
| Cache | Redis (shared with Celery broker, separate DB number) |

---

## 2. Project layout

```
legislation-tracker-backend/
├── config/                 # Django project (settings, urls, wsgi, asgi, celery)
├── apps/
│   ├── accounts/          # User, UserPreference
│   ├── legislation/       # Bill, BillDocument, BillContract, EvidenceSpan, BillTopic, BillSimilarity
│   ├── congress/          # Representative, Vote, VoteRecord
│   ├── changelog/         # ChangeLog (event backbone for RSS + newsletters)
│   └── ingestion/         # Celery tasks, IngestionState
├── manage.py
├── requirements/
│   ├── base.txt
│   ├── dev.txt
│   └── prod.txt
├── docker-compose.yml     # postgres, redis, minio, celery worker, celery beat
└── .env.example
```

---

## 3. Data models

### 3.1 Bill

Canonical metadata only. No interpretation stored here.

| Field | Type | Notes |
|-------|------|-------|
| id | pk | |
| jurisdiction | str | `federal`, `state` |
| session | int | e.g. 119 |
| bill_number | str | e.g. `HR 1234` |
| title | text | |
| summary | text | nullable |
| status | str | e.g. `introduced`, `passed_house` |
| processing_status | enum | `pending`, `processing`, `complete`, `failed` — for UI ingestion state |
| introduced_at | date | |
| last_action_at | datetime | |
| sponsor | FK(Representative) | nullable |
| latest_contract | FK(BillContract) | nullable — denormalized for "latest contract" without ORDER BY |
| source_api_id | str | Congress API bill id |
| raw_text_url | url | nullable |
| pdf_url | url | nullable |
| metadata_hash | str | hash(status, title, summary, last_action_at) for change detection |
| created_at | datetime | auto |
| updated_at | datetime | auto |

**Unique**: `(session, bill_number)`.
**Indexes**: `(updated_at DESC)`, `(metadata_hash)`, `(session, bill_number)`, `(processing_status)`.

---

### 3.2 BillDocument

Original versions and revisions. Enables version diffing.

| Field | Type | Notes |
|-------|------|-------|
| id | pk | |
| bill | FK(Bill) | |
| version_label | str | `introduced`, `amended`, `engrossed`, `enrolled` |
| is_active_version | bool | default False — exactly one True per bill; simplifies "latest" and UI |
| object_storage_key | str | S3 key for PDF/XML |
| content_type | str | MIME type |
| file_size_bytes | int | nullable |
| source_url | url | original GovInfo URL |
| raw_text | text | nullable, or use S3 |
| extracted_text | text | nullable, post-processing |
| content_hash | str | hash of document content |
| downloaded_at | datetime | nullable — when file was stored |
| parsed_at | datetime | nullable — when text was extracted |
| contract_generated_at | datetime | nullable — when BillContract was created |
| created_at | datetime | auto |

**Unique**: `(bill, version_label)`.
**Invariant**: When a new version arrives, set previous `is_active_version=False`, new one `True`.
**Indexes**: `(bill_id)`, `(version_label)`, `(content_hash)`, `(bill_id, is_active_version)`.

**S3 layout**:
```
bills/{session}/{bill_number}/{version_label}.xml
bills/{session}/{bill_number}/{version_label}.pdf
amendments/{session}/{bill_number}/{version_label}.xml
```

---

### 3.3 BillContract (Structured Interpretation Layer)

One structured "plain-language contract" per bill version. This is the core differentiator.

| Field | Type | Notes |
|-------|------|-------|
| id | pk | |
| bill | FK(Bill) | |
| document | FK(BillDocument) | |
| schema_version | str | e.g. `1.0` |
| contract_json | JSONB | normalized structured fields |
| contract_hash | str | hash(contract_json) for change detection |
| computed_at | datetime | |

**contract_json contains**:
- `funding_allocations`
- `obligations`
- `restrictions`
- `agencies_affected`
- `timelines`
- `penalties`
- `beneficiaries`

**Indexes**: `(bill_id)`, `(contract_hash)`, `(bill_id, computed_at DESC)`.

---

### 3.4 EvidenceSpan

Every extracted field traces back to source text. Makes the system auditable.

| Field | Type | Notes |
|-------|------|-------|
| id | pk | |
| bill | FK(Bill) | |
| document | FK(BillDocument) | |
| contract | FK(BillContract) | |
| field_path | str | e.g. `funding_allocations[0].amount` |
| start_char | int | |
| end_char | int | |
| quoted_text | text | |
| page_number | int | nullable |

**Indexes**: `(contract_id)`, `(bill_id)`.

---

### 3.5 Topic + BillTopic

| Field (Topic) | Type | Notes |
|-------|------|-------|
| id | pk | |
| name | str | |
| slug | str | unique |
| description | text | nullable |

| Field (BillTopic) | Type | Notes |
|-------|------|-------|
| id | pk | |
| bill | FK(Bill) | |
| topic | FK(Topic) | |
| confidence_score | float | nullable |

**Indexes (BillTopic)**: `(topic_id)`, `(bill_id)`, `(topic_id, bill_id)`.

---

### 3.6 Representative, Vote, VoteRecord

**Representative**

| Field | Type | Notes |
|-------|------|-------|
| id | pk | |
| bioguide_id | str | unique, stable ID from Congress API |
| name | str | |
| chamber | str | `house`, `senate` |
| party | str | |
| state | str | |
| district | str | nullable (House only) |
| is_current | bool | default True |
| created_at | datetime | auto |
| updated_at | datetime | auto |

**Vote**

| Field | Type | Notes |
|-------|------|-------|
| id | pk | |
| bill | FK(Bill) | |
| chamber | str | |
| roll_number | int | |
| vote_date | datetime | |
| result | str | `passed`, `failed`, etc. |
| yeas | int | |
| nays | int | |

**VoteRecord**

| Field | Type | Notes |
|-------|------|-------|
| id | pk | |
| vote | FK(Vote) | |
| representative | FK(Representative) | |
| position | str | `yes`, `no`, `abstain`, `present` |

**Indexes**: VoteRecord on `(vote_id)`, `(representative_id)`.

---

### 3.7 BillSimilarity

Precomputed, batch-updated.

| Field | Type | Notes |
|-------|------|-------|
| id | pk | |
| bill_a | FK(Bill) | |
| bill_b | FK(Bill) | |
| similarity_score | float | |
| method | str | `embedding`, `title`, etc. |
| computed_at | datetime | |

**Ordering invariant**: Always store with `bill_a_id < bill_b_id`. Application logic (or DB constraint) enforces this so you never store both (A,B) and (B,A).
**Unique**: `(bill_a, bill_b, method)`.
**Indexes**: `(bill_a_id)`, `(bill_b_id)`, `(similarity_score DESC)`.

---

### 3.8 ChangeLog (Event Backbone)

Powers RSS feeds, newsletters, and all "what changed?" queries. Append-only.

| Field | Type | Notes |
|-------|------|-------|
| id | pk | |
| bill | FK(Bill) | |
| document | FK(BillDocument) | nullable — which version triggered this change |
| contract | FK(BillContract) | nullable — which contract, for contract_update |
| change_type | str | `status_update`, `new_version`, `contract_update`, `topic_update`, `vote` |
| old_value | JSONB | nullable |
| new_value | JSONB | |
| created_at | datetime | auto |

**Indexes** (critical — this is the hottest read table):
- `(created_at DESC)`
- `(bill_id)`
- `(change_type)`
- `(created_at DESC, bill_id)` — composite for RSS queries

**Partitioning**: Use monthly `PARTITION BY RANGE (created_at)` from the beginning. ChangeLog grows very fast; early partitioning avoids painful migrations later. In Django this is done via a migration that creates the partitioned table and child partitions with raw SQL (or a library); the ORM still writes to the parent table.

**How RSS works**: query ChangeLog WHERE bill_id IN (topic-filtered set) AND created_at > cutoff, ORDER BY created_at DESC. No recomputation.

**How newsletters work**: same query scoped to user preferences (topics, state, chamber) since last_sent_at.

---

### 3.9 User + UserPreference

**User**: extends Django `AbstractUser`. Email-based login.

**UserPreference**

| Field | Type | Notes |
|-------|------|-------|
| id | pk | |
| user | FK(User) | |
| topic | FK(Topic) | nullable |
| state | str | nullable |
| chamber | str | nullable |
| last_sent_at | datetime | nullable, for newsletter tracking |

Multiple rows per user (one per preference dimension).

---

### 3.10 IngestionState

Tracks polling cursors. Prevents re-fetching everything.

| Field | Type | Notes |
|-------|------|-------|
| id | pk | |
| jurisdiction | str | `federal` |
| congress | int | e.g. 119 |
| last_polled_at | datetime | |
| last_bill_update_seen_at | datetime | high-water mark from API |

---

## 4. Celery Task Graph

Fan-out pipeline. Each task is idempotent. Hash-based short-circuiting at every level.

```
poll_congress (Beat, every 5-10 min)
    |
    v
process_bill (per bill, enqueued)
    |
    +---> process_bill_versions
    |         |
    |         v
    |     download_document (per version)
    |         |
    |         v
    |     generate_contract
    |         |
    |         +---> update_topics
    |         +---> [similarity_queue]
    |
    +---> process_bill_votes
```

### Task details

| Task | What it does | Short-circuit |
|------|-------------|---------------|
| `poll_congress` | Fetch updated bill IDs from Congress API using `fromDateTime`. Enqueue `process_bill` for each. Update `IngestionState.last_bill_update_seen_at`. | Only fetches since last cursor. |
| `process_bill` | Set Bill.processing_status = `processing`. Fetch metadata. Compute metadata_hash. If unchanged, exit (set `complete`). If changed, update Bill, insert ChangeLog, enqueue `process_bill_versions` + `process_bill_votes`. On failure set `failed`. | metadata_hash comparison. |
| `process_bill_versions` | Fetch text version list. For each new version: create BillDocument; if it's the new active version, set previous docs' `is_active_version=False`, this one `True`. Enqueue `download_document`. | version_label + source URL check. |
| `download_document` | Set `downloaded_at` when stored; set `parsed_at` when text extracted. Upload to S3. Compute content_hash. If unchanged, exit. Enqueue `generate_contract`. | content_hash comparison. |
| `generate_contract` | Parse extracted text. Produce contract_json (canonical serialization) + EvidenceSpans. Compute contract_hash. If unchanged, exit. Store BillContract; set Bill.latest_contract, BillDocument.contract_generated_at. Insert ChangeLog(document=..., contract=...), enqueue `update_topics` + add to similarity queue. | contract_hash comparison. |
| `update_topics` | Generate topic labels from contract. Compute topic_set_hash. If changed, update BillTopic, insert ChangeLog. | topic_set_hash comparison. |
| `recompute_similarity_batch` | Periodic (Beat). Batch-process queued bill_ids. Compute embeddings, update BillSimilarity. | Batched, not per-bill. |
| `process_bill_votes` | Fetch vote references. If new vote, insert Vote + VoteRecords + ChangeLog. | Check if vote already stored. |
| `fetch_congress_members` | Periodic (Beat, daily). Upsert Representatives from Congress API. | bioguide_id as natural key. |

### Design principles

- **Polling is cheap**: `poll_congress` does zero heavy work.
- **Heavy work is queued**: NLP, S3 uploads, similarity all happen in background tasks.
- **Hash short-circuiting everywhere**: no redundant ChangeLog entries, no newsletter spam.
- **Idempotent**: every task can be safely retried.
- **Fan-out**: one failure doesn't block siblings.
- **Version handoff**: When a new BillDocument is set as current, set previous `is_active_version=False`, new `True`. When a new BillContract is stored, set `Bill.latest_contract` and `BillDocument.contract_generated_at`.

### Retry and failure handling

Tasks assume idempotency, but you still need explicit retry and dead-letter behavior so one malformed PDF or NLP failure doesn't cause infinite loops.

| Concern | Strategy |
|--------|----------|
| **max_retries** | Set per task: e.g. 3 for `download_document`, 2 for `generate_contract`, 1 for `process_bill`. |
| **exponential backoff** | Use Celery `countdown` or `retry_backoff=True` so retries don't hammer Congress/GovInfo. |
| **dead-letter logging** | On final failure: log task_id, bill_id/document_id, exception, and payload to a table or log stream. Do not re-queue. |
| **High-risk tasks** | GovInfo download (network, large files), NLP (`generate_contract`), similarity (compute). These get retries + backoff + dead-letter. |

Without this, one bad document can spin forever or hide in the queue.

---

## 5. Data source separation

**Congress API** = structured metadata layer:
- Bill search + detail + text versions + actions + cosponsors + vote references + amendments + members.

**GovInfo API** = document source of truth:
- Official PDFs, XML, MODS. Downloaded and stored in S3.

The backend owns both API keys. The Next.js client never calls Congress/GovInfo directly.

---

## 6. S3 / Object Storage

| Content | Source | Format |
|---------|--------|--------|
| Bill full text | GovInfo | XML, PDF |
| Amendment text | GovInfo | XML |
| Extracted text | Processing pipeline | plain text |
| Future embeddings | Similarity pipeline | parquet/binary |

**Infrastructure**:
- Production: AWS S3 bucket (`legislation-tracker-documents`).
- Local dev: MinIO in docker-compose (S3-compatible).
- Python: `django-storages` + `boto3`.

---

## 7. Index strategy summary

| Table | Key indexes |
|-------|-------------|
| Bill | `(session, bill_number)` unique, `(updated_at DESC)`, `(metadata_hash)`, `(processing_status)` |
| BillDocument | `(bill_id)`, `(version_label)`, `(content_hash)`, `(bill_id, is_active_version)` |
| BillContract | `(bill_id)`, `(contract_hash)`, `(bill_id, computed_at DESC)` |
| ChangeLog | `(created_at DESC)`, `(bill_id)`, `(change_type)`, `(created_at DESC, bill_id)` composite; **partitioned by RANGE (created_at) monthly from day one** |
| BillTopic | `(topic_id)`, `(bill_id)`, `(topic_id, bill_id)` |
| VoteRecord | `(vote_id)`, `(representative_id)` |
| BillSimilarity | `(bill_a_id)`, `(bill_b_id)`, `(similarity_score DESC)`; enforce `bill_a_id < bill_b_id` |

ChangeLog is the hottest read table. Partition from the beginning to avoid migration pain.

---

## 8. Critical design decisions

1. **Bills and interpretations are separate tables.** Bill stores canonical metadata. BillContract stores structured interpretation.
2. **Every structured field traces to an EvidenceSpan.** The system is auditable.
3. **Versioning is explicit via BillDocument.** You can diff versions. `is_active_version` marks the current one; denormalized `Bill.latest_contract` avoids repeated "latest contract" queries.
4. **RSS and newsletters are driven entirely by ChangeLog.** No recomputation at read time.
5. **Hash-based short-circuiting at every pipeline stage.** Work only happens when data meaningfully changes.
6. **Polling is cheap, heavy work is queued.** The ingestion scheduler does minimal work; everything else fans out.
7. **ChangeLog is partitioned from day one.** Monthly by `created_at` so it scales without a painful migration later.
8. **BillSimilarity stores ordered pairs only.** `bill_a_id < bill_b_id` everywhere to avoid duplicate (A,B) and (B,A).

---

## 8b. contract_json schema stability (critical risk)

The hardest part of this system is not ingestion — it's keeping **contract_json** stable enough that:

- Changes are meaningful (real content changes, not formatting).
- Hashing is reliable (same logical content → same hash).
- Minor formatting or ordering differences don't flood ChangeLog with noise.

**Requirements before hashing or storing contract_json:**

| Requirement | Why |
|-------------|-----|
| **Deterministic key ordering** | Serialize JSON with sorted keys (e.g. `json.dumps(..., sort_keys=True)`). Otherwise `{"a":1,"b":2}` and `{"b":2,"a":1}` hash differently. |
| **Deterministic array ordering** | Define a canonical order for arrays (e.g. by id, or by a sort key). Don't rely on extraction order. |
| **Normalized numeric formats** | Store numbers in a canonical form (e.g. string representation with fixed precision, or integers for cents). Avoid float noise. |
| **Stripped whitespace** | Normalize strings (strip, collapse internal spaces) before hashing. |
| **Canonical serialization** | One function that takes the contract dict and returns the exact string used for `contract_hash`. Use it everywhere. |

Without this, most structured-interpretation systems degenerate into noisy change streams. Schema stability is where to invest design time early.

---

## 9. Secrets (backend .env only)

```
CONGRESS_API_KEY=...
GOVINFO_API_KEY=...
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_S3_BUCKET_NAME=legislation-tracker-documents
AWS_S3_ENDPOINT_URL=http://minio:9000  # local dev only
DATABASE_URL=postgres://...
REDIS_URL=redis://...
DJANGO_SECRET_KEY=...
```

---

## 10. Implementation order

1. **Scaffold**: Django project, docker-compose (postgres, redis, minio), settings, .env.
2. **Core models**: Bill (with processing_status, latest_contract), BillDocument (is_active_version, downloaded_at, parsed_at, contract_generated_at), Representative, Topic, BillTopic, ChangeLog (document, contract FKs), User, UserPreference, IngestionState. **ChangeLog**: create as partitioned table (monthly by created_at) from the start.
3. **Ingestion pipeline**: Celery + Beat, `poll_congress`, `process_bill`, `process_bill_versions`, `process_bill_votes`.
4. **Document storage**: `download_document` task, S3 upload, BillDocument content_hash.
5. **Interpretation layer**: BillContract, EvidenceSpan, `generate_contract` task (stub first, NLP later).
6. **Topics + similarity**: `update_topics`, `recompute_similarity_batch`, BillSimilarity.
7. **API**: DRF endpoints for bills, documents, contracts, representatives, votes. JWT auth. Pre-signed S3 URLs.
8. **RSS + feeds**: ChangeLog-powered RSS endpoint (`/rss?topic=X&state=Y`).
9. **Newsletters**: Query ChangeLog by user preferences since last_sent_at.
10. **Indexes + optimization**: Composite indexes, ChangeLog partitioning when needed.
