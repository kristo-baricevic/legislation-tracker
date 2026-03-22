# Legislation Tracker Backend

Django backend for the legislation tracker: bills, documents, structured contracts, change log, and feeds.

See [BACKEND_PLAN.md](../BACKEND_PLAN.md) and [ARCHITECTURE_ELI5.md](../ARCHITECTURE_ELI5.md) in the repo root for architecture. Build steps: [BACKEND_BUILD_STEPS.md](../BACKEND_BUILD_STEPS.md).

## Quick start (local) — Postgres

The backend is set up to use **PostgreSQL** by default when you use the provided `.env`. Follow these steps in order.

### 1. Start Postgres (and Redis, MinIO)

```bash
cd legislation-tracker-backend
docker compose up -d
```

Wait until Postgres is ready (a few seconds). Check with:

```bash
docker compose exec postgres pg_isready -U legislation
```

You should see `legislation:5432 - accepting connections`.

### 2. Environment

```bash
cp .env.example .env
# Edit .env: set DJANGO_SECRET_KEY (required). Optionally set CONGRESS_API_KEY, GOVINFO_API_KEY.
# .env.example already has DATABASE_URL pointing at Postgres and REDIS_URL.
```

- The `.env` file must live in **legislation-tracker-backend/** (same directory as `manage.py`), not in the repo root.
- For Congress ingestion use **CONGRESS_API_KEY** (get a key at https://api.congress.gov). Use `CONGRESS_API_KEY=your-key` with no spaces around `=`. After changing `.env`, **restart the Celery worker** so it picks up the new value.

**Verify the key is loaded:** from the backend directory run  
`python manage.py shell -c "from django.conf import settings; k=getattr(settings,'CONGRESS_API_KEY',''); print('CONGRESS_API_KEY loaded:', bool(k), 'length:', len(k))"`  
You should see `CONGRESS_API_KEY loaded: True length: <number>`.

`.env.example` uses `DATABASE_URL=postgres://legislation:legislation@localhost:5432/legislation`. Do not change this if you use `docker compose` for Postgres.

### 3. Python env and deps

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements/dev.txt
```

### 4. Database (migrate against Postgres)

With Postgres running and `.env` in place:

```bash
python manage.py migrate
python manage.py createsuperuser  # optional, for /admin/
```

### 5. Run server

```bash
python manage.py runserver
```

API: http://localhost:8000/admin/ (after creating a superuser). Auth API: http://localhost:8000/api/auth/.

**One-shot setup (script):**

```bash
bash scripts/setup-postgres.sh
```

This starts Docker (Postgres, Redis, MinIO), waits for Postgres, and copies `.env.example` to `.env` if missing. Then run the "Next steps" it prints (venv, pip install, migrate, runserver).

### Postgres without Docker (local install)

To use a **locally installed** PostgreSQL instead of Docker:

**1. Install Postgres**

- **macOS (Homebrew):** `brew install postgresql@16` then `brew services start postgresql@16`.  
  Ensure the `postgres` (or `psql`) commands are on your PATH; Homebrew will show the path to add (e.g. `export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"`).
- **Ubuntu/Debian:** `sudo apt install postgresql postgresql-client`
- **Windows:** install from [postgresql.org](https://www.postgresql.org/download/windows/) and start the service.

**2. Create the database and user** (once)

Using the same name/password as `.env.example` so `DATABASE_URL` works as-is:

```bash
# Connect as the default superuser (often your macOS user, or postgres on Linux)
psql postgres

# In psql:
CREATE USER legislation WITH PASSWORD 'legislation' CREATEDB;
CREATE DATABASE legislation OWNER legislation;
\q
```

Or run the script (uses `psql`; works when Postgres is installed locally):

```bash
bash scripts/setup-postgres-local.sh
```

**3. Use the same `.env`**

Your `.env` can keep:

```bash
DATABASE_URL=postgres://legislation:legislation@localhost:5432/legislation
```

**4. Migrate and run**

```bash
python manage.py migrate
python manage.py runserver
```

Redis and MinIO are still optional (Celery/S3). For Redis without Docker: `brew install redis && brew services start redis` (macOS).

### Using SQLite instead of Postgres

If you prefer not to run Postgres at all, in `.env` set:

```bash
DATABASE_URL=sqlite:///./db.sqlite3
```

Then run `python manage.py migrate` and `python manage.py runserver` as above. Redis and MinIO are still optional for Celery and S3.

### 6. Celery (Phase 3 ingestion)

With **Redis** running (e.g. `docker compose up -d` or `brew services start redis`):

**Start worker** (one terminal):

```bash
cd legislation-tracker-backend
source .venv/bin/activate   # if using venv
celery -A config worker -l info
```

**Start Beat** (second terminal):

```bash
cd legislation-tracker-backend
source .venv/bin/activate
celery -A config beat -l info
```

The Celery app sets `DJANGO_SETTINGS_MODULE=config.settings.dev` by default so you don’t need to export it. To use production settings, set `DJANGO_SETTINGS_MODULE=config.settings.prod` before running Celery.

**Trigger `poll_congress` once** (third terminal or after worker/beat are running):

```bash
cd legislation-tracker-backend
source .venv/bin/activate
python manage.py shell -c "
from apps.ingestion.tasks import poll_congress
r = poll_congress.delay()
print('Enqueued:', r.get(timeout=30))
"
```

**Confirm Bills and ChangeLog rows:**

```bash
python manage.py shell -c "
from apps.legislation.models import Bill
from apps.changelog.models import ChangeLog
print('Bills:', Bill.objects.count())
print('ChangeLog entries:', ChangeLog.objects.count())
for b in Bill.objects.all()[:5]:
    print(' ', b.bill_number, b.title[:50] if b.title else '')
"
```

## Project layout

```
legislation-tracker-backend/
├── config/           # Django project (settings, urls, wsgi, asgi, celery)
├── apps/             # accounts, legislation, congress, changelog, ingestion (Phase 2+)
├── requirements/
├── manage.py
├── docker-compose.yml
├── .env.example
└── README.md
```

Each app under `apps/` has its own **README.md** describing purpose, how it fits the stack, and main models or tasks:

| App | README |
|-----|--------|
| `accounts` | [apps/accounts/README.md](apps/accounts/README.md) |
| `legislation` | [apps/legislation/README.md](apps/legislation/README.md) |
| `congress` | [apps/congress/README.md](apps/congress/README.md) |
| `changelog` | [apps/changelog/README.md](apps/changelog/README.md) |
| `ingestion` | [apps/ingestion/README.md](apps/ingestion/README.md) |

## Settings

- **config.settings.dev** — default for `runserver` and local Celery (DEBUG=True, AllowAny for DRF).
- **config.settings.prod** — DEBUG=False; requires DJANGO_SECRET_KEY and ALLOWED_HOSTS.

Override with `DJANGO_SETTINGS_MODULE=config.settings.prod` when running in production.

## MinIO (S3-compatible storage)

After `docker compose up -d`, MinIO is at http://localhost:9000 (console: 9001). Create a bucket named `legislation-tracker-documents` via the console or:

```bash
docker compose exec minio mc alias set local http://localhost:9000 minioadmin minioadmin
docker compose exec minio mc mb local/legislation-tracker-documents
```

(Requires `mc` in the MinIO container; newer MinIO images may use a different approach.)

## Tests

```bash
pytest
# or
python manage.py test
```
