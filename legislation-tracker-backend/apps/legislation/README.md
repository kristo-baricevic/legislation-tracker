# `legislation` app

## Purpose

This app is the **core “what is a bill?”** data model. It stores the official text and metadata for bills, optional AI-style summaries (**contracts**), and how bills relate to **topics** and each other (**similarity**). Think of it as the library catalog for legislation the system tracks.

## How it works (plain English + tech)

- **PostgreSQL** holds all tables; **Django ORM** defines models like `Bill`, `BillDocument`, `BillContract`, etc.
- A **Bill** is one measure (e.g. “HR 7898” in Congress 119): title, status, sponsor link, hashes for change detection, and processing state.
- **BillDocument** is a specific **version** of the bill text (introduced, engrossed, enrolled…), with a **source URL** (often from Congress.gov) and optional **S3** keys when files are stored (Phase 4). The `is_active_version` flag marks the “current” version for display.
- **BillContract** is the structured, plain-language interpretation of a document version (`contract_json`), with a hash so we know when the interpretation changed.
- **EvidenceSpan** ties contract fields back to **exact spans** in the source text (for transparency and citations).
- **Topic** / **BillTopic** support tagging bills for search and feeds.
- **BillSimilarity** stores precomputed “related bill” scores (future use for recommendations).

The **Django REST Framework (DRF)** exposes read-only **list/detail APIs** for bills (`/api/bills/`) so the **Next.js** frontend can show tables and detail pages.

**Phase 4 — document files:** **`download_document`** (Celery, in `ingestion` app) saves bytes to **django-storages** targeting **MinIO** (local, free) or **filesystem** (`USE_LOCAL_DOCUMENT_STORAGE=True`).

**Phase 5 — contract layer:** **`generate_contract`** builds a **stub** `contract_json` (title + excerpt + version), hashes it with **`contract_json.canonical_json_string`**, creates **`BillContract`** / **`EvidenceSpan`** / **`ChangeLog`**, and enqueues Phase 6 stubs. Full write-up: **[docs/PHASE_5_CONTRACT.md](../../docs/PHASE_5_CONTRACT.md)**.

## What you’ll find here

| Model | Role |
|--------|------|
| `Bill` | Canonical bill metadata. |
| `BillDocument` | Per-version text/source metadata. |
| `BillContract` | Interpreted “contract” JSON per document. |
| `EvidenceSpan` | Links contract fields to source text. |
| `Topic`, `BillTopic` | Policy tags. |
| `BillSimilarity` | Pairwise similarity between bills. |

## Who should read this

Anyone changing **bill storage**, **documents**, **contracts**, or the **public bill API**.
