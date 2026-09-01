# `legislation` app

## Purpose

This app is the **core “what is a bill?”** data model. It stores the official text and metadata for bills, deterministic evidence-backed summaries (**contracts**), and how bills relate to **topics** and each other (**similarity**). Think of it as the library catalog for legislation the system tracks.

## How it works (plain English + tech)

- **PostgreSQL** holds all tables; **Django ORM** defines models like `Bill`, `BillDocument`, `BillContract`, etc.
- A **Bill** is one measure (e.g. “HR 7898” in Congress 119): title, status, sponsor link, hashes for change detection, and processing state.
- **BillDocument** is a specific **version** of the bill text (introduced, engrossed, enrolled…), with a **source URL** (often from Congress.gov) and optional **S3** keys when files are stored (Phase 4). The `is_active_version` flag marks the “current” version for display.
- **BillContract** is the structured, plain-language interpretation of a document version (`contract_json`), with a hash so we know when the interpretation changed.
- **EvidenceSpan** ties contract fields back to **exact spans** in the source text (for transparency and citations).
- **Topic** / **BillTopic** support tagging bills for search and feeds.
- **BillSimilarity** stores precomputed “related bill” scores for recommendations.

The **Django REST Framework (DRF)** exposes read-only **list/detail APIs** for bills (`/api/bills/`) so the **Next.js** frontend can show tables and detail pages.

**Phase 4 — document files:** **`download_document`** (Celery, in `ingestion` app) saves bytes to **django-storages** targeting **MinIO** (local, free) or **filesystem** (`USE_LOCAL_DOCUMENT_STORAGE=True`).

**Phase 5 — contract layer:** **`generate_contract`** selects the federal
`2.0-legal-nlp` pipeline by default, or the immutable `2.1-legal-nlp`
reader-first pipeline when its write gate is enabled. The compatible
`1.1-deterministic` fallback remains available for unsupported input. Generation
hashes the result with **`contract_json.canonical_json_string`**, creates
**`BillContract`** / **`EvidenceSpan`**, and enqueues topic and similarity work.
Every version validates its JSON Schema and exact source spans before
persistence. Schema-only backfills use semantic comparison and suppress bill
activity, unread updates, and topic/contract ChangeLog noise. Full write-up:
**[docs/PHASE_5_CONTRACT.md](../../docs/PHASE_5_CONTRACT.md)**.

The public bill response is compact. A 2.1 contract exposes orientation and
counts there, while substantive arrays and evidence are available through
bounded contract endpoints:

- `/api/contracts/{id}/reader-items/`
- `/api/contracts/{id}/financial-items/`
- `/api/contracts/{id}/timeline-items/`
- `/api/contracts/{id}/definition-items/`
- `/api/contracts/{id}/evidence/` (requires exactly one reader item ID)

The bill's complete official summary is also loaded separately after explicit
reader action. Legacy and 2.0 contracts continue to use their existing API and
client projections.

## What you’ll find here

| Model | Role |
|--------|------|
| `Bill` | Canonical bill metadata. |
| `BillDocument` | Per-version text/source metadata. |
| `BillContract` | Interpreted “contract” JSON per document. |
| `EvidenceSpan` | Links contract fields to source text. |
| `Topic`, `BillTopic` | Policy tags. |
| `BillSimilarity` | Pairwise similarity between bills. |

Key contract files:

| File | Role |
|---|---|
| `extraction/federal_structure.py` | Offset-preserving federal hierarchy and clause parser. |
| `extraction/legal_rules.py` | Deterministic legal claim, timeline, and definition rules. |
| `extraction/financial_rules.py` | Distinct, uncapped financial-action extraction. |
| `extraction/renderer.py` | Immutable controlled 2.0 language and evidence paths. |
| `extraction/reader_renderer.py` | Controlled 2.1 reader lines, associations, and evidence chunks. |
| `extraction/schema.py` | Contract, association, and exact-evidence validation. |
| `extraction/service.py` | Write-gated 2.1/2.0 selection and expected v1 fallback. |
| `reader_api.py` | Bounded public reader projections and official-summary projection. |
| `management/commands/backfill_contracts.py` | Preview-first durable backfill. |

## Who should read this

Anyone changing **bill storage**, **documents**, **contracts**, or the **public bill API**.
