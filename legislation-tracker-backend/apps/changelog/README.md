# `changelog` app

## Purpose

This app is the **event log** for the product: every meaningful change to a bill (status, new document version, new contract, topic change, vote) gets recorded as one row. That powers **“what changed?”** timelines, future **RSS feeds**, and **email digests** without re-scanning the whole database.

## How it works (plain English + tech)

- **ChangeLog** stores each event in **PostgreSQL** as an **append-only** row (we don’t edit old events; we add new ones).
- Each row points to a **Bill** and optionally to a **BillDocument** or **BillContract** when the event is about a specific version or interpretation.
- `change_type` is a short label (e.g. `status_update`, `vote`, `contract_update`).
- `old_value` and `new_value` are **JSON** snapshots so the API or UI can show before/after without joining many tables.

The design is meant to scale: later, the table can be **partitioned by date** in PostgreSQL for very large histories. Ingestion tasks write here when bills update, votes are recorded, etc.

## What you’ll find here

| Model | Role |
|--------|------|
| `ChangeLog` | One row per user-visible change event. |

## Who should read this

Anyone building **feeds**, **notifications**, **audit trails**, or **“recent activity”** features.
