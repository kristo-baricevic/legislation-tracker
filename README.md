# Legislation Tracker

Monorepo: **Django** API (`legislation-tracker-backend`) + **Next.js** app (`legislation-tracker-client`). Bills from Congress.gov, documents, deterministic plain-language bill briefs, change history, voting records, and (with Celery running) background ingestion. The reader-first brief explains the bill in source order, exposes every recognized financial provision without inventing a grand total, and keeps exact official text available on demand. An optional, disabled-by-default AI layer lets signed-in users enhance individual federal bills with their own OpenAI API key without changing the canonical contract.

---

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

Background work needs **Redis** and **two extra terminals** (same venv, same `legislation-tracker-backend` directory):

**Terminal A — worker**

```bash
cd legislation-tracker-backend
source .venv/bin/activate
celery -A config worker -l info
```

**Terminal B — beat (scheduler)**

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
