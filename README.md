# Legislation Tracker

Monorepo: **Django** API (`legislation-tracker-backend`) + **Next.js** app (`legislation-tracker-client`). Bills from Congress.gov, documents, deterministic plain-language bill briefs, change history, voting records, and (with Celery running) background ingestion. The reader-first brief explains the bill in source order, exposes every recognized financial provision without inventing a grand total, and keeps exact official text available on demand. An optional, disabled-by-default AI layer lets signed-in users enhance individual federal bills with their own OpenAI API key without changing the canonical contract.

---

## Run the complete app in Docker

From this repository root, copy `.env.docker.example` to `.env.docker` and fill in
the required Congress API key, FEC API key, and Django secret. Then run:

```bash
rtk proxy bash scripts/docker-up.sh
```

Open http://localhost:13000. This starts PostgreSQL, Redis, document storage,
the API, frontend, ingestion worker, similarity worker, research worker, enhancement worker, and
Celery Beat scheduler. Configuration checks and migrations must succeed before
the app and workers start. Configuration is shared by every backend service.
The backend-directory Compose file is **dependencies only**, not an app launcher.

Each ingestion stage has its own queue and single-process worker: bill metadata,
text versions, relationships, bill votes, roll calls, downloads, document
analysis, metadata analysis, topics, search indexing, representative details,
and committee rosters. Bill discovery and vote discovery also have separate
workers. The default `celery` worker coordinates dispatch and recovery.
Similarity runs six processes; research and enhancement run two each.
Their pool sizes can be overridden with `SIMILARITY_WORK_CONCURRENCY`,
`RESEARCH_WORK_CONCURRENCY`, and `ENHANCEMENT_WORK_CONCURRENCY`.
Each ingestion stage admits at most two dispatched/running durable jobs by
default (`INGESTION_STAGE_IN_FLIGHT`); a backlog in one stage cannot fill
another stage's slots. Already-queued legacy messages drain without purging.

For an existing installation, set `EXISTING_VOLUMES=true` and the volume names in `.env.docker` to the
existing volumes **before starting**. Stop the old app workers, scheduler, and
database/storage containers first; never run two PostgreSQL servers against the
same volume or two schedulers against the same queue. Do not use `down -v`.
Stop this stack with `rtk proxy docker compose --env-file .env.docker down`;
named volumes remain intact.

Enhancement workers start automatically. Explicitly set enhancement enablement
in `.env.docker`, preserving the existing app's setting. Enabling it requires the encryption
key ring and active key ID; restore the original keys when reusing a database.
The startup command rejects incomplete enhancement configuration. It does not
create replacement encryption keys or automatically launch paid enhancements.

Startup regression tests:
`rtk proxy python3 -m unittest discover -s scripts -p 'test_*.py'`.
Run after building the backend image. These also check installed runtime
dependencies and portrait processing without network or database access.
Set `BACKEND_TEST_IMAGE` to test a separately tagged backend image.

## Run everything locally (no Docker)

Use this path if you have **PostgreSQL** and **Redis** installed on your machine (Homebrew, apt, or postgres.org — not Docker containers).

### What to install first

| Piece            | Role                                                     |
| ---------------- | -------------------------------------------------------- |
| **Python 3.12**  | Backend and production dependency lock                   |
| **PostgreSQL**   | Main database                                            |
| **Redis**        | Celery queue (ingestion, downloads, contract generation) |
| **Node.js 22**   | Frontend                                                 |
| **pnpm 11**      | Frontend package manager (version pinned in `package.json`) |

---

### 1. PostgreSQL (local)

Create the DB user and database once (same names as `.env.example`):

```bash
psql postgres
```

In `psql`:

```sql
CREATE USER legislation WITH PASSWORD 'legislation' CREATEDB;
CREATE DATABASE legislation OWNER legislation;
\q
```

Or run the helper (from the backend folder, with `psql` on your PATH):

```bash
cd legislation-tracker-backend
bash scripts/setup-postgres-local.sh
```

**macOS (Homebrew) example:** `brew install postgresql@16` and `brew services start postgresql@16`, then add the `bin` directory to your `PATH` if the installer suggests it.

---

### 2. Redis (local)

**macOS:** `brew install redis && brew services start redis`  
**Linux:** `sudo apt install redis-server && sudo systemctl start redis` (or your distro’s equivalent)

Redis should listen on **localhost:6379** (matches `REDIS_URL` in `.env.example`).

---

### 3. Backend environment and database

```bash
cd legislation-tracker-backend
cp .env.example .env
```

Edit **`.env`** (in this folder, next to `manage.py`):

- Set **`DJANGO_SECRET_KEY`** to a long random string (required).
- Optionally set **`CONGRESS_API_KEY`** for live ingestion ([api.congress.gov](https://api.congress.gov)).

Keep **`DATABASE_URL=postgres://legislation:legislation@localhost:5432/legislation`** if you used the user/database above.  
Keep **`REDIS_URL=redis://localhost:6379/0`** if Redis is local on the default port.

**Document storage without MinIO:** add to `.env` so PDFs go to disk under `local_media/`:

```bash
USE_LOCAL_DOCUMENT_STORAGE=True
```

Then:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements/dev.txt
python manage.py migrate
python manage.py createsuperuser   # optional — for /admin/
python manage.py runserver
```

API: **http://127.0.0.1:8000/** — admin at `/admin/`, auth under `/api/auth/`.

---

### 4. Celery (ingestion, scheduled polls, file downloads, contracts)

Background work needs **Redis**, three workers and a scheduler, each in its own terminal (same venv, same `legislation-tracker-backend` directory):

**Workers — one command per terminal**

```bash
cd legislation-tracker-backend
source .venv/bin/activate
celery -A config worker -Q celery -l info
# Separate terminals: user-requested work must not wait behind ingestion.
celery -A config worker -Q enhancements --concurrency=1 --prefetch-multiplier=1 -n enhancements@%h -l info
celery -A config worker -Q research --concurrency=1 --prefetch-multiplier=1 -n research@%h -l info
celery -A config worker -Q similarity --concurrency=1 --prefetch-multiplier=1 -n similarity@%h -l info
```

**Separate terminal — beat (scheduler)**

```bash
cd legislation-tracker-backend
source .venv/bin/activate
celery -A config beat -l info
```

The Django app alone will run without Celery; **polling Congress, downloading documents, and generating contracts** only run when the worker (and usually Beat) are up.

The current reader contract writer is deliberately gated. Leave
`LEGAL_NLP_V21_WRITE_ENABLED=False` until the compatible API and frontend have
been deployed and verified; see the
**[contract rollout guide](legislation-tracker-backend/docs/PHASE_5_CONTRACT.md)**.

---

### 5. Frontend (Next.js)

```bash
cd legislation-tracker-client
corepack enable
pnpm install --frozen-lockfile
pnpm dev
```

App: **http://localhost:3000**

The client expects the API at **http://localhost:8000** by default. To change that, set **`NEXT_PUBLIC_API_URL`** in `legislation-tracker-client/.env.local`.

### Optional user-owned AI enhancements

The feature is federal-only, private to the signed-in user, and disabled by
default. Users save and validate their own provider key under `/settings`, then
explicitly confirm a bounded request from an eligible bill page. Results include
server-owned cited-source text and paginated private history; they never modify
the deterministic contract or trigger automatically during ingestion.

Enabling the feature requires a dedicated Fernet key ring, the Django API,
Celery worker and Beat processes, secure production transport, and explicit
provider configuration. See the
**[AI enhancement guide](legislation-tracker-backend/docs/LLM_ENHANCEMENTS.md)**
for behavior and APIs, and
**[production operations](legislation-tracker-backend/docs/PRODUCTION_OPERATIONS.md)**
for rollout and key-rotation instructions.

---

### Quick reference

| Service      | URL                          |
| ------------ | ---------------------------- |
| Next.js app  | http://localhost:3000        |
| Django API   | http://127.0.0.1:8000        |
| Django admin | http://127.0.0.1:8000/admin/ |

---

## More documentation

Before opening a pull request, run the complete local verification gate from
the repository root:

```bash
./scripts/check-local.sh
```

It runs backend checks/tests/lint/dependency audit, frontend tests/typecheck/
lint/audit/production build, and the extension test and syntax checks. GitHub
Actions remain intentionally deferred.

- **Backend detail:** [legislation-tracker-backend/README.md](legislation-tracker-backend/README.md) (includes Docker-based Postgres/Redis/MinIO if you prefer that later.)
- **Deterministic bill briefs and rollout:** [legislation-tracker-backend/docs/PHASE_5_CONTRACT.md](legislation-tracker-backend/docs/PHASE_5_CONTRACT.md)
- **User-owned AI enhancements:** [legislation-tracker-backend/docs/LLM_ENHANCEMENTS.md](legislation-tracker-backend/docs/LLM_ENHANCEMENTS.md)
- **Production operations:** [legislation-tracker-backend/docs/PRODUCTION_OPERATIONS.md](legislation-tracker-backend/docs/PRODUCTION_OPERATIONS.md)
- **Build phases / checklist:** [BACKEND_BUILD_STEPS.md](BACKEND_BUILD_STEPS.md)
- **Architecture:** [BACKEND_PLAN.md](BACKEND_PLAN.md), [ARCHITECTURE_ELI5.md](ARCHITECTURE_ELI5.md)
