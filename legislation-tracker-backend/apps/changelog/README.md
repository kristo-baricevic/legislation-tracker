# `changelog` app

## Purpose

This app is the **event log** for the product: every meaningful change to a bill (status, new document version, new contract, topic change, vote) gets recorded as one row. That powers **“what changed?”** timelines, future **RSS feeds**, and **email digests** without re-scanning the whole database.

## How it works (plain English + tech)

- **ChangeLog** stores each event in **PostgreSQL** as an **append-only** row (we don’t edit old events; we add new ones). PostgreSQL stores those rows in monthly UTC partitions; SQLite keeps one ordinary table for local development.
- Each row points to a **Bill** and optionally to a **BillDocument** or **BillContract** when the event is about a specific version or interpretation.
- `change_type` is a short label (e.g. `status_update`, `vote`, `contract_update`).
- `old_value` and `new_value` are **JSON** snapshots so the API or UI can show before/after without joining many tables.

The partitioned parent keeps the same `changelog_changelog` name, so ingestion
tasks and the Django ORM keep writing normally. There is deliberately no
default partition: an out-of-range event fails visibly instead of being hidden
in storage that cannot later be attached to the monthly hierarchy.

PostgreSQL requires a partitioned primary key to include the partition key, so
the physical key is `(id, created_at)`. Normal inserts still use a single,
global identity sequence, but PostgreSQL no longer guarantees `id` uniqueness
by itself. Do not manually assign event IDs or add a foreign key to
`ChangeLog`; a Django system check and the conversion migration reject inbound
foreign keys.

`python manage.py ensure_changelog_partitions --months-ahead 12` is safe to run
repeatedly. Celery Beat also runs the same maintenance daily.

## What you’ll find here

| Model | Role |
|--------|------|
| `ChangeLog` | One row per user-visible change event. |

## Who should read this

Anyone building **feeds**, **notifications**, **audit trails**, or **“recent activity”** features.
