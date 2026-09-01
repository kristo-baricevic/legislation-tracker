# Production Operations

This backend needs four production processes/services:

1. **PostgreSQL** for durable application data.
2. **Redis** for Celery broker/result backend and Django cache.
3. **Django web** for the API.
4. **Celery worker + Celery Beat** for ingestion, document processing, contracts, and scheduled refreshes.

The Next.js client is deployed separately and points at the Django API with `NEXT_PUBLIC_API_URL`.

## Required Environment

Set these for the Django web process, Celery worker, and Celery Beat:

```bash
DJANGO_SETTINGS_MODULE=config.settings.prod
DEBUG=False
DJANGO_SECRET_KEY=<long-random-secret>
ALLOWED_HOSTS=api.example.com
DATABASE_URL=postgres://...
REDIS_URL=redis://...
CONGRESS_API_KEY=<congress-api-key>
CORS_ALLOWED_ORIGINS=https://app.example.com
CSRF_TRUSTED_ORIGINS=https://app.example.com
AUTH_COOKIE_SAMESITE=Lax
```

Leave `CURRENT_CONGRESS_OVERRIDE` unset during normal operation. Polling,
representative synchronization, similarity recomputation, and UI defaults
resolve the active Congress when work executes, using the January 3 boundary
in Washington, DC. Set the override identically on the API, worker, and Beat
only for an intentional backfill or emergency pin, then remove it.

The web application uses HttpOnly JWT cookies with CSRF protection and refresh
rotation/blacklisting. The browser extension continues to use the separate
Bearer-token endpoints. Use `AUTH_COOKIE_SAMESITE=None` only when the app and
API are genuinely cross-site; it requires HTTPS and exact CORS/CSRF origins.
The CSRF bootstrap endpoint also returns the token in JSON so a separately
hosted app can retain it in memory and send it as `X-CSRFToken`; the JWTs remain
HttpOnly. Browser tabs serialize refresh rotation through the Web Locks API.

For a production extension, add its fixed ID as a second explicit origin, for
example `CORS_ALLOWED_ORIGINS=https://app.example.com,chrome-extension://<extension-id>`.
Do not use a wildcard Chrome-extension origin.

Optional but expected for document storage:

```bash
USE_LOCAL_DOCUMENT_STORAGE=False
AWS_ACCESS_KEY_ID=<key>
AWS_SECRET_ACCESS_KEY=<secret>
AWS_STORAGE_BUCKET_NAME=<bucket>
AWS_S3_REGION_NAME=us-east-1
AWS_S3_ENDPOINT_URL=<optional-s3-compatible-endpoint>
DOCUMENT_DOWNLOAD_TIMEOUT_SECONDS=120
DOCUMENT_DOWNLOAD_MAX_BYTES=52428800
DOCUMENT_DOWNLOAD_SPOOL_MAX_BYTES=5242880
DOCUMENT_PDF_MAX_PAGES=1000
DOCUMENT_EXTRACTED_TEXT_MAX_CHARS=5000000
```

`USE_LOCAL_DOCUMENT_STORAGE=True` is only appropriate for local development or a single-node deployment where local disk persistence is explicitly managed.

## Optional user-owned AI enhancement

AI bill enhancement is disabled by default. Users supply their own OpenAI key
through the authenticated Settings page; the deployment does not provide a
shared provider key. Set the following identically on the API, worker, and Beat
only after the evaluation and transport gates pass:

The feature architecture, API routes, user flow, request validation, durable
execution semantics, and test boundary are documented in
[LLM_ENHANCEMENTS.md](LLM_ENHANCEMENTS.md).

```bash
LLM_ENHANCEMENTS_ENABLED=True
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
LLM_ENHANCEMENT_PRODUCTION_TLS_CONFIRMED=True
LLM_ENHANCEMENT_SECRET_LOG_REDACTION_CONFIRMED=True
```

The estimated-input setting is compared with the canonical request's UTF-8 byte
count as a deliberately conservative local token bound. Revisit both request
limits when changing models, and treat the displayed value as a safety bound
rather than a provider bill or exact tokenizer count.

Keep the run lease at least 30 seconds longer than the provider timeout. Startup
and readiness checks reject a smaller margin because response validation and
persistence continue after the provider call returns.

The deterministic E2E provider is not a deployment option. Its registration is
available only through `config.settings.e2e`, and production configuration fails
closed if `LLM_ENHANCEMENT_E2E_FAKE_PROVIDER_ENABLED` is true.

Generate the Fernet key outside the repository and secret manager logs. Retain
old key-ring entries while any credential row references them.

To rotate encryption, add the new key to the ring, mark its ID active on the
API/worker/Beat, and run `python manage.py rotate_llm_credentials --execute`.
The command re-encrypts bounded batches without changing credential revisions
or validation state. Remove an old key only after the command reports complete
and no database row references its ID.

The provider key used for the non-production evaluation command is separate:

```bash
LLM_ENHANCEMENT_EVALUATION_API_KEY=<dedicated-test-key> \
python manage.py evaluate_bill_enhancements \
  --execute --case-limit 25 \
  --max-input-tokens 60000 --max-output-tokens 4000 \
  --output /secure/local/path/evaluation-results.json
```

The command prints the hard budget before its first request, makes one request
per selected case with SDK retries disabled, and writes source/output material
only when `--output` is supplied. Never configure the evaluation key in normal
API, worker, or Beat process environments. Human reviewers must score the local
artifact against the release gates in the design before production enablement.
The checked-in 25-case corpus includes the review rubric and human labels in the
artifact, plus multi-source, truncated, conflicting, cross-reference, and
prompt-injection-shaped source packets.

`/health/` reports `llm_enhancements` as `disabled`, `ok`, or `error` without
decrypting user keys or contacting OpenAI. An enabled but unsafe configuration
makes readiness fail.

Pending enhancement attempts are durable database work. A dispatch lease expiry
reuses the existing token because an earlier broker message may only be delayed;
a known publish failure clears it. Running lease expiry becomes
`outcome_unknown` and is never replayed automatically. Monitor pending age,
dispatch failures, running lease expiry, and outcome-unknown rate without
logging keys, source text, prompts, or results.

Users can open paginated historical enhancements from the bill page. Deleting a
credential does not delete those results, so key-retention and user-data policy
should treat credential rows and enhancement history as separate data classes.

## Release Commands

Run database migrations before serving traffic:

```bash
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check
```

Run the API with a production WSGI server:

```bash
gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000}
```

Run a Celery worker:

```bash
celery -A config worker -l info
```

Run Celery Beat as exactly one scheduler instance:

```bash
celery -A config beat -l info
```

Do not run multiple Beat schedulers against the same environment unless you also add a distributed scheduler/lock. Multiple Beat instances can enqueue duplicate ingestion work.

## Container deployment

The backend image installs `requirements/production.lock` with
`--require-hashes`. Regenerate that lock with Python 3.12 whenever
`requirements/base.txt` changes, audit it, and review the resulting version
changes before building the image.

The repository root includes `docker-compose.production.yml`, which runs the
API, worker, single Beat process, PostgreSQL, Redis, the standalone Next.js
client, and a one-shot migration job. Copy `.env.production.example` to
`.env.production`, replace every placeholder, then run:

```bash
docker compose -f docker-compose.production.yml --env-file .env.production up -d --build
```

The migration job runs `python manage.py migrate --noinput` after PostgreSQL
and Redis are healthy. The API, worker, and Beat wait for it to finish
successfully, so they cannot start against an unmigrated schema. Static files
are collected while building the backend image. If the migration job fails,
inspect it with:

```bash
docker compose -f docker-compose.production.yml --env-file .env.production logs migrate
```

Fix the failure, then rerun the deployment command. The compose health check
uses `/health/live/`; deploy/load-balancer readiness should use `/health/`,
which verifies the database, Redis cache, and document storage.

The production Compose file exposes the API only to the internal Compose
network on port 8000. Attach a trusted TLS-terminating ingress or reverse proxy
to that network; do not add a host `ports` mapping that bypasses HTTPS. The
browser-facing client still uses the externally routed HTTPS API URL.

## Scheduled Background Polling

Celery Beat currently schedules:

| Schedule key | Task | Interval | Purpose |
| --- | --- | ---: | --- |
| `poll-congress` | `apps.ingestion.tasks.poll_congress` | 10 minutes | Broad Congress.gov discovery for updated federal bills. |
| `poll-tracked-bills` | `apps.ingestion.tasks.poll_tracked_bills` | 5 minutes | Direct refresh for bills already relevant to user tracking. |
| `dispatch-ingestion-work` | `apps.ingestion.tasks.dispatch_ingestion_work` | 30 seconds | Sends durable discovered bill work to workers. |
| `recover-stale-ingestion-work` | `apps.ingestion.tasks.recover_stale_ingestion_work` | 5 minutes | Releases work abandoned by a worker or broker failure. |
| `sync-representatives` | `apps.ingestion.tasks.sync_representatives` | Daily | Refreshes the complete current congressional roster. |
| `ensure-changelog-partitions` | `apps.changelog.tasks.ensure_change_log_partitions_task` | Daily | Creates missing UTC ChangeLog partitions through the next 12 months. |
| `dispatch-bill-enhancements` | `apps.legislation.tasks.dispatch_bill_enhancement_attempts` | 15 seconds | Publishes delivery hints for due, user-confirmed enhancement attempts. |
| `recover-stale-bill-enhancements` | `apps.legislation.tasks.recover_stale_bill_enhancement_attempts` | 1 minute | Marks expired provider calls outcome-unknown without replaying them. |

Both schedules enqueue normal ingestion tasks. They do not store user-specific feed rows. The durable history is written to the shared `ChangeLog` table by ingestion tasks such as `process_bill`, `process_bill_votes`, document processing, and contract generation.

Contract generation enqueues `update_topics`, which deterministically infers policy topics from the bill title, summary, and contract text. Topic changes are written as persistent `topic_update` rows in `ChangeLog`.

`GET /api/tracking/feed/` reads persistent `ChangeLog` rows and filters them for the authenticated user based on tracked bills, tracked topics, and tracked legislators.

Important limitation: `poll_tracked_bills` refreshes bills that already exist in the shared corpus. Discovery of brand-new bills still depends on `poll_congress`, followed by topic assignment/sponsor data.

## Search projection rollout

After deploying the search migration, preview and then enqueue one durable
projection job per bill for each Congress being exposed in search:

```bash
python manage.py backfill_bill_search --congress 120
python manage.py backfill_bill_search --congress 120 --execute
```

Keep the normal worker and `dispatch-ingestion-work` schedule running until
`search_index` work has no pending, processing, blocked, or dead rows. Replay a
dead item only after correcting its recorded failure. During the backfill,
PostgreSQL search uses full-text vectors for projected bills and a bounded
metadata fallback only for bills that have no projection yet, so rollout does
not make existing bills disappear. Search headlines are loaded only for the
requested result page.

Representative roster detail synchronization persists each member's official
service intervals. Deploy migration `congress.0011_representative_terms` before
the next `sync-representatives` run; the daily task then refreshes the complete
current roster and replaces the associated term rows atomically. Until a
member's intervals have been populated, current members use their current
chamber as a conservative current-Congress fallback and historical insight
requests report incomplete coverage.

## ChangeLog partition migration

`changelog.0003_partition_by_created_at` converts an existing PostgreSQL
`changelog_changelog` table into monthly UTC partitions. It is transactional,
but it takes an `ACCESS EXCLUSIVE` lock and builds the replacement indexes in
that transaction. Treat it as a planned maintenance window, not a rolling
deployment:

1. Back up the database and record the current `ChangeLog` row count.
2. Quiesce the API, workers, Beat, and any long-running read/reporting jobs.
   A five-second lock timeout makes the migration fail rather than wait behind
   a live reader.
3. Run `python manage.py migrate --noinput`.
4. Verify the parent and row count, then resume API, workers, Beat, and readers:

```sql
SELECT relkind FROM pg_class WHERE oid = 'changelog_changelog'::regclass;
-- expected: p

SELECT count(*) FROM changelog_changelog;

SELECT child.relname, pg_get_expr(child.relpartbound, child.oid) AS bounds
FROM pg_inherits
JOIN pg_class parent ON parent.oid = pg_inherits.inhparent
JOIN pg_class child ON child.oid = pg_inherits.inhrelid
WHERE parent.relname = 'changelog_changelog'
ORDER BY child.relname;
```

5. Run `python manage.py ensure_changelog_partitions --months-ahead 12` once.
   It is idempotent and should normally report `created=0` immediately after
   a successful migration.

The parent has a physical primary key of `(id, created_at)`, because PostgreSQL
requires the partition key to be part of every partitioned primary key. Normal
Django inserts still use one identity sequence, but `id` is not independently
database-unique. Do not add a foreign key to `ChangeLog` or manually supply an
event ID; Django's model check and the migration reject inbound foreign keys.

## Manual Admin Controls

These ingestion endpoints are staff-only in production and local development:

```text
POST /api/ingestion/poll-congress/
POST /api/ingestion/sync-representatives/
POST /api/ingestion/backfill-documents/
POST /api/ingestion/backfill-topics/
POST /api/ingestion/bills/
```

Regular authenticated users can use tracking and feed endpoints, but cannot manually trigger ingestion:

```text
GET  /api/tracking/
GET  /api/tracking/feed/
POST /api/tracking/bills/
POST /api/tracking/topics/
POST /api/tracking/legislators/
```

## Operational Checks

Verify Django configuration:

```bash
python manage.py check
```

Verify Celery can load settings and tasks:

```bash
celery -A config inspect registered
```

Check core data counts:

```bash
python manage.py shell -c "
from apps.legislation.models import Bill
from apps.changelog.models import ChangeLog
from apps.accounts.models import TrackedBill, TrackedTopic, TrackedLegislator
print('Bills:', Bill.objects.count())
print('ChangeLog:', ChangeLog.objects.count())
print('Tracked bills:', TrackedBill.objects.count())
print('Tracked topics:', TrackedTopic.objects.count())
print('Tracked legislators:', TrackedLegislator.objects.count())
"
```

Expected production behavior:

- Celery Beat periodically enqueues polling tasks.
- Celery workers process those tasks and write shared bill/changelog updates.
- User dashboards read tracking summaries and persistent feed entries from the API.
- Staff can manually enqueue ingestion when needed; normal users cannot.
