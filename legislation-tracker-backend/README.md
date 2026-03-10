# Legislation Tracker Backend

Django backend for the legislation tracker: bills, documents, structured contracts, change log, and feeds.

See [BACKEND_PLAN.md](../BACKEND_PLAN.md) and [ARCHITECTURE_ELI5.md](../ARCHITECTURE_ELI5.md) in the repo root for architecture. Build steps: [BACKEND_BUILD_STEPS.md](../BACKEND_BUILD_STEPS.md).

## Quick start (local)

### 1. Services (Postgres, Redis, MinIO)

```bash
cd legislation-tracker-backend
docker compose up -d
```

### 2. Python env and deps

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements/dev.txt
```

### 3. Environment

```bash
cp .env.example .env
# Edit .env: set DJANGO_SECRET_KEY, CONGRESS_API_KEY, GOVINFO_API_KEY.
# For local with Docker, use:
#   DATABASE_URL=postgres://legislation:legislation@localhost:5432/legislation
#   REDIS_URL=redis://localhost:6379/0
#   AWS_S3_ENDPOINT_URL=http://localhost:9000
```

### 4. Database

```bash
python manage.py migrate
python manage.py createsuperuser  # optional
```

### 5. Run server

```bash
python manage.py runserver
```

API: http://localhost:8000/admin/ (after creating a superuser).

### 6. Celery (optional for Phase 1)

With Redis running:

```bash
# Terminal 2: worker
celery -A config worker -l info

# Terminal 3: beat (scheduler)
celery -A config beat -l info
```

Set `DJANGO_SETTINGS_MODULE=config.settings.dev` if needed (manage.py defaults to it).

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
