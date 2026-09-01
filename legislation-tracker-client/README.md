# Legislation Tracker (frontend)

**Full-stack local setup (Postgres + Redis + Django + Celery + this app, without Docker):** see the **[root README](../README.md)**.

## Getting Started

Use Node.js 22 and the pnpm version pinned in `package.json`, then run the development server (the backend should be running separately):

```bash
corepack enable
pnpm install --frozen-lockfile
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

### Auth (login / sign up)

The app has **Log in** and **Sign up** pages that use the Django web-session API. To use them:

1. Run the backend (`legislation-tracker-backend`) and ensure it is available at `http://localhost:8000` (or set `NEXT_PUBLIC_API_URL` in `.env.local` to your backend URL).
2. Create an account at `/signup`, then log in at `/login`. JWTs stay in secure HttpOnly cookies; the web app does not store them in `localStorage`.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

### Reader-first bill brief

Federal bills with a `2.1-legal-nlp` contract open with a compact orientation:
the latest attributed CRS summary when available, or an honest notice when no
CRS summary has been published, plus any explicit purpose found in the bill,
policy areas, and extraction counts. The substantive brief then loads bounded
pages in official source order rather than ranking provisions.

The financial breakdown includes every recognized appropriation,
authorization, allocation, transfer, rescission, reduction, cancellation,
set-aside, limitation, and other explicit financial action. It is never capped
to a "top" list and the UI does not add unlike amounts into a misleading grand
total. Exact-clause financial links appear beneath the matching plain-English
line; broader account or program provisions appear once at section level.
Readers can load evidence text, deadlines/effective dates, definitions, full
official summaries, and the complete grouped voting record on demand.

Older `1.1-deterministic` and `2.0-legal-nlp` contracts retain their compatible
renderers. A malformed or unavailable 2.1 projection fails back to that safe
legacy display rather than exposing internal contract data.

### Optional AI enhancement UI

When the backend enables user-owned AI enhancement, authenticated users can
save and validate their own OpenAI key at `/settings`. Eligible federal bill
pages then show a confirmation flow, asynchronous status, source-cited result,
and paginated private history. State bills explain the current federal-only
scope without making private credential or enhancement requests.

The browser never receives a saved key from the API. See the backend
[AI enhancement guide](../legislation-tracker-backend/docs/LLM_ENHANCEMENTS.md)
for the complete API, security, execution, and test contracts.

### Representative browser journey on PostgreSQL

The representative-insights journey uses the real Django API and a seeded
PostgreSQL database. From the backend directory, start the isolated database:

```bash
docker compose -f docker-compose.e2e-postgres.yml up -d
```

Then, from this directory, run:

```bash
E2E_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/legislation_e2e \
  pnpm test:e2e -- e2e/representative-insights.spec.ts
```

The E2E API bootstrap reads that URL, migrates the database, and seeds the
bill, member, committee, and roll-call evidence used by the journey. Tear the
database down with `docker compose -f docker-compose.e2e-postgres.yml down -v`
from `legislation-tracker-backend/` when it is no longer needed.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## govinfo api docs

<https://github.com/usgpo/api>
