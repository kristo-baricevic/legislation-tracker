# Legislation Tracker

Monorepo: **Django** API (`legislation-tracker-backend`) + **Next.js** app (`legislation-tracker-client`). Bills from Congress.gov, documents, plain-language “contracts,” change log, and (with Celery running) background ingestion.

---

## Run everything locally (no Docker)

Use this path if you have **PostgreSQL** and **Redis** installed on your machine (Homebrew, apt, or postgres.org — not Docker containers).

### What to install first

| Piece | Role |
|--------|------|
| **Python 3.11+** | Backend |
| **PostgreSQL** | Main database |
| **Redis** | Celery queue (ingestion, downloads, contract generation) |
| **Node.js 18+** | Frontend |

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

---

### 5. Frontend (Next.js)

```bash
cd legislation-tracker-client
npm install
npm run dev
```

App: **http://localhost:3000**

The client expects the API at **http://localhost:8000** by default. To change that, set **`NEXT_PUBLIC_API_URL`** in `legislation-tracker-client/.env.local`.

---

### Quick reference

| Service | URL |
|--------|-----|
| Next.js app | http://localhost:3000 |
| Django API | http://127.0.0.1:8000 |
| Django admin | http://127.0.0.1:8000/admin/ |

---

## More documentation

- **Backend detail:** [legislation-tracker-backend/README.md](legislation-tracker-backend/README.md) (includes Docker-based Postgres/Redis/MinIO if you prefer that later.)
- **Build phases / checklist:** [BACKEND_BUILD_STEPS.md](BACKEND_BUILD_STEPS.md)
- **Architecture:** [BACKEND_PLAN.md](BACKEND_PLAN.md), [ARCHITECTURE_ELI5.md](ARCHITECTURE_ELI5.md)
